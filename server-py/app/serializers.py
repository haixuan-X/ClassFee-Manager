"""VO 序列化：字段名/日期格式与 Jackson @JsonFormat 逐一相同。

约定：
- 日期时间 → "yyyy-MM-dd HH:mm:ss"，日期 → "yyyy-MM-dd"，None → null
- 刚插入未回填的 createdAt 由调用方显式传 None（对齐 MyBatis-Plus insert 不回填）
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .models import ClsClass, FeeBatch, FeeCategory, FeePayment, FeeRecord, SysNotice, SysUser

# 读取对象字段的哨兵：用于区分「未传」与「显式 None（对齐 Java 刚插入未回填）」
UNSET: Any = object()


def fmt_dt(v: datetime | None) -> str | None:
    return v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime) else None


def fmt_d(v: date | None) -> str | None:
    if isinstance(v, datetime):
        v = v.date()
    return v.strftime("%Y-%m-%d") if isinstance(v, date) else None


def user_vo(u: SysUser, class_name: str | None) -> dict[str, Any]:
    return {
        "id": u.id,
        "username": u.username,
        "realName": u.real_name,
        "role": u.role if u.role is not None else "MEMBER",
        "classId": u.class_id,
        "className": class_name,
    }


def category_dict(c: FeeCategory) -> dict[str, Any]:
    return {
        "id": c.id,
        "classId": c.class_id,
        "name": c.name,
        "kind": c.kind,
        "icon": c.icon,
        "sort": c.sort,
        "status": c.status,
    }


def record_vo(
    r: FeeRecord,
    category_name: str | None,
    created_by_name: str | None,
    *,
    created_at: Any = UNSET,
    voided_by_name: str | None = None,
) -> dict[str, Any]:
    ca = r.created_at if created_at is UNSET else created_at
    return {
        "id": r.id,
        "type": r.type,
        "categoryId": r.category_id,
        "categoryName": category_name,
        "amount": r.amount,
        "title": r.title,
        "occurredAt": fmt_dt(r.occurred_at),
        "channel": r.channel,
        "remark": r.remark,
        "receiptUrl": r.receipt_url,
        "status": r.status,
        "createdBy": r.created_by,
        "createdByName": created_by_name,
        "createdAt": fmt_dt(ca),
        # 第十九轮审计：作废留痕。删除是硬删无痕，所以这两个字段是「账去哪了」的唯一线索
        "voidedBy": r.voided_by,
        "voidedByName": voided_by_name,
        "voidedAt": fmt_dt(r.voided_at),
    }


def batch_vo(
    b: FeeBatch,
    total: int,
    paid: int,
    *,
    created_at: Any = UNSET,
    created_by_name: str | None = None,
    closed_by_name: str | None = None,
) -> dict[str, Any]:
    ca = b.created_at if created_at is UNSET else created_at
    from decimal import Decimal, ROUND_HALF_UP

    if total == 0:
        rate = Decimal("0.0")
    else:
        rate = (Decimal(paid) * 100 / Decimal(total)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return {
        "id": b.id,
        "name": b.name,
        "amount": b.amount,
        "deadline": fmt_d(b.deadline),
        "remark": b.remark,
        "status": b.status,
        "createdAt": fmt_dt(ca),
        # 第十七轮归属权：前端靠它判断「关闭/删除」按钮是否该给（见 require_ownership）
        "createdBy": b.created_by,
        "createdByName": created_by_name,
        # 第十九轮审计：关闭留痕（谁、何时关的）
        "closedBy": b.closed_by,
        "closedByName": closed_by_name,
        "closedAt": fmt_dt(b.closed_at),
        "total": total,
        "paidCount": paid,
        "unpaidCount": total - paid,
        "rate": rate,
    }


def payment_vo(p: FeePayment, member: SysUser | None) -> dict[str, Any]:
    return {
        "id": p.id,
        "userId": p.user_id,
        "realName": member.real_name if member is not None else None,
        "studentNo": member.student_no if member is not None else None,
        "role": member.role if member is not None else None,
        "status": p.status,
        "amount": p.amount,
        "channel": p.channel,
        "paidAt": fmt_dt(p.paid_at),
        "recordId": p.record_id,
        "remark": p.remark,
    }


def member_vo(u: SysUser, batch: FeeBatch | None, payment: FeePayment | None) -> dict[str, Any]:
    vo: dict[str, Any] = {
        "userId": u.id,
        "username": u.username,
        "realName": u.real_name,
        "studentNo": u.student_no,
        "role": u.role,
        "status": u.status,
        "batchId": None,
        "payStatus": None,
        "amount": None,
        "channel": None,
        "paidAt": None,
        "recordId": None,
    }
    if batch is not None:
        vo["batchId"] = batch.id
        if payment is None:
            vo["payStatus"] = "UNPAID"
        else:
            vo["payStatus"] = payment.status
            vo["amount"] = payment.amount
            vo["channel"] = payment.channel
            vo["paidAt"] = fmt_dt(payment.paid_at)
            vo["recordId"] = payment.record_id
    return vo


def notice_vo(
    n: SysNotice,
    created_by_name: str | None,
    *,
    created_at: Any = UNSET,
    updated_by_name: str | None = None,
) -> dict[str, Any]:
    """班级公告出参：Java NoticeVO（id/title/content/pinned/publishedAt）+ status 与发布人。

    createdAt 与 record_vo 同理：刚插入未回填时由调用方显式传 None。
    """
    ca = n.created_at if created_at is UNSET else created_at
    return {
        "id": n.id,
        "title": n.title,
        "content": n.content,
        "pinned": n.pinned,
        "status": n.status,
        "publishedAt": fmt_dt(n.published_at),
        "createdBy": n.created_by,
        "createdByName": created_by_name,
        "createdAt": fmt_dt(ca),
        # 第十九轮审计：最后编辑人 / 时间（编辑、置顶、下架、恢复都会刷新）
        "updatedBy": n.updated_by,
        "updatedByName": updated_by_name,
        "updatedAt": fmt_dt(n.updated_at),
    }


def class_vo(c: ClsClass) -> dict[str, Any]:
    """班级信息出参：balance 是流水事务同步的冗余列，只读不可手改。"""
    return {
        "id": c.id,
        "className": c.class_name,
        "grade": c.grade,
        "headTeacher": c.head_teacher,
        "balance": c.balance,
        "status": c.status,
    }


def page_result(records: list[Any], total: int, page: int, size: int) -> dict[str, Any]:
    return {"records": records, "total": total, "page": page, "size": size}
