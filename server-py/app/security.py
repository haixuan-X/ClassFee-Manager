"""JWT 签发/解析、BCrypt 密码、认证鉴权中间件。

顺序与 Spring 拦截器一致：先解析令牌（401）→ 再校验角色（403）→ 之后才轮到参数/请求体校验。
"""
from __future__ import annotations

import json
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
    role: str  # MEMBER(普通成员) / GUEST(访客·只读) / ADMIN(生活委员) / MONITOR(班长) / TEACHER(班主任) / DEAN(院长·系统管理员)
    class_id: int


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
# GUEST（访客，第二十四轮）：给领导/校方看的**纯只读**账号。
# 等级取 0，与 MEMBER 同级——两者都不参与账号管理（改别人账号的接口
# 本身就要求 STAFF_ROLES）。它比 MEMBER 多的只是「能看全班学生信息、能勾选导出」。
#
# DEAN（院长，第二十八轮）：**系统管理员**，等级压在班主任之上（4 > 3）。
# 「默认院长是管理员」这句落在这里——院长是等级最高的那一档，能管理所有低档角色，
# 包括班主任自己。等级差一档就够表达「系统管理员」了，不需要另起一套并行体系。
ROLE_LEVEL: dict[str, int] = {
    "MEMBER": 0,
    "GUEST": 0,    # 访客（只读；等级同普通成员，都管不了账号）
    "ADMIN": 1,    # 生活委员
    "MONITOR": 2,  # 班长
    "TEACHER": 3,  # 班主任
    "DEAN": 4,     # 院长（系统管理员，等级最高）
}

#: 够格管理访客账号的最低等级。等于「班主任及以上」——院长(4)自然包含在内。
#:
#: ⚠ 这里**必须**跟着 `ROLE_LEVEL` 走，不能写成 `actor_role != "TEACHER"`：
#: 那样会出现「等级更高的院长管不了访客、等级更低的班主任却能管」的倒挂。
#: 角色是身份、等级才是权限——判定一律看等级。
GUEST_MANAGER_MIN_LEVEL = ROLE_LEVEL["TEACHER"]


# =====================================================================
# 第二十六轮：访客的「可见范围」由班主任逐个指定
# =====================================================================
# 以前访客是写死的全能看（前端 `GUEST_VISIBLE` 一个常量）。现在每个访客账号
# 自己带一份范围（`sys_user.guest_scopes`），老师在建号/编辑时勾。
#
# **为什么必须后端拦、不能只藏侧栏**：前端隐藏的是「入口」，不是「数据」。
# 只要访客手输 URL 或者直接调接口，前端那套白名单就形同虚设。
# 第二十四轮就有过教训——访客侧栏漏了「班级公告」这类问题只靠人眼发现。
#
# 这里只映射**表外拦不住**的那些路径；绝大多数接口要么被 `_STAFF_ROUTES` 拦掉，
# 要么对所有登录角色开放，再判一遍只会让两套规则漂移。写进 `required_guest_scope`
# 之前先确认一遍：这条路径真的没被别处拦住吗？

#: 范围项 = 访客能进的四类页面。顺序即界面上多选框的顺序。
GUEST_SCOPE_KEYS: tuple[str, ...] = ("DASHBOARD", "RECORDS", "STUDENTS", "TASKS")

#: 访客角色名。刻意提成常量：这个字面量现在同时出现在中间件守卫、scope 解析
#: 和 user_service 三处，写错一个字母就会变成「访客绕过范围检查」而没有任何报错。
GUEST_ROLE = "GUEST"

#: `required_guest_scope` 的哨兵值：**访客一律看不到**，不管勾了什么。
#:
#: 用常量而不是空串：``""`` 和 ``None`` 在判据里是两个完全不同的意思
#: （「访客不能碰」vs「这条路径不归范围管」，前者拒绝、后者放行），
#: 写成空串一旦哪个分支写成 `if need:` 就会被静默当成后者放行——方向反了。
NO_GUEST_SCOPE = "\x00none"

#: 给界面用的中文名与说明。`security` 放这里而不是 schemas：这份文案
#: 同时被账号编辑框和权限说明引用，放一处才不会漂。
GUEST_SCOPE_LABELS: dict[str, tuple[str, str]] = {
    "DASHBOARD": ("仪表盘", "班级余额、收支趋势和最新流水"),
    "RECORDS": ("账本明细", "全部记账流水、缴费记录，以及收费批次（金额和截止时间）"),
    "STUDENTS": ("学生信息", "全班学生的登记信息，可勾选导出"),
    "TASKS": ("班级任务", "任务题目和填写情况（只有汇总，不含谁填了什么）"),
}


def parse_guest_scopes(raw: str | None) -> list[str]:
    """把 `sys_user.guest_scopes` 解析成范围列表。

    - `None`（库里的 NULL）= 全部可见。**只给老账号**：第二十四轮那批访客建号时
      根本没有这个概念，行为就是全能看，用 NULL 让它们零迁移保持原样。
    - `'[]'` = 真的什么都看不到（老师一项都没勾）。
    - `'["STUDENTS"]'` = 只看学生信息。

    ⚠ 这三种必须各自表达各自的含义，不能互相塌缩。曾经把「空数组」也当成「全开」
    （`[] or 全开`），于是勾选框里显示「什么都没勾」，实际权限却是「全都有」——
    老师想给一个「什么都看不到」的访客，界面上根本表达不出来，而界面在撒谎。
    空就是空。
    """
    if raw is None:
        return list(GUEST_SCOPE_KEYS)
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        # 库里的值坏了：宁可放宽成全开，也不要让一个访客莫名什么都看不到
        return list(GUEST_SCOPE_KEYS)
    if not isinstance(items, list):
        return list(GUEST_SCOPE_KEYS)
    return [s for s in GUEST_SCOPE_KEYS if s in items]


def dump_guest_scopes(scopes: list[str] | None) -> str | None:
    """入参 -> 落库值。

    ⚠ `None`（没传这个字段）和 `[]`（传了空数组）**必须分开**，它们是两件事：

    - `None` = 老师没表态 = 全部可见 -> NULL（建号表单的老行为、老账号的表示）
    - `[]`  = 老师明确一项都没勾 = 什么都看不到 -> `'[]'`

    写成 `picked = [s for s in KEYS if s in (scopes or [])]` 会把两者塌成同一个，
    结果「不传范围」的访客被存成 `'[]'`——看着什么都没勾，实际什么都看不到。
    这个错很安静：不传范围本来是最常见的用法，只有 `guest_probe` 那类用例会炸。
    """
    if scopes is None:
        return None  # 没表态 = 全开
    picked = [s for s in GUEST_SCOPE_KEYS if s in scopes]
    if len(picked) == len(GUEST_SCOPE_KEYS):
        return None  # 全勾 = 全开，和老账号共用一个表示，少一种要解释的状态
    return json.dumps(picked, ensure_ascii=False)  # 含 [] = 什么都看不到


def guest_can_see(user: LoginUser, scopes: list[str] | None, path: str) -> bool:
    """访客能不能访问这条路径。给中间件和测试共用同一套判据。"""
    if user.role != GUEST_ROLE:
        return True
    need = required_guest_scope(path)
    if need is None:
        return True  # 个人信息、改密这类不归范围管
    if need == NO_GUEST_SCOPE:
        return False  # 明确标记为「访客一律看不到」
    return need in (scopes if scopes is not None else list(GUEST_SCOPE_KEYS))


def _scope_display(scope: str) -> str:
    """403 提示里的中文名。取不到就退回一个能看懂的说法，别只回个 key。"""
    if scope == NO_GUEST_SCOPE:
        return "该页面"
    return GUEST_SCOPE_LABELS.get(scope, (scope, ""))[0]


def required_guest_scope(path: str) -> str | None:
    """这条路径属于哪个可见范围。

    三种返回值，**方向默认朝着「关」**：

    - 范围 key（``"RECORDS"`` 等）——访客勾了这一项才放行
    - `NO_GUEST_SCOPE`——访客一律看不到，勾什么都不行
    - `None`——这条路径不归范围管（`/api/auth/*` 个人信息、改密），
      由各自端点的角色校验负责

    绝大多数接口压根不用写进这张表：要么已被 `_STAFF_ROUTES` 拦掉
    （成员管理、记账写入…），要么对所有登录角色开放（`/api/auth/*`），
    再判一遍只会让两套规则漂移。**写进表里的，都是「表外拦不住」的。**

    ⚠ 后两条是实测补上的，都是「前端藏着、后端放着」的洞：

    - `/api/batches`（收费批次）第二十轮为了回答普通同学的「有没有班费要交 /
      我交了吗」被**移出** `_STAFF_ROUTES`，访客跟着就能读了——里面是金额和
      截止时间，属于账目信息，所以归到 RECORDS 范围一起管。
      （访客侧栏本来就不给这个入口，所以界面上看不出差别，纯粹是接口层的漏。）
    - `/api/class`（班级信息）不属于四个范围中的任何一个。默认方向是「不给」，
      所以返回 `NO_GUEST_SCOPE`：就算四项全勾也读不到。老师想让访客知道班级
      名称的话，`/api/auth/me` 里已经带了 `className`，走 `/api/auth/*` 不经过这里。
    """
    if path.startswith("/api/dashboard"):
        return "DASHBOARD"
    # `/api/records/export` 本来就在 _STAFF_ROUTES 里（访客 403），
    # 这里一并映射成 RECORDS 只是为了让规则读起来是完整的。
    if path == "/api/records" or path.startswith("/api/records/"):
        return "RECORDS"
    if path == "/api/students" or path.startswith("/api/students/"):
        return "STUDENTS"
    if path == "/api/tasks" or path.startswith("/api/tasks/"):
        return "TASKS"
    if path == "/api/batches" or path.startswith("/api/batches/"):
        return "RECORDS"
    if path == "/api/class":
        return NO_GUEST_SCOPE  # 不属于任何范围 = 一律拒绝
    return None


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

    ## 访客（GUEST）例外：班主任及以上才能管

    访客的等级是 0（和普通成员同级，纯只读），但通用规则「等级高可以管等级低」
    会让生活委员(1) **有资格**管访客——可访客代表的是外部人员（校方/领导），
    一个生活委员不该能停用或删除校方的账号。

    这里单独拦一道，而不是在各个接口里各写一遍：这道函数就是四个管理动作的
    **唯一总入口**，规则写在这里才不会漏。（第二十四轮就漏过一次——
    创建时拦了「只有班主任能建访客」，管理那四个动作却全放行。）

    ⚠ 判据是**等级**（`>= GUEST_MANAGER_MIN_LEVEL`）而不是 `== "TEACHER"`：
    写成角色相等判断的话，加了等级更高的院长之后就会出现倒挂——
    班主任能管访客、院长（更高）反而不能。
    """
    from .errors import BizException

    if target_role == GUEST_ROLE and role_level(actor_role) < GUEST_MANAGER_MIN_LEVEL:
        raise BizException.forbidden("访客账号只能由班主任及以上管理")

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


def _account_active(user_id: int) -> tuple[bool, str | None]:
    """(账号是否仍可登录, 访客可见范围原文)。

    JWT 是无状态的，只带 id/role/username/class_id，不含 status，也不含 token 版本号，
    所以「停用账号」「删账号」都无法让已签发的令牌立刻失效。这里在鉴权中间件里
    按主键查一次 `sys_user`，把这两件事变成即时生效。

    第二十六轮顺路把 `guest_scopes` 一起读出来：老师改完访客的范围之后
    **不用等对方重新登录**就生效——这正是「创建时选、编辑时也能改」的前提。
    塞进 JWT 做不到这一点（令牌一签发就固定，除非再引入 token 版本号，
    那会让「改密码」也连带把别处踢下线，代价反而更大）。

    代价是每个 /api 请求多一次主键查询（走聚簇索引，量级微秒级）；换来的是
    「停用」这个管理动作真的有意义。查库失败时**放行**（fail-open）：
    数据库抖动不该把所有在线用户一起踢下线，那是可用性事故而不是安全事件。
    访客范围同理——宁可这一次放行，也不要因为查询失败让访客突然什么都看不到。
    """
    from sqlalchemy import text

    from .db import engine

    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT status, guest_scopes FROM sys_user WHERE id = :i"),
                {"i": user_id},
            ).first()
    except Exception:  # noqa: BLE001
        return True, None
    if row is None:
        return False, None
    return row[0] == 1, row[1]


async def _account_active_async(user_id: int) -> tuple[bool, str | None]:
    """`_account_active` 的线程池包装。

    鉴权中间件是 **async** 的，直接在里面跑同步的 pymysql 查询会阻塞整个事件循环
    （一个慢查询会卡住所有并发请求）。丢给 anyio 的线程池执行，与其它同步
    endpoint 走的是同一套机制。
    """
    import anyio.to_thread

    return await anyio.to_thread.run_sync(_account_active, user_id)


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


def install_auth_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def _auth(request: Request, call_next):
        path = request.url.path
        if path == "/api" or path.startswith("/api/"):
            if (request.method, path) not in PUBLIC_ROUTES:
                header = request.headers.get("Authorization")
                if header is None or not header.startswith(BEARER_PREFIX):
                    return fail(401, "未登录或登录已过期", None, status=401)
                try:
                    user = parse_token(header[len(BEARER_PREFIX):])
                except BizException as e:
                    # 中间件内异常不经过全局处理器，直接出响应体
                    return fail(e.code, e.message, None, status=e.status)
                # 第十六轮：JWT 里没有 status，账号被停用后旧令牌本来还能继续用满 2 小时——
                # 「停用」形同虚设（实测停用后所有接口仍 200，甚至能改个人信息）。
                # 这里补一次主键查询（线程池执行，不阻塞事件循环），停用/删除即刻生效。
                # 第二十六轮：同一次查询把访客的可见范围也带出来（见 `_account_active`），
                # 不额外加查询——老师改完范围访客立刻生效，不用等重新登录。
                active, guest_scopes_raw = await _account_active_async(user.id)
                if not active:
                    return fail(403, "账号已被停用，请联系班主任", None, status=403)
                # 访客范围：后端硬拦。前端隐藏的只是**入口**，手输 URL 或直接调接口
                # 都能绕过去——权限必须在服务端收口。
                if user.role == GUEST_ROLE:
                    need = required_guest_scope(path)
                    if need is not None and need not in parse_guest_scopes(guest_scopes_raw):
                        return fail(
                            403,
                            f"该访客账号未被授权查看{_scope_display(need)}",
                            None,
                            status=403,
                        )
                request.state.user = user
                for method, pattern in _STAFF_COMPILED:
                    if request.method == method and pattern.match(path):
                        if user.role not in STAFF_ROLES:
                            return fail(403, "当前角色无权执行该操作", None, status=403)
                        break
        return await call_next(request)
