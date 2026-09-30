"""收费批次服务：建批次 → 逐人标记缴费（同事务生成流水）→ 关闭/删除（对应 Java BatchService）。

不变式（同一事务维护）：
1. fee_payment.status=PAID ⟺ 其 record_id 指向一条 NORMAL 流水
2. 自动流水与 cls_class.balance 同事务原子变更
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..errors import BizException
from ..helpers import add_balance, like_pattern, lock_class
from ..models import FeeBatch, FeeCategory, FeePayment, FeeRecord, SysUser
from ..schemas import BatchPayRequest, BatchRequest
from ..security import STAFF_ROLES, LoginUser, require_ownership
from ..serializers import batch_vo, fmt_d, fmt_dt, member_vo, payment_vo

PREFERRED_INCOME_CATEGORY = "班费收取"


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[:max_len]


def _stat_map(db: Session, batches: list[FeeBatch]) -> dict[int, tuple[int, int]]:
    """批次统计（一次聚合查询，避免 N+1）。"""
    if not batches:
        return {}
    ids = [b.id for b in batches]
    rows = db.execute(
        select(
            FeePayment.batch_id,
            func.count().label("total"),
            func.sum(case((FeePayment.status == "PAID", 1), else_=0)).label("paid"),
        )
        .where(FeePayment.batch_id.in_(ids))
        .group_by(FeePayment.batch_id)
    )
    out: dict[int, tuple[int, int]] = {}
    for batch_id, total, paid in rows:
        out[int(batch_id)] = (int(total), int(paid or 0))
    return out


def _creator_names(db: Session, batches: list[FeeBatch]) -> dict[int, str]:
    """批量补创建人与关闭人姓名（第十九轮：关闭留痕也要能看到人名）。"""
    ids = {b.created_by for b in batches if b.created_by is not None}
    ids |= {b.closed_by for b in batches if b.closed_by is not None}
    names: dict[int, str] = {}
    if ids:
        for u in db.scalars(select(SysUser).where(SysUser.id.in_(ids))):
            names.setdefault(u.id, u.real_name)
    return names


def to_vo_list(
    db: Session, batches: list[FeeBatch], *, fresh: bool = False
) -> list[dict]:
    stats = _stat_map(db, batches)
    names = _creator_names(db, batches)
    result = []
    for b in batches:
        total, paid = stats.get(b.id, (0, 0))
        result.append(
            batch_vo(
                b,
                total,
                paid,
                created_at=None if fresh else b.created_at,
                created_by_name=names.get(b.created_by),
                closed_by_name=names.get(b.closed_by),
            )
        )
    return result


def _require_batch(db: Session, class_id: int, batch_id: int) -> FeeBatch:
    batch = db.get(FeeBatch, batch_id)
    if batch is None or batch.class_id != class_id:
        raise BizException.bad_request("批次不存在或无权操作")
    return batch


def _require_batch_for_update(db: Session, class_id: int, batch_id: int) -> FeeBatch:
    batch = db.execute(
        select(FeeBatch).where(FeeBatch.id == batch_id).with_for_update()
    ).scalar()
    if batch is None or batch.class_id != class_id:
        raise BizException.bad_request("批次不存在或无权操作")
    return batch


def _resolve_batch(db: Session, batch_id: int | None, class_id: int) -> FeeBatch | None:
    """批次解析：指定 id > 最新进行中 > 最新。"""
    if batch_id is not None:
        return _require_batch(db, class_id, batch_id)
    open_batch = db.execute(
        select(FeeBatch)
        .where(FeeBatch.class_id == class_id, FeeBatch.status == "OPEN")
        .order_by(FeeBatch.id.desc())
        .limit(1)
    ).scalar()
    if open_batch is not None:
        return open_batch
    return db.execute(
        select(FeeBatch)
        .where(FeeBatch.class_id == class_id)
        .order_by(FeeBatch.id.desc())
        .limit(1)
    ).scalar()


# ============================ 缴费对象口径 ============================

# **第二十轮口径**：缴费对象 = 全部**学生**（普通成员 MEMBER / 生活委员 ADMIN / 班长 MONITOR），
# 只有班主任 TEACHER 排除。
#
# 为什么改：第十四轮定的是「只算 MEMBER」，理由是「运营角色是管账的人不该出现在缴费名单里，
# 否则完成率永远差几个人」。这个理由对**班主任**成立（.env 声明的老师账号，根本不是学生），
# 但对**生活委员 / 班长**不成立 —— 他们是在自己班里承担班务的**学生**，班费照交。
# 沿用旧口径的真实后果不是「完成率不好看」，而是**班里收不到他们的班费**：他们不在
# 缴费名单里，成员缴费页列不出他们，代为登记也就无处可登记。
#
# 班主任仍然排除，所以他的「我的缴费」入口在第二十轮一并移除（见 router / SideNav 的 roles）。
#
# 这是一个**常量**，_class_members 与 members() 都从这里取：两处口径必须一致，否则会出现
# 「批次里已经生成了缴费行、缴费名单页却列不出这个人」的死角。
PAYABLE_ROLES = ("MEMBER", "ADMIN", "MONITOR")


def _class_members(db: Session, class_id: int) -> list[SysUser]:
    """**缴费对象**：本班全部学生（MEMBER / 生活委员 ADMIN / 班长 MONITOR），不含班主任。

    第十四轮原本只算 MEMBER，第二十轮按用户确认改为「除班主任外全员」——生活委员和班长
    也是学生，班费照交。口径常量见 `PAYABLE_ROLES`。
    """
    return list(
        db.scalars(
            select(SysUser)
            .where(
                SysUser.class_id == class_id,
                SysUser.status == 1,
                SysUser.role.in_(PAYABLE_ROLES),
            )
            .order_by(SysUser.username.asc())
        )
    )


def _income_category(db: Session, class_id: int) -> FeeCategory:
    categories = list(
        db.scalars(
            select(FeeCategory)
            .where(
                FeeCategory.class_id == class_id,
                FeeCategory.kind == "INCOME",
                FeeCategory.status == 1,
            )
            .order_by(FeeCategory.sort.asc())
        )
    )
    if not categories:
        raise BizException.bad_request("缺少可用的收入类别，请先在类别字典中配置")
    for c in categories:
        if c.name == PREFERRED_INCOME_CATEGORY:
            return c
    return categories[0]


def _remarkable_after_void(db: Session, payment: FeePayment | None) -> bool:
    """缴费行是否处于「流水作废、等待重新标记」状态。"""
    if payment is None or payment.record_id is None or payment.status != "UNPAID":
        return False
    old = db.get(FeeRecord, payment.record_id)
    return old is not None and old.status == "VOID"


# ============================ 批次 ============================


def list_batches(db: Session, user: LoginUser) -> list[dict]:
    """批次列表。

    第十八轮：**放开给所有登录角色**，但按角色裁剪。

    起因：普通成员能看账本、能看仪表盘上的「缴费完成率 50%」，却**没有任何入口知道自己
    交没交** —— 那三个问题（有没有班费要交 / 我交了吗 / 什么时候截止）本来不需要缴费
    名单就能回答，403 把它们一起挡掉了。

    口径：
    - 运营角色（ADMIN/MONITOR/TEACHER）：完整 VO（含 `createdBy` / `rate` / `remark`）。
    - 其它角色：**精简 VO**，不含 `createdBy` / `rate` / `remark` 等内部字段。
    - 两边都带 `myStatus` / `myAmount` / `myPaidAt` / `myAmountDue`，值为 `null` 表示
      「你不属于这个批次的缴费对象」（**班主任天然如此**；成员若是建批次之后才入班也如此）。
      **这几个键对所有角色都稳定存在** —— 早先只给非运营角色，导致前端拿到 `undefined`，
      `=== null` 判断落空，把「你不属于缴费对象」显示成了「未缴费」。
      第二十轮起生活委员与班长也进了缴费名单（`PAYABLE_ROLES`），所以他们同样拿得到真值。
    - **缴费名单仍然专属**：`GET /batches/{id}/payments` 与 `GET /members` 里是别人的
      姓名 / 学号 / 手机号，继续留在 `_STAFF_ROUTES` 里。这里只放开「批次 + 我自己」。
    """
    batches = list(
        db.scalars(
            select(FeeBatch)
            .where(FeeBatch.class_id == user.class_id)
            .order_by(FeeBatch.id.desc())
        )
    )
    is_staff = user.role in STAFF_ROLES
    base = to_vo_list(db, batches) if is_staff else _slim_batch_list(db, batches)
    if not batches:
        return base
    mine = _my_payments(db, user.id, [b.id for b in batches])
    for vo, b in zip(base, batches):
        vo.update(_my_vo_fields(db, mine.get(b.id)))
    return base


def _slim_batch_list(db: Session, batches: list[FeeBatch]) -> list[dict]:
    """非运营角色的批次 VO：只保留「该不该交 / 交了多少 / 什么时候截止」需要的信息。

    刻意**不含**：createdBy（内部归属字段）、rate（完成率由仪表盘给）、
    remark（班务内部备注，可能写了减免等未公开信息）。
    聚合数 total/paidCount/unpaidCount 保留 —— 仪表盘本来就把完成率给所有人看，
    不算新增泄露，反而让同学知道自己身后还差几个。
    """
    stats = _stat_map(db, batches)
    out: list[dict] = []
    for b in batches:
        total, paid = stats.get(b.id, (0, 0))
        out.append(
            {
                "id": b.id,
                "name": b.name,
                "amount": b.amount,
                "deadline": fmt_d(b.deadline),
                "status": b.status,
                "total": total,
                "paidCount": paid,
                "unpaidCount": total - paid,
            }
        )
    return out


def _my_payments(
    db: Session, user_id: int, batch_ids: list[int]
) -> dict[int, FeePayment]:
    """一次性取出「我」在这些批次里的缴费行（避免 N+1）。"""
    if not batch_ids:
        return {}
    out: dict[int, FeePayment] = {}
    for p in db.scalars(
        select(FeePayment).where(
            FeePayment.batch_id.in_(batch_ids), FeePayment.user_id == user_id
        )
    ):
        out.setdefault(p.batch_id, p)
    return out


def _my_vo_fields(db: Session, payment: FeePayment | None) -> dict:
    """我自己的缴费状态；对所有角色都返回这组键（无缴费行时值为 None）。"""
    return {
        "myStatus": payment.status if payment is not None else None,
        "myAmount": payment.amount if payment is not None else None,
        "myPaidAt": fmt_dt(payment.paid_at) if payment is not None else None,
        "myAmountDue": _remarkable_after_void(db, payment),
    }


def create_batch(db: Session, user: LoginUser, req: BatchRequest) -> dict:
    with db.begin():
        # 行锁班级：同班并发创建串行化
        lock_class(db, user.class_id)

        name = (req.name or "").strip()
        duplicated = (
            db.scalar(
                select(func.count())
                .select_from(FeeBatch)
                .where(
                    FeeBatch.class_id == user.class_id,
                    FeeBatch.status == "OPEN",
                    FeeBatch.name == name,
                )
            )
            or 0
        )
        if duplicated > 0:
            raise BizException.bad_request("已存在同名的进行中批次，请勿重复创建")

        batch = FeeBatch(
            class_id=user.class_id,
            name=name,
            amount=(req.amount or Decimal("0.01")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ),
            deadline=req.deadline,
            remark=req.remark,
            status="OPEN",
            created_by=user.id,
        )
        db.add(batch)
        db.flush()

        members = _class_members(db, user.class_id)
        if not members:
            # 第二十轮：口径是「除班主任外的学生」，所以措辞不能再只说「暂无成员」
            raise BizException.bad_request("班级暂无缴费对象（只有班主任账号），无法创建批次")
        for member in members:
            db.add(
                FeePayment(
                    batch_id=batch.id,
                    user_id=member.id,
                    amount=Decimal("0.00"),
                    status="UNPAID",
                )
            )
        db.flush()
        return to_vo_list(db, [batch], fresh=True)[0]


def detail(db: Session, user: LoginUser, batch_id: int) -> dict:
    batch = _require_batch(db, user.class_id, batch_id)
    payments = list(
        db.scalars(
            select(FeePayment)
            .where(FeePayment.batch_id == batch_id)
            .order_by(FeePayment.id.asc())
        )
    )
    user_ids = {p.user_id for p in payments}
    users: dict[int, SysUser] = {}
    if user_ids:
        for u in db.scalars(select(SysUser).where(SysUser.id.in_(user_ids))):
            users.setdefault(u.id, u)

    rows = [payment_vo(p, users.get(p.user_id)) for p in payments]
    # 按学号排序（空当空串），Python sort 稳定，等价 Java Comparator 链
    rows.sort(key=lambda v: (v["studentNo"] or "", v["realName"] or ""))
    return {"batch": to_vo_list(db, [batch])[0], "payments": rows}


def pay(db: Session, user: LoginUser, batch_id: int, req: BatchPayRequest) -> None:
    with db.begin():
        # 行锁批次：与 close 的条件更新串行，堵住「关闭后仍入账」的并发窗口
        batch = _require_batch_for_update(db, user.class_id, batch_id)

        payer = db.get(SysUser, req.userId)
        if payer is None or batch.class_id != payer.class_id:
            raise BizException.bad_request("缴费成员不存在或不属于本班")
        if payer.status != 1:
            raise BizException.bad_request("该成员账号已停用")

        payment = db.execute(
            select(FeePayment)
            .where(FeePayment.batch_id == batch_id, FeePayment.user_id == payer.id)
            .limit(1)
        ).scalar()
        if payment is not None and payment.status == "PAID":
            raise BizException.bad_request(f"{payer.real_name} 已缴费，无需重复标记")
        # 关闭后仅放行「作废后重新标记」
        if batch.status == "CLOSED" and not _remarkable_after_void(db, payment):
            raise BizException.bad_request("批次已关闭，不能继续标记缴费")

        amount = (
            batch.amount
            if req.amount is None
            else req.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
        channel = req.channel if req.channel else "CASH"
        occurred_at = req.occurredAt if req.occurredAt is not None else datetime.now()

        category = _income_category(db, batch.class_id)
        record = FeeRecord(
            class_id=batch.class_id,
            type="INCOME",
            category_id=category.id,
            amount=amount,
            title=_truncate(f"收取{batch.name}·{payer.real_name}", 60),
            occurred_at=occurred_at,
            channel=channel,
            payer_user_id=payer.id,
            batch_id=batch.id,
            remark=req.remark,
            status="NORMAL",
            created_by=user.id,
        )
        db.add(record)
        db.flush()

        add_balance(db, batch.class_id, amount)

        if payment is None:
            # 罕见路径：批次行缺失时补建（并发撞 uk_batch_user 由事务回滚兜底）
            db.add(
                FeePayment(
                    batch_id=batch_id,
                    user_id=payer.id,
                    amount=amount,
                    status="PAID",
                    channel=channel,
                    paid_at=occurred_at,
                    record_id=record.id,
                    remark=req.remark,
                )
            )
            try:
                db.flush()
            except IntegrityError:
                raise BizException.bad_request("该成员缴费状态已变化，请刷新后重试") from None
        else:
            # status != PAID 做条件更新：双击/并发只命中一行，另一路 0 行回滚
            result = db.execute(
                update(FeePayment)
                .where(FeePayment.id == payment.id, FeePayment.status != "PAID")
                .values(
                    status="PAID",
                    amount=amount,
                    channel=channel,
                    paid_at=occurred_at,
                    record_id=record.id,
                    remark=req.remark,
                )
            )
            if result.rowcount == 0:
                raise BizException.bad_request("该成员缴费状态已变化，请刷新后重试")


def close(db: Session, user: LoginUser, batch_id: int) -> None:
    with db.begin():
        batch = _require_batch(db, user.class_id, batch_id)
        # 第十七轮归属权：只能关闭自己建的批次（关闭后不能再收款，是实质动作）
        require_ownership(user.id, batch.created_by, what="收费批次")
        result = db.execute(
            update(FeeBatch)
            .where(FeeBatch.id == batch_id, FeeBatch.status == "OPEN")
            # 第十九轮审计：关闭后不能收款，是实质动作，记谁关的、什么时候
            .values(status="CLOSED", closed_by=user.id, closed_at=datetime.now())
        )
        if result.rowcount == 0:
            now = db.get(FeeBatch, batch_id)
            if now is not None and now.status == "CLOSED":
                raise BizException.bad_request("批次已关闭，无需重复操作")
            raise BizException.bad_request("批次状态已变化，请刷新后重试")


def delete_batch(db: Session, user: LoginUser, batch_id: int) -> None:
    with db.begin():
        batch = _require_batch_for_update(db, user.class_id, batch_id)
        # 第十七轮归属权：只能删自己建的批次（删除会连带抹掉缴费与自动流水）
        require_ownership(user.id, batch.created_by, what="收费批次")

        records = list(
            db.scalars(select(FeeRecord).where(FeeRecord.batch_id == batch_id))
        )
        # 回滚量 = 各笔正常流水的增量取反：收入减掉、支出加回来
        rollback = Decimal(0)
        for r in records:
            if r.status != "NORMAL":
                continue
            rollback += -r.amount if r.type == "INCOME" else r.amount

        db.execute(delete(FeeRecord).where(FeeRecord.batch_id == batch_id))
        db.execute(delete(FeePayment).where(FeePayment.batch_id == batch_id))
        db.execute(delete(FeeBatch).where(FeeBatch.id == batch.id))

        if rollback != 0:
            add_balance(db, batch.class_id, rollback)


# ============================ 成员缴费 ============================


def members(
    db: Session,
    user: LoginUser,
    *,
    keyword: str | None,
    pay_status: str | None,
    batch_id: int | None,
) -> list[dict]:
    batch = _resolve_batch(db, batch_id, user.class_id)

    kw = keyword.strip() if keyword is not None else ""
    # 缴费名单必须与 _class_members **完全同口径**（PAYABLE_ROLES）：
    # 若这里少列一个人，批次里已经生成的缴费行就没法在页面上登记，完成率会永远卡住
    conds = [
        SysUser.class_id == user.class_id,
        SysUser.status == 1,
        SysUser.role.in_(PAYABLE_ROLES),
    ]
    if kw:
        pattern = like_pattern(kw)
        conds.append(
            or_(
                SysUser.real_name.like(pattern),
                SysUser.student_no.like(pattern),
                SysUser.username.like(pattern),
            )
        )
    users = list(
        db.scalars(select(SysUser).where(*conds).order_by(SysUser.username.asc()))
    )

    pay_map: dict[int, FeePayment] = {}
    if batch is not None:
        for p in db.scalars(
            select(FeePayment).where(FeePayment.batch_id == batch.id)
        ):
            pay_map.setdefault(p.user_id, p)

    result = [member_vo(u, batch, pay_map.get(u.id)) for u in users]

    if pay_status is not None and pay_status.strip() != "":
        result = [m for m in result if m["payStatus"] == pay_status]
    return result


def completion_rate(db: Session, class_id: int) -> Decimal | None:
    """仪表盘完成率：0-100（1 位小数）；班级还没有批次时为 null。"""
    batch = _resolve_batch(db, None, class_id)
    if batch is None:
        return None
    return to_vo_list(db, [batch])[0]["rate"]
