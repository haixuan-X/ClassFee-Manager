"""VO 序列化：字段名/日期格式与 Jackson @JsonFormat 逐一相同。

约定：
- 日期时间 → "yyyy-MM-dd HH:mm:ss"，日期 → "yyyy-MM-dd"，None → null
- 刚插入未回填的 createdAt 由调用方显式传 None（对齐 MyBatis-Plus insert 不回填）
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .models import ClsClass, FeeBatch, FeeCategory, FeePayment, FeeRecord, SysUser

# 读取对象字段的哨兵：用于区分「未传」与「显式 None（刚插入未回填的对象）」
UNSET: Any = object()


def fmt_dt(v: datetime | None) -> str | None:
    return v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime) else None


def fmt_d(v: date | None) -> str | None:
    if isinstance(v, datetime):
        v = v.date()
    return v.strftime("%Y-%m-%d") if isinstance(v, date) else None


def user_vo(
    u: SysUser,
    class_name: str | None,
    managed_classes: list[tuple[int, str]] | None = None,
) -> dict[str, Any]:
    # 函数内导入：`security` 在模块顶层导入过 `responses`，这里再顶层导入
    # serializers 就绕回去了。放函数内是因为它只在访客那条分支才用得上。
    from .security import DEAN_ROLE, GUEST_ROLE, parse_guest_scopes

    managed = managed_classes or [(u.class_id, class_name or "")]
    managed_ids = [cid for cid, _ in managed]
    managed_names = [name for _, name in managed]
    return {
        "id": u.id,
        "username": u.username,
        "realName": u.real_name,
        "role": u.role if u.role is not None else "MEMBER",
        # 第二十六轮：访客的可见范围。登录响应和 /auth/me 共用这一个序列化器，
        # 所以前端登录完立刻就能按它过滤侧栏和路由，不必再发一次请求。
        # 非访客一律 null——「他看不见什么」这个问题对其他角色不存在。
        "guestScopes": parse_guest_scopes(u.guest_scopes) if u.role == GUEST_ROLE else None,
        # 第三十轮：是不是纯院长。登录响应和 /auth/me 共用这一个序列化器，
        # 前端登录完立刻就能按它决定侧栏给不给「账目」「班级」两组。
        "deanOnly": u.role == DEAN_ROLE and bool(u.dean_only),
        "classId": u.class_id,
        "className": class_name,
        # 第三十二轮：这个人**能管哪些班**。
        #
        # 一个班主任常带好几个班；前端靠这两个字段渲染「班级切换器」，
        # 切换后所有请求都带上 `classId`（后端在鉴权中间件里校验它可不可管）。
        "classIds": managed_ids or [u.class_id],
        "classNames": managed_names or ([class_name] if class_name else []),
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


# 第二十四轮：班级公告已整体移除，`notice_vo` 连同 SysNotice 模型、页面、
# 路由、接口、sys_notice 表一并删除。


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
