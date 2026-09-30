"""应用配置：读 docker-compose 的 CLASSFEE_* / SPRING_DATASOURCE_* 环境变量。"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

DEFAULT_JWT_SECRET = "classfee-m1-dev-secret-please-change-me-0123456789"
# 默认连接串用 **SQLAlchemy 原生写法**（驱动://主机:端口/库名?参数）。
# 注意字符集写 charset（PyMySQL 认这个），时区不在 URL 里配 —— 那是 Java 驱动的参数，
# PyMySQL 没有；应用时区由容器的 TZ=Asia/Shanghai 环境变量保证。
DEFAULT_DB_URL = "mysql+pymysql://localhost:3306/classfee?charset=utf8mb4"


def _normalize_db_url(url: str) -> str:
    """统一成 SQLAlchemy 原生连接串。

    首选写法（本项目现在用的）：``mysql+pymysql://host:3306/db?charset=utf8mb4``
    —— 原样使用，参数由自己掌控。

    同时**保留对 Java 版 JDBC 串的兼容**（老 .env / 老部署文档里还写着这种）：
    ``jdbc:mariadb://host:3306/db?x=y`` → ``mysql+pymysql://host:3306/db?charset=utf8mb4``
    —— 注意 JDBC 后面那些 `useUnicode` / `serverTimezone` 是 **Java 驱动专有参数，
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
    # 数据库连接：优先 CLASSFEE_DB_*（本项目命名），仍兼容 SPRING_DATASOURCE_*（旧 Java/Spring 版沿用名）
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
        # 空库建班信息：旧 CLASSFEE_INIT_CLASS_* 仍兼容（第九轮改名，新名优先）
        "class_name": os.environ.get("CLASSFEE_CLASS_NAME")
        or os.environ.get("CLASSFEE_INIT_CLASS_NAME", "计科2201班"),
        "grade": os.environ.get("CLASSFEE_CLASS_GRADE")
        or os.environ.get("CLASSFEE_INIT_GRADE", "2022级"),
        "head_teacher": os.environ.get("CLASSFEE_CLASS_HEAD_TEACHER")
        or os.environ.get("CLASSFEE_INIT_HEAD_TEACHER", "测试班主任"),
        # 小票图片存储根目录（compose 里挂 named volume 保证重建容器不丢图）
        "upload_dir": os.environ.get(
            "CLASSFEE_UPLOAD_DIR", str(Path(__file__).resolve().parents[1] / "uploads")
        ),
    }
