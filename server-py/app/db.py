"""SQLAlchemy 引擎与会话（sync + pymysql）。"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

_cfg = settings()

engine = create_engine(
    _cfg["database_url"],
    connect_args={
        "user": _cfg["db_username"],
        "password": _cfg["db_password"],
        "charset": "utf8mb4",
        # 墙钟 datetime（对齐 Java 侧 serverTimezone=Asia/Shanghai 的朴素值）
        "local_infile": False,
    },
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=10,
    pool_recycle=3600,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ping_db(retries: int = 30, interval: float = 2.0) -> None:
    """启动期连接重试（适配 compose 里 mariadb 慢启动）。"""
    import time

    last: Exception | None = None
    for i in range(retries):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(interval)
    raise RuntimeError(f"数据库连接失败: {last}")
