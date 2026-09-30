"""仪表盘统计：余额、本月收支、近 N 月趋势、支出分类占比、最新流水（对应 Java DashboardService）。

统一口径：只统计 status='NORMAL' 的流水，作废（红冲）不参与。
SQL 与 ReportMapper 的 @Select 逐字对齐。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..errors import BizException
from ..models import ClsClass, FeeRecord
from ..security import LoginUser
from ..services.batch_service import completion_rate
from ..services.notice_service import pinned_notices
from ..services.record_service import to_vo_list

EPOCH = datetime(1970, 1, 1)
FAR_FUTURE = datetime(2999, 1, 1)

_SUM_RANGE_SQL = text(
    """
    SELECT COALESCE(SUM(CASE WHEN type = 'INCOME'  THEN amount END), 0) AS income,
           COALESCE(SUM(CASE WHEN type = 'EXPENSE' THEN amount END), 0) AS expense,
           COUNT(*) AS cnt
      FROM fee_record
     WHERE class_id = :classId
       AND status = 'NORMAL'
       AND occurred_at >= :start
       AND occurred_at < :end
    """
)

_TREND_SQL = text(
    """
    SELECT DATE_FORMAT(occurred_at, '%Y-%m') AS ym,
           COALESCE(SUM(CASE WHEN type = 'INCOME'  THEN amount END), 0) AS income,
           COALESCE(SUM(CASE WHEN type = 'EXPENSE' THEN amount END), 0) AS expense
      FROM fee_record
     WHERE class_id = :classId
       AND status = 'NORMAL'
       AND occurred_at >= :from
     GROUP BY ym
     ORDER BY ym
    """
)

_PIE_SQL = text(
    """
    SELECT c.name AS name, COALESCE(SUM(f.amount), 0) AS value
      FROM fee_record f
      JOIN fee_category c ON c.id = f.category_id
     WHERE f.class_id = :classId
       AND f.type = 'EXPENSE'
       AND f.status = 'NORMAL'
       AND f.occurred_at >= :from
     GROUP BY c.id, c.name
     ORDER BY value DESC
    """
)


def _sum_range(db: Session, class_id: int, start: datetime, end: datetime) -> tuple:
    row = db.execute(
        _SUM_RANGE_SQL, {"classId": class_id, "start": start, "end": end}
    ).one()
    return row[0], row[1], int(row[2])


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, 1)


def _normalize_months(months: int) -> int:
    if months < 1 or months > 24:
        raise BizException.bad_request("months 需在 1-24 之间")
    return months


def summary(db: Session, user: LoginUser) -> dict:
    class_id = user.class_id

    # 冗余余额（记账时原子更新）
    clazz = db.get(ClsClass, class_id)
    balance = clazz.balance if clazz is not None and clazz.balance is not None else Decimal(0)

    # 本月收支
    today = date.today()
    month_start = _first_of_month(today)
    next_month_start = _add_months(month_start, 1)
    month_income, month_expense, month_count = _sum_range(
        db,
        class_id,
        datetime(month_start.year, month_start.month, month_start.day),
        datetime(next_month_start.year, next_month_start.month, next_month_start.day),
    )

    # 全量流水对账：与冗余余额应当一致
    all_income, all_expense, _ = _sum_range(db, class_id, EPOCH, FAR_FUTURE)
    real_balance = all_income - all_expense

    # 最新 5 笔（含作废，前端按状态标注）
    latest = list(_latest_records(db, class_id))

    return {
        "balance": balance,
        "realBalance": real_balance,
        "monthIncome": month_income,
        "monthExpense": month_expense,
        "monthCount": month_count,
        "completionRate": completion_rate(db, class_id),
        "latestRecords": to_vo_list(db, latest),
        "pinnedNotices": pinned_notices(db, class_id),
    }


def _latest_records(db: Session, class_id: int):
    from sqlalchemy import select

    return db.scalars(
        select(FeeRecord)
        .where(FeeRecord.class_id == class_id)
        .order_by(FeeRecord.occurred_at.desc(), FeeRecord.id.desc())
        .limit(5)
    )

def trend(db: Session, user: LoginUser, months: int) -> list[dict]:
    n = _normalize_months(months)
    from_day = _add_months(_first_of_month(date.today()), -(n - 1))

    rows = db.execute(
        _TREND_SQL,
        {
            "classId": user.class_id,
            "from": datetime(from_day.year, from_day.month, from_day.day),
        },
    ).all()
    by_ym: dict[str, dict] = {}
    for ym, income, expense in rows:
        by_ym.setdefault(ym, {"ym": ym, "income": income, "expense": expense})

    result = []
    for i in range(n):
        ym = _add_months(from_day, i).strftime("%Y-%m")
        point = by_ym.get(ym)
        if point is None:
            point = {"ym": ym, "income": Decimal(0), "expense": Decimal(0)}
        result.append(point)
    return result


def category_pie(db: Session, user: LoginUser, months: int) -> list[dict]:
    from_day = _add_months(
        _first_of_month(date.today()), -(_normalize_months(months) - 1)
    )
    rows = db.execute(
        _PIE_SQL,
        {
            "classId": user.class_id,
            "from": datetime(from_day.year, from_day.month, from_day.day),
        },
    ).all()
    return [{"name": name, "value": value} for name, value in rows]
