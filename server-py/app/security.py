"""JWT 签发/解析、BCrypt 密码、认证鉴权中间件。

顺序与 Spring 拦截器一致：先解析令牌（401）→ 再校验角色（403）→ 之后才轮到参数/请求体校验。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

import bcrypt
import jwt
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .errors import BizException
from .responses import fail

_cfg = settings()
JWT_SECRET = _cfg["jwt_secret"]
JWT_EXPIRE_HOURS = _cfg["jwt_expire_hours"]

BEARER_PREFIX = "Bearer "


@dataclass
class LoginUser:
    id: int
    username: str
    role: str  # MEMBER(普通成员·只读) / ADMIN(生活委员) / MONITOR(班长) / TEACHER(班主任) / DEAN(院长·系统管理员)
    class_id: int
    # 第三十轮：**只有 DEAN 用得上**。1 = 纯院长（只管学院，不参与班级事务）。
    #
    # ⚠ 它**不进 JWT**：JWT 是无状态的，签发后就固定了。而这个标志要能
    # **即时生效**（把一个人从「兼班主任」改成「纯院长」后立刻生效），
    # 靠的是鉴权中间件里那次本来就有的主键查询（见 `_account_active`）——
    # 和 `status`（停用）同一条路子。
    dean_only: bool = False


# ---------------- 密码 ----------------

def _pw_bytes(raw: str) -> bytes:
    b = raw.encode("utf-8")
    # bcrypt 算法密钥上限 72 字节（python-bcrypt 超长会抛错，截断对齐 OpenBSD 行为）
    return b[:72]


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(_pw_bytes(raw), bcrypt.gensalt(rounds=10)).decode("ascii")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_pw_bytes(raw), hashed.encode("ascii"))
    except ValueError:
        # 密文格式非法（非 BCrypt）：等价视为不匹配
        return False


# ---------------- JWT（HS256） ----------------

def create_token(user: LoginUser) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "classId": user.class_id,
        "iat": now,
        "exp": now + JWT_EXPIRE_HOURS * 3600,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def parse_token(token: str) -> LoginUser:
    """解析失败（含过期/签名错/claims 缺失）→ 401 登录已过期，请重新登录。"""
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return LoginUser(
            id=int(claims["sub"]),
            username=str(claims["username"]),
            role=str(claims["role"]),
            class_id=int(claims["classId"]),
        )
    except Exception as e:  # noqa: BLE001  —— 对齐 JwtUtil：任何解析失败统一 401 文案
        raise BizException.unauthorized("登录已过期，请重新登录") from e


# ---------------- 路由角色表（对应各控制器 @RequireRole） ----------------

# 免鉴权端点。`/api/version` 在列：登录页要在**还没登录时**就显示版本号
# （出问题时第一眼看到的就是「我跑的是哪一版」）。它只回常量，无业务数据。
PUBLIC_ROUTES = {
    ("POST", "/api/auth/login"),
    ("GET", "/api/version"),
}

# 运营角色：ADMIN（生活委员）/ MONITOR（班长）/ TEACHER（班主任）/ DEAN（院长）
# **记账权限**同权（第七轮起 TEACHER=全权运营：财务 + 成员管理；
# 第十四轮新增 MONITOR 承载「班长」称谓；第二十八轮新增 DEAN 作为系统管理员）。
#
# DEAN 进 STAFF_ROLES 的理由：它是**最高级运营角色**，「记账/成员管理」这套权限
# 对它是「全都要」，不是「另开一套」。真要给它单独一套权限，就得在 `_STAFF_ROUTES`
# 里另起分支——而那会让「院长能记账、班主任不能」这种话说不通。
STAFF_ROLES = frozenset({"ADMIN", "MONITOR", "TEACHER", "DEAN"})

# ---------------- 账号管理权限等级（第十五轮） ----------------
# 记账权限同权 ≠ 管理权限同权。**院长 > 班主任 > 班长 > 生活委员 > 普通成员**：
# 低等级角色不能改动/停用/删除高等级角色的账号，否则班长能把班主任踢下线。
# 数字越大权限越高；MEMBER=0（只读，不参与账号管理）。
#
# DEAN（院长，第二十八轮）：**系统管理员**，等级压在班主任之上（4 > 3）。
# 「默认院长是管理员」这句落在这里——院长是等级最高的那一档，能管理所有低档角色，
# 包括班主任自己。等级差一档就够表达「系统管理员」了，不需要另起一套并行体系。
ROLE_LEVEL: dict[str, int] = {
    "MEMBER": 0,
    "ADMIN": 1,    # 生活委员
    "MONITOR": 2,  # 班长
    "TEACHER": 3,  # 班主任
    "DEAN": 4,     # 院长（系统管理员，等级最高）
}

#: 院长角色名（第三十轮起被中间件直接引用）。
#:
#: 提成常量的理由：这个字面量同时出现在等级表、纯院长判定多处，写错一个字母就是
#: 「某道权限闸门整体失效」，而且**不报错**。
DEAN_ROLE = "DEAN"


def role_level(role: str | None) -> int:
    """角色等级；未知角色按 0（最弱）处理，缺省安全。"""
    return ROLE_LEVEL.get(role or "", 0)


def require_min_level(user: LoginUser, need_role: str, what: str) -> None:
    """等级不足就 403。用于「按角色分档」的**管理级能力**（如管理看板）。

    和 `require_role_higher` 的区别：那个管的是「你能不能改**某人**」，
    这个管的是「你能不能用**某项能力**」。两者都是按等级判，但语义不同，
    混用会写出「能管班主任的人却看不了管理看板」这种自相矛盾的东西。

    用等级而不是 `user.role == "DEAN"`：等级是一贯的权威来源，
    将来在院长之上再加一档，这里自动生效，不用回来补。

    ⚠ **前端也要拦**：这个函数只保证接口不给数据。界面侧同样要**不渲染入口**
    —— 让班主任看到一个点进去就报 403 的入口，比看不到更糟。
    """
    floor = role_level(need_role)
    if role_level(user.role) < floor:
        raise BizException.forbidden(f"{what}仅限院长及以上查看")


def require_role_higher(actor_role: str, target_role: str) -> None:
    """账号管理护栏：操作者的等级必须**严格高于**目标账号。

    覆盖「编辑资料 / 重置密码 / 停用 / 删除」四类账号管理动作：

    - 低级不能动高级（班长/生活委员动不了班主任）
    - 同级不能互动（避免两个班长相向踢下线）
    - 「自己不动自己」不在这里判：停用/删除自己由各接口给出更贴切的提示语
    """
    actor, target = role_level(actor_role), role_level(target_role)
    if target < actor:
        return
    if target == actor:
        raise BizException.bad_request(
            f"权限不足：不能管理与自己同级的账号（对方角色：{target_role}）"
        )
    raise BizException.bad_request(
        f"权限不足：你的角色不能管理更高权限的账号（对方角色：{target_role}）"
    )


# (method, path 正则)；表内路径仅运营角色可访问，其余 /api 路径=任意登录角色
# （公告/班级信息：GET 全员可读，写操作才进本表）
_STAFF_ROUTES: list[tuple[str, str]] = [
    ("POST", r"^/api/records$"),
    ("POST", r"^/api/records/[^/]+/void$"),
    ("DELETE", r"^/api/records/[^/]+$"),
    ("GET", r"^/api/records/export$"),
    ("POST", r"^/api/files$"),  # 小票上传随记账权限（GET /api/files/* 查看对登录角色开放）
    ("POST", r"^/api/categories$"),
    ("PUT", r"^/api/categories/[^/]+$"),
    ("DELETE", r"^/api/categories/[^/]+$"),
    ("GET", r"^/api/members$"),
    ("GET", r"^/api/users$"),
    ("POST", r"^/api/users$"),
    # 第四十四轮：批量管理。**白名单是按「方法 + 精确路径」列的**，
    # 所以新端点必须显式加进来，否则运营角色一调就是 403。
    # 刻意不写成 `^/api/users/[^/]+$` 的 POST：那会顺带放行 `POST /api/users/{id}`
    # 这种并不存在的路径，白名单宁可窄一点也不要做成「反正不存在」的放行。
    ("POST", r"^/api/users/batch$"),
    ("PUT", r"^/api/users/[^/]+$"),
    ("DELETE", r"^/api/users/[^/]+$"),
    # 第十八轮：GET /api/batches 移出本表 —— 普通成员需要知道「有没有班费要交 / 我交了吗」。
    # 服务层按角色裁剪：非运营角色只拿到批次基本信息 + **自己**的缴费状态，
    # 缴费名单（/payments）与 /members 里是别人的姓名/学号/手机号，仍然留在表内。
    ("POST", r"^/api/batches$"),
    ("GET", r"^/api/batches/[^/]+/payments$"),
    ("POST", r"^/api/batches/[^/]+/pay$"),
    ("POST", r"^/api/batches/[^/]+/close$"),
    ("DELETE", r"^/api/batches/[^/]+$"),
    ("PUT", r"^/api/class$"),
]

_STAFF_COMPILED = [(m, re.compile(p)) for m, p in _STAFF_ROUTES]


# ==================== 纯院长（第三十轮） ====================
#
# 院长有两种：
#   ① **兼班主任**：本班的账目、任务、成员、班级信息他都管（第二十八轮以来的行为）
#   ② **纯院长**：只管**学院**这一层，班级事务一概不参与
#
# 纯院长的能力 = 学院学生名册 + 班主任名册 + 学院任务 + 学生情况总览 + 自己的个人信息。
# 班级那一套（记账、缴费、批次、类别、班级任务、班级信息、班级学生信息、班级账号）
# 归班主任和班委。
#
# ## 为什么用**白名单**而不是黑名单
#
# 白名单的默认方向是「关」：将来加了新接口而忘了把它加进白名单，纯院长就访问不到
# （症状是「页面没数据」，可发现、可补）。反过来若用黑名单，漏一个就是**静默放行**
# （不可发现）。权限边界宁可严一档。

#: 纯院长**可以**访问的接口（方法 + 路径正则）。
#:
#: - `/api/auth/**`：登录、/me、改自己的密码与资料——那是他自己的账号
#: - `/api/college/**`：学院这一层**全部**接口（学生名册 / 班主任名册 / 学院任务）。
#:   名册不只是看：改一格、转班、导入、删行、安排班主任都是院长的本职——
#:   只给 GET 的话他点开「学院学生信息」一个格子都改不了，那就是个只读海报。
#:   这个前缀下没有账目/缴费/班级任务，所以放宽到写不越界。
#:   班级那一套（记账、缴费、批次、类别、班级任务、班级信息、班级学生信息）
#:   仍然不在白名单里。
#: - `GET /api/class/choices`：**全校启用班的名单**（只有 id / 班名 / 年级）。
#:   「个人信息」页要用它渲染「我带的班」——纯院长把这个开关一拨到
#:   「院长 + 班主任」就立刻需要选项，而那时 `dean_only` 还是 1（改完才落库），
#:   拦掉的话用户会先吃一个 403 才看到下拉框。给的是班名，不是班级事务：
#:   账目、缴费、班级任务、班级成员一个都不在里面。
#: - `/api/dashboard/students`：学生情况总览（学院级看板）
#: - `/api/tasks/overview`：任务总览（第三十二轮）——统计的是**全校**的任务，
#:   属学院事务，不含任何班级账目，所以纯院长能看。
#:
#: 刻意**不包含** `/api/dashboard/summary|trend|category-pie`：那是班级账目总览的
#: 数据源。纯院长没有班级账目可言——侧栏里也不给他「账目」这一组。
_PURE_DEAN_ALLOWED: list[tuple[str, str]] = [
    ("GET", r"^/api/auth/"),
    ("POST", r"^/api/auth/"),
    ("PUT", r"^/api/auth/"),
    ("GET", r"^/api/college/"),
    ("POST", r"^/api/college/"),
    ("PUT", r"^/api/college/"),
    ("DELETE", r"^/api/college/"),
    ("GET", r"^/api/class/choices$"),
    ("GET", r"^/api/dashboard/students$"),
    # 第三十三轮：任务接口。**学院任务（scope=COLLEGE）是院长的本职**，
    # 发布/查看/管理它必须放行；但 service 层会把纯院长**限制在学院任务内**
    # （不能发/看/管班级任务）。兼班主任院长（dean_only=0）不受此限制。
    ("GET", r"^/api/tasks"),
    ("POST", r"^/api/tasks"),
    ("PUT", r"^/api/tasks"),
    ("DELETE", r"^/api/tasks"),
]

_PURE_DEAN_COMPILED = [(m, re.compile(p)) for m, p in _PURE_DEAN_ALLOWED]


def pure_dean_allowed(method: str, path: str) -> bool:
    """纯院长能不能碰这个接口。"""
    return any(m == method and p.match(path) for m, p in _PURE_DEAN_COMPILED)


def _account_active(user_id: int) -> tuple[bool, bool]:
    """(账号是否仍可登录, 是否纯院长)。

    JWT 是无状态的，只带 id/role/username/class_id，不含 status，也不含 token 版本号，
    所以「停用账号」「删账号」都无法让已签发的令牌立刻失效。这里在鉴权中间件里
    按主键查一次 `sys_user`，把这两件事变成即时生效。

    第三十轮再顺路把 `dean_only` 带出来：把一个院长从「兼班主任」改成
    「纯院长」后应当**立刻生效**，同样不能等令牌过期。

    代价是每个 /api 请求多一次主键查询（走聚簇索引，量级微秒级）；换来的是
    「停用」这个管理动作真的有意义。查库失败时**放行**（fail-open）：
    数据库抖动不该把所有在线用户一起踢下线，那是可用性事故而不是安全事件。
    """
    from sqlalchemy import text

    from .db import engine

    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT status, dean_only FROM sys_user WHERE id = :i"),
                {"i": user_id},
            ).first()
    except Exception:  # noqa: BLE001
        return True, False
    if row is None:
        return False, False
    return row[0] == 1, bool(row[1])


async def _account_active_async(user_id: int) -> tuple[bool, bool]:
    """`_account_active` 的线程池包装。

    鉴权中间件是 **async** 的，直接在里面跑同步的 pymysql 查询会阻塞整个事件循环
    （一个慢查询会卡住所有并发请求）。丢给 anyio 的线程池执行，与其它同步
    endpoint 走的是同一套机制。
    """
    return await _anyio_thread(_account_active, user_id)


async def _anyio_thread(fn, *args):
    """在线程池里跑一个同步函数（中间件里查库不能阻塞事件循环）。"""
    import anyio.to_thread

    return await anyio.to_thread.run_sync(fn, *args)


def managed_class_ids(user_id: int, default_class_id: int, role: str) -> list[int]:
    """这个账号**能管的班**（第三十二轮）。

    - **其他人 = 默认班 ∪ `sys_user_class` 里关联的班**。
    - **院长 = 他自己勾的「我带的班」**；一条都没勾过才退回「所有启用班」。

    ## 为什么院长不再「恒等于全校」（第三十三轮）

    「个人信息 → 我带的班」对院长原来是**摆设**：不管勾成什么样，
    回执和侧栏切换器永远是全部启用班。用户的说法是「感觉有点串数据，
    没有根据我带的班来分类」。

    现在**学院层照旧全校**（那是 `/api/college/*` 自己的口径，不走过里），
    这里只管**班级层**（账目/任务/学生信息/成员缴费/班级信息）能切到哪些班。

    **一条关联都没有 = 从没设过**：老账号、回归探针都走这条，
    行为与以前一致（全部启用班），不会升级即失效。

    ⚠ **默认班永远在里面**：关联表只存「额外带的班」，摘不掉默认班。
    """
    from sqlalchemy import text

    from .db import engine

    try:
        with engine.connect() as conn:
            picked: list[int] = []
            for (cid,) in conn.execute(
                text("SELECT class_id FROM sys_user_class WHERE user_id = :i"),
                {"i": user_id},
            ):
                c = int(cid)
                if c not in picked:
                    picked.append(c)
            alive = {
                int(cid)
                for (cid,) in conn.execute(
                    text("SELECT id FROM cls_class WHERE status = 1")
                )
            }
    except Exception:  # noqa: BLE001
        # 查不到就按「只管默认班」处理：宁可少一个班，也不能让他多看一个班的账
        return [default_class_id]

    if role == DEAN_ROLE:
        if not picked:
            return sorted(alive) or [default_class_id]
        out = [default_class_id]
        for c in picked:
            if c in alive and c not in out:
                out.append(c)
        return out

    ids: list[int] = [default_class_id]
    for c in picked:
        if c not in ids:
            ids.append(c)
    return ids


def resolve_current_class(
    user: LoginUser, raw: str | None, managed: list[int]
) -> int:
    """本次请求的「当前班」。

    - 没带 `classId` → 默认班（`user.class_id`）
    - 带了且在「他能管的班」里 → 那个班
    - 带了但**不在** → 拒绝（403）。这是权限边界，不能悄悄回落到默认班：
      那会让「手输别人的 classId」看起来像生效了，其实数据还是自己班的。
    """
    if raw is None or str(raw).strip() == "":
        return user.class_id
    try:
        cid = int(raw)
    except (TypeError, ValueError):
        raise BizException.bad_request("班级参数不对")
    if cid not in managed:
        raise BizException.forbidden("你不管理这个班")
    return cid


def require_ownership(actor_id: int, created_by: int | None, *, what: str) -> None:
    """归属权护栏（第十七轮 · A 方案）：**只能改/删自己创建的内容**。

    背景：三张业务表都记了 `created_by`，但改/删路径一直只校验「是不是同一个班」，
    于是出现「删不掉班主任的账号，却能删掉班主任记的流水」这种自相矛盾 ——
    第十五轮加的等级只管住了账号管理，账目这条路是敞开的。

    A 方案的口径最直白：**谁创建谁负责**。同班、同为运营角色，但不是你建的，
    你就不能改、不能删。

    已知代价（用户已知情选择）：如果 A 让 B 代记一笔，之后**只有 B 能改它**，
    包括班主任在内都改不了。这是为了责任可追溯而接受的取舍；
    报错的文案会带上创建人姓名，方便找到人协作处理，而不是让操作者对着
    「权限不足」发呆。
    """
    if created_by is not None and actor_id == created_by:
        return
    from .errors import BizException

    who = f"（创建人 id={created_by}）" if created_by is not None else "（无创建人记录）"
    raise BizException.forbidden(
        f"只能处理自己创建的{what}；这条是他人创建的{who}，请联系创建人协作处理"
    )


def require_roles(*roles: str):
    """端点依赖：从 request.state 取登录用户并校验角色。"""
    async def _dep(request: Request) -> LoginUser:
        user: LoginUser | None = getattr(request.state, "user", None)
        if user is None:
            raise BizException.unauthorized("未登录或登录已过期")
        if user.role not in roles:
            raise BizException.forbidden("当前角色无权执行该操作")
        return user

    return _dep


async def get_current_user(request: Request) -> LoginUser:
    user: LoginUser | None = getattr(request.state, "user", None)
    if user is None:
        raise BizException.unauthorized("未登录或登录已过期")
    return user


#: 拒绝路径上最多替客户端读掉多少字节的请求体。
#: 中间件是**不登录也能打到**的入口，无上限地等一个谎报 `Content-Length`
#: 的客户端会把任务挂死——超过这个数就不读了（那种请求本来也是被拒的）。
_MAX_DRAIN_BYTES = 1024 * 1024
#: 同上，读多久还没读完就放弃（秒）。
_DRAIN_TIMEOUT = 2.0


async def _discard_body(request: Request) -> None:
    """在**拒绝**请求之前，把客户端发来的请求体读掉（丢弃）。

    ## 不读就会 RST

    鉴权中间件跑在路由和请求体解析**之前**。直接 `return fail(401, …)` 时，
    客户端发来的 body 还躺在内核接收缓冲区里没人读；服务端随后关闭连接，
    而 TCP 规定「接收缓冲区里还有未读数据就回 RST」——客户端于是
    **读不到那条 401 响应**，只看到 `ConnectionResetError`。

    实测带 body 的匿名 PUT 有六成以上概率整条响应丢失。前端的表现是
    token 过期后不提示「登录已过期」，而是甩一个网络错误出来。

    ## 只在拒绝路径上调

    放行路径**不能**读：`call_next` 返回时下游的流式处理（上传）可能还在读
    body，这时候去读会把它要的字节抢走。所以只在「不往下走、直接出响应」
    的分支里读。

    ## 有上限

    没有 `Content-Length` 也没有 `Transfer-Encoding` 就是没有 body（GET/HEAD），
    直接返回——否则每个被拒的 GET 都要等一次超时。
    """
    raw = request.headers.get("content-length")
    if raw is not None:
        try:
            if int(raw) > _MAX_DRAIN_BYTES:
                return
        except ValueError:
            return  # 说不清有多大，不赌
    elif not request.headers.get("transfer-encoding"):
        return  # 没有 body，没什么可读的
    try:
        import anyio

        with anyio.fail_after(_DRAIN_TIMEOUT):
            async for _ in request.stream():
                pass
    except Exception:  # noqa: BLE001  读不完就算了，不影响拒绝本身
        return


def install_auth_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def _auth(request: Request, call_next):
        async def reject(status: int, code: int, message: str):
            """出拒绝响应前先读掉 body（见 `_discard_body`）。"""
            await _discard_body(request)
            return fail(code, message, None, status=status)

        path = request.url.path
        if path == "/api" or path.startswith("/api/"):
            if (request.method, path) not in PUBLIC_ROUTES:
                header = request.headers.get("Authorization")
                if header is None or not header.startswith(BEARER_PREFIX):
                    return await reject(401, 401, "未登录或登录已过期")
                try:
                    user = parse_token(header[len(BEARER_PREFIX):])
                except BizException as e:
                    # 中间件内异常不经过全局处理器，直接出响应体
                    return await reject(e.status, e.code, e.message)
                # 第十六轮：JWT 里没有 status，账号被停用后旧令牌本来还能继续用满 2 小时——
                # 「停用」形同虚设（实测停用后所有接口仍 200，甚至能改个人信息）。
                # 这里补一次主键查询（线程池执行，不阻塞事件循环），停用/删除即刻生效。
                active, dean_only = await _account_active_async(user.id)
                if not active:
                    return await reject(403, 403, "账号已被停用，请联系班主任")
                # 把「是否纯院长」贴到本次请求的用户对象上。
                # 它不进 JWT（JWT 签发后就固定了，而这个标志要能即时生效），
                # 所以每次请求都按主键查一次——和 status 同一条路子。
                user.dean_only = dean_only
                # 第三十二轮：**当前班**。
                #
                # 一个班主任可能管好几个班（云计算2502 + 云计算2501）。
                # 请求里带 `classId` 就切到那个班——只允许切到**他能管的班**。
                #
                # ⚠ 这一步把 `user.class_id` 改成「本次请求操作的班」，
                # 后面所有 service 用的都是它——所以那 80 多处 `user.class_id`
                # 一行都不用改，语义自动跟着当前班走。
                managed = await _anyio_thread(
                    managed_class_ids, user.id, user.class_id, user.role
                )
                # ⚠ **学院口径的接口不吃 `classId` 这层语义**：那几页的
                # `classId` 是页面上的「全部班级」筛选条件，不是「本次操作哪个班」。
                # 混在一起会出怪事：把学院名册筛到某个不在「我带的班」里的班，
                # 整个请求 403（筛一下就被拒，看起来像权限坏了）。
                # 前端 `api/request.ts` 对同一批路径也不注入 classId，两边口径一致。
                college_scope = path.startswith("/api/college/") or path.startswith(
                    "/api/dashboard/students"
                )
                if not college_scope:
                    try:
                        user.class_id = resolve_current_class(
                            user, request.query_params.get("classId"), managed
                        )
                    except BizException as e:
                        return await reject(e.status, e.code, e.message)
                # 纯院长（第三十轮）：只管学院，班级事务一概不参与。
                # 后端硬拦——前端隐藏的只是**入口**，手输 URL 或直接调接口都能绕过去。
                if user.role == DEAN_ROLE and dean_only:
                    if not pure_dean_allowed(request.method, path):
                        return await reject(
                            403,
                            403,
                            "纯院长只负责学院事务；班级事务请由班主任（或班委）处理",
                        )
                request.state.user = user
                for method, pattern in _STAFF_COMPILED:
                    if request.method == method and pattern.match(path):
                        if user.role not in STAFF_ROLES:
                            return await reject(403, 403, "当前角色无权执行该操作")
                        break
        return await call_next(request)
