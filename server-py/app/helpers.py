"""跨服务共用的 SQL 辅助：与 Java 各 Service 中的私有工具逐一对应。"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from .errors import BizException


def escape_like(raw: str) -> str:
    """LIKE 通配符转义（对应 Java escapeLike：反斜杠为转义符）。"""
    return raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def like_pattern(raw: str) -> str:
    return f"%{escape_like(raw)}%"


def parse_boundary(text_value: str | None, is_end: bool) -> datetime | None:
    """yyyy-MM-dd → 次日/当日零点（左闭右开）；空→None；非法→400 日期格式应为 yyyy-MM-dd。

    严格两位补零，与 Java LocalDate.parse(ISO) 一致（2026-9-1 两侧都拒绝）。
    """
    if text_value is None or not text_value.strip():
        return None
    t = text_value.strip()
    try:
        if len(t) != 10 or t[4] != "-" or t[7] != "-":
            raise ValueError(t)
        d = datetime.strptime(t, "%Y-%m-%d")
    except ValueError:
        raise BizException.bad_request("日期格式应为 yyyy-MM-dd") from None
    if is_end:
        d = d + timedelta(days=1)
    return datetime(d.year, d.month, d.day)


def add_balance(db: Session, class_id: int, delta: Decimal) -> None:
    """cls_class.balance 原子增减；行数 != 1 即失败（对齐 ClsClassMapper.addBalance）。"""
    result = db.execute(
        text("UPDATE cls_class SET balance = balance + :delta WHERE id = :id"),
        {"delta": delta, "id": class_id},
    )
    if result.rowcount != 1:
        raise BizException.bad_request("班级余额更新失败，请重试")


def lock_class(db: Session, class_id: int) -> None:
    """行锁班级行（批次创建前串行化，对应 selectOne ... for update）。"""
    db.execute(
        text("SELECT id FROM cls_class WHERE id = :id FOR UPDATE"),
        {"id": class_id},
    )
