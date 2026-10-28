"""应用配置：读 docker-compose 的 CLASSFEE_* / SPRING_DATASOURCE_* 环境变量。"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

DEFAULT_JWT_SECRET = "classfee-m1-dev-secret-please-change-me-0123456789"
# 默认连接串用 **SQLAlchemy 原生写法**（驱动://主机:端口/库名?参数）。
# 注意字符集写 charset（PyMySQL 认这个），时区不在 URL 里配 —— 那是 JDBC 驱动的参数，
# PyMySQL 没有；应用时区由容器的 TZ=Asia/Shanghai 环境变量保证。
DEFAULT_DB_URL = "mysql+pymysql://localhost:3306/classfee?charset=utf8mb4"


#: 布尔型环境变量的「真」值写法。`.env` 里人们爱写 1/true/yes/on，
#: 也有人写「是」——都认。但空串和乱七八糟的值一律当**假**，
#: 宁可按默认走也不要因为一个错别字把权限模式切了。
_TRUTHY = {"1", "true", "yes", "on"}


def _truthy(raw: str) -> bool:
    return raw.strip().lower() in _TRUTHY


def _normalize_db_url(url: str) -> str:
    """统一成 SQLAlchemy 原生连接串。

    首选写法（本项目现在用的）：``mysql+pymysql://host:3306/db?charset=utf8mb4``
    —— 原样使用，参数由自己掌控。

    同时**保留对 JDBC 连接串的兼容**（老 .env / 老部署文档里还写着这种）：
    ``jdbc:mariadb://host:3306/db?x=y`` → ``mysql+pymysql://host:3306/db?charset=utf8mb4``
    —— 注意 JDBC 串后面那些 `useUnicode` / `serverTimezone` 是**驱动专有参数，
    PyMySQL 不认**，所以直接丢弃并统一用 charset（实测两种写法连同一库结果一致）。
    """
    url = url.strip()
    if url.startswith("jdbc:mariadb://") or url.startswith("jdbc:mysql://"):
        rest = url.split("://", 1)[1]
        host_and_db, _, _query = rest.partition("?")
        return f"mysql+pymysql://{host_and_db}?charset=utf8mb4"
    if url.startswith("mariadb+pymysql://"):
        return url.replace("mariadb+pymysql://", "mysql+pymysql://", 1)
    return url


@lru_cache(maxsize=1)
def settings() -> dict:
    # 数据库连接：优先 CLASSFEE_DB_*（本项目命名），仍兼容 SPRING_DATASOURCE_*（旧版沿用名）
    raw_url = os.environ.get("CLASSFEE_DB_URL") or os.environ.get(
        "SPRING_DATASOURCE_URL", DEFAULT_DB_URL
    )
    return {
        "database_url": _normalize_db_url(raw_url),
        "db_username": os.environ.get("CLASSFEE_DB_USERNAME")
        or os.environ.get("SPRING_DATASOURCE_USERNAME", "classfee"),
        "db_password": os.environ.get("CLASSFEE_DB_PASSWORD")
        or os.environ.get("SPRING_DATASOURCE_PASSWORD", "classfee123"),
        # JWT 签名密钥：Python 后端在 config.py 读取 → security.py 签发/校验登录令牌
        "jwt_secret": os.environ.get("CLASSFEE_JWT_SECRET", DEFAULT_JWT_SECRET),
        "jwt_expire_hours": int(os.environ.get("CLASSFEE_JWT_EXPIRE_HOURS", "2")),
        # 班主任（运营）账号：在 compose 的 .env / 系统环境变量里「声明即生效」，
        # 启动时仅在库中不存在时创建。默认为空 = 代码里不写死任何默认口令；
        # 用户名与密码必须同时填写，否则不创建（启动日志会提示）。
        "teacher_username": os.environ.get("CLASSFEE_TEACHER_USERNAME", "").strip(),
        "teacher_password": os.environ.get("CLASSFEE_TEACHER_PASSWORD", ""),
        "teacher_name": os.environ.get("CLASSFEE_TEACHER_NAME", "").strip(),
        "teacher_role": (
            os.environ.get("CLASSFEE_TEACHER_ROLE", "TEACHER").strip().upper() or "TEACHER"
        ),
        # 第三十轮：**这个账号是不是纯院长**。
        #
        # 院长有两种：① 兼班主任（本班的账目/任务/成员他都管）；
        # ② 只是院长（纯院级管理员，只管学院那一层，班级事务一概不参与）。
        # 部署时在这里声明——安装服务的人最清楚这个账号要干什么。
        #
        # 只在 `CLASSFEE_TEACHER_ROLE=DEAN` 时才有意义（别的角色忽略它）。
        # 取值：1/true/yes/on = 纯院长；0/false/no/off/空 = 兼班主任（默认）。
        #
        # ⚠ 默认 0 = 与第二十八轮的行为**完全一致**，存量部署升级后不受影响。
        "dean_only": _truthy(
            os.environ.get("CLASSFEE_DEAN_ONLY", "").strip().lower()
        ),
        # 学院名称（第三十二轮）。
        #
        # 显示在侧栏顶部：**院长的权限范围是「学院」而不是某个班**，
        # 所以顶头那行不能只写班级名。兼班主任的院长显示
        # 「学院名 班级名」（例如「智能汽车学院 云计算2502」），
        # 纯院长只显示「学院名」。
        #
        # 留空 = 界面上退回写「学院」两个字。
        "college_name": os.environ.get("CLASSFEE_COLLEGE_NAME", "").strip(),
        # 空库建班信息：旧 CLASSFEE_INIT_CLASS_* 仍兼容（第九轮改名，新名优先）
        "class_name": os.environ.get("CLASSFEE_CLASS_NAME")
        or os.environ.get("CLASSFEE_INIT_CLASS_NAME", "计科2201班"),
        "grade": os.environ.get("CLASSFEE_CLASS_GRADE")
        or os.environ.get("CLASSFEE_INIT_GRADE", "2022级"),
        "head_teacher": os.environ.get("CLASSFEE_CLASS_HEAD_TEACHER")
        or os.environ.get("CLASSFEE_INIT_HEAD_TEACHER")
        # 没配就跟着班主任账号的姓名走；都没有就留空（不写「测试班主任」这种假数据）
        or os.environ.get("CLASSFEE_TEACHER_NAME", "").strip(),
        # 小票图片存储根目录（compose 里挂 named volume 保证重建容器不丢图）
        "upload_dir": os.environ.get(
            "CLASSFEE_UPLOAD_DIR", str(Path(__file__).resolve().parents[1] / "uploads")
        ),
    }
