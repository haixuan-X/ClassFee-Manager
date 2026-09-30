"""JWT 签发/解析、BCrypt 密码、认证鉴权中间件（对应 Java JwtUtil + AuthInterceptor）。

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
    role: str  # MEMBER(普通成员) / ADMIN(生活委员) / MONITOR(班长) / TEACHER(班主任)
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
        # 密文格式非法（非 BCrypt）：Java encoder.matches 抛异常 → 这里等价视为不匹配
        return False


# ---------------- JWT（HS256，claims 与 Java JwtUtil 相同） ----------------

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

PUBLIC_ROUTES = {("POST", "/api/auth/login")}

# 运营角色：ADMIN（生活委员）/ MONITOR（班长）/ TEACHER（班主任）三者**记账权限**同权
# （第七轮起 TEACHER=全权运营：财务 + 成员管理；第十四轮新增 MONITOR 承载「班长」称谓）
STAFF_ROLES = frozenset({"ADMIN", "MONITOR", "TEACHER"})

# ---------------- 账号管理权限等级（第十五轮） ----------------
# 记账权限同权 ≠ 管理权限同权。**班主任 > 班长 > 生活委员 > 普通成员**：
# 低等级角色不能改动/停用/删除高等级角色的账号，否则班长能把班主任踢下线。
# 数字越大权限越高；MEMBER=0（只读，不参与账号管理）。
ROLE_LEVEL: dict[str, int] = {
    "MEMBER": 0,
    "ADMIN": 1,    # 生活委员
    "MONITOR": 2,  # 班长
    "TEACHER": 3,  # 班主任
}


def role_level(role: str | None) -> int:
    """角色等级；未知角色按 0（最弱）处理，缺省安全。"""
    return ROLE_LEVEL.get(role or "", 0)


def require_role_higher(actor_role: str, target_role: str) -> None:
    """账号管理护栏：操作者的等级必须**严格高于**目标账号。

    覆盖「编辑资料 / 重置密码 / 停用 / 删除」四类账号管理动作：

    - 低级不能动高级（班长/生活委员动不了班主任）
    - 同级不能互动（避免两个班长相向踢下线）
    - 「自己不动自己」不在这里判：停用/删除自己由各接口给出更贴切的提示语
    """
    from .errors import BizException

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
    ("POST", r"^/api/notices$"),
    ("PUT", r"^/api/notices/[^/]+$"),
    ("DELETE", r"^/api/notices/[^/]+$"),
    ("PUT", r"^/api/class$"),
]

_STAFF_COMPILED = [(m, re.compile(p)) for m, p in _STAFF_ROUTES]


def _account_active(user_id: int) -> bool:
    """账号是否仍可登录（status=1 且行还在）。

    JWT 是无状态的，只带 id/role/username/class_id，不含 status，也不含 token 版本号，
    所以「停用账号」「删账号」都无法让已签发的令牌立刻失效。这里在鉴权中间件里
    按主键查一次 `sys_user`，把这两件事变成即时生效。

    代价是每个 /api 请求多一次主键查询（走聚簇索引，量级微秒级）；换来的是
    「停用」这个管理动作真的有意义。查库失败时**放行**（fail-open）：
    数据库抖动不应该把所有在线用户一起踢下线，那是可用性事故而不是安全事件。
    """
    from sqlalchemy import text

    from .db import engine

    try:
        with engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM sys_user WHERE id = :i"), {"i": user_id}
            ).scalar()
    except Exception:  # noqa: BLE001
        return True
    return status == 1


async def _account_active_async(user_id: int) -> bool:
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
    """端点依赖：从 request.state 取登录用户并校验角色（403 文案同 Java）。"""
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
                if not await _account_active_async(user.id):
                    return fail(403, "账号已被停用，请联系班主任", None, status=403)
                request.state.user = user
                for method, pattern in _STAFF_COMPILED:
                    if request.method == method and pattern.match(path):
                        if user.role not in STAFF_ROLES:
                            return fail(403, "当前角色无权执行该操作", None, status=403)
                        break
        return await call_next(request)
