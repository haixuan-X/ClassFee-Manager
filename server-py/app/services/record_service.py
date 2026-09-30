"""收支流水服务：记账、查询、作废（红冲）、删除（对应 Java RecordService）。"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session

from ..errors import BizException
from ..helpers import add_balance, like_pattern, parse_boundary
from ..models import FeeCategory, FeePayment, FeeRecord, SysUser
from ..schemas import RecordRequest
from ..security import LoginUser, require_ownership
from ..serializers import page_result, record_vo
from . import file_service

log = logging.getLogger("classfee")


def _delta(record: FeeRecord) -> Decimal:
    return record.amount if record.type == "INCOME" else -record.amount


def _creator_name(db: Session, user: LoginUser) -> str:
    """录入人姓名从库里取：JWT 只带 id/username/role/classId。"""
    creator = db.get(SysUser, user.id)
    return creator.real_name if creator is not None else user.username


def _names_for(db: Session, records: list[FeeRecord]) -> tuple[dict, dict]:
    cat_ids = {r.category_id for r in records if r.category_id is not None}
    # 第十九轮：作废人也要姓名，合并进同一次查询（仍然只发一条 SQL，不引入 N+1）
    user_ids = {r.created_by for r in records if r.created_by is not None}
    user_ids |= {r.voided_by for r in records if r.voided_by is not None}
    cat_names = {}
    if cat_ids:
        for c in db.scalars(select(FeeCategory).where(FeeCategory.id.in_(cat_ids))):
            cat_names.setdefault(c.id, c.name)
    names = {}
    if user_ids:
        for u in db.scalars(select(SysUser).where(SysUser.id.in_(user_ids))):
            names.setdefault(u.id, u.real_name)
    return cat_names, names


def to_vo_list(db: Session, records: list[FeeRecord]) -> list[dict]:
    """批量补齐类别名、录入人与作废人姓名，避免逐条查询（N+1）；仪表盘复用。"""
    if not records:
        return []
    cat_names, names = _names_for(db, records)
    return [
        record_vo(
            r,
            cat_names.get(r.category_id),
            names.get(r.created_by),
            voided_by_name=names.get(r.voided_by),
        )
        for r in records
    ]


def build_record_filters(
    user: LoginUser,
    *,
    type_: str | None,
    category_id: int | None,
    keyword: str | None,
    status: str | None,
    record_id: int | None,
    start: str | None,
    end: str | None,
    channel: str | None = None,
):
    """账本筛选条件（列表与导出共用，保证「看到什么就导出什么」）。

    第十六轮：枚举值改为**校验**而不是直接塞进 WHERE。旧实现把任意字符串当等值条件，
    于是 `status=all`、`type=all`、`status=BOGUS` 都会静默返回 0 条——调用方（尤其是
    导出、脚本、第三方集成）无从分辨「没有数据」和「参数写错了」。现在：
    - 空值 / `all`（大小写不敏感）= 不筛选
    - 合法枚举值 = 按值筛选
    - 其它值 = 400，指名道姓告诉哪个参数错了
    """

    def _norm(value: str | None) -> str:
        """去空白 + 大写；`all` / 空串是「不筛选」的哨兵值。"""
        return (value or "").strip().upper()

    t = _norm(type_)
    s = _norm(status)
    ch = _norm(channel)

    kw = keyword.strip() if keyword is not None else ""
    has_keyword = kw != ""

    if t and t != "ALL" and t not in ("INCOME", "EXPENSE"):
        raise BizException.bad_request("收支方向只能是 INCOME / EXPENSE 或 all")
    if s and s != "ALL" and s not in ("NORMAL", "VOID"):
        raise BizException.bad_request("流水状态只能是 NORMAL / VOID 或 all")
    if ch and ch != "ALL" and ch not in ("CASH", "WECHAT", "ALIPAY", "BANK", "OTHER"):
        raise BizException.bad_request("支付渠道不合法")

    start_dt = parse_boundary(start, False)
    end_dt = parse_boundary(end, True)

    conds = [FeeRecord.class_id == user.class_id]
    if record_id is not None:
        conds.append(FeeRecord.id == record_id)
    if t and t != "ALL":
        conds.append(FeeRecord.type == t)
    if category_id is not None:
        conds.append(FeeRecord.category_id == category_id)
    if s and s != "ALL":
        conds.append(FeeRecord.status == s)
    if ch and ch != "ALL":
        conds.append(FeeRecord.channel == ch)
    if start_dt is not None:
        conds.append(FeeRecord.occurred_at >= start_dt)
    if end_dt is not None:
        conds.append(FeeRecord.occurred_at < end_dt)
    if has_keyword:
        pattern = like_pattern(kw)
        conds.append(or_(FeeRecord.title.like(pattern), FeeRecord.remark.like(pattern)))
    return and_(*conds)


def list_records(
    db: Session,
    user: LoginUser,
    *,
    page: int,
    size: int,
    type_: str | None,
    category_id: int | None,
    keyword: str | None,
    status: str | None,
    record_id: int | None,
    start: str | None,
    end: str | None,
    channel: str | None = None,
) -> dict:
    where = build_record_filters(
        user,
        type_=type_,
        category_id=category_id,
        keyword=keyword,
        status=status,
        record_id=record_id,
        start=start,
        end=end,
        channel=channel,
    )
    total = db.scalar(select(func.count()).select_from(FeeRecord).where(where)) or 0
    rows = list(
        db.scalars(
            select(FeeRecord)
            .where(where)
            .order_by(FeeRecord.occurred_at.desc(), FeeRecord.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    )
    return page_result(to_vo_list(db, rows), total, page, size)


def create_record(db: Session, user: LoginUser, req: RecordRequest) -> dict:
    with db.begin():
        category = db.get(FeeCategory, req.categoryId)
        if (
            category is None
            or user.class_id != category.class_id
            or category.status != 1
        ):
            raise BizException.bad_request("所选类别不存在或已停用")
        if category.kind != req.type:
            raise BizException.bad_request("类别与收支类型不匹配，请重新选择")

        # 小票只挂支出（设计文档 M4：报销/采购票据）；路径必须指向真实存在的上传文件
        if req.receiptUrl:
            if req.type != "EXPENSE":
                raise BizException.bad_request("仅支出流水可上传小票图片")
            if file_service.resolve_receipt(req.receiptUrl) is None:
                raise BizException.bad_request("小票文件不存在或已失效，请重新上传")

        record = FeeRecord(
            class_id=user.class_id,
            type=req.type,
            category_id=category.id,
            amount=req.amount,
            title=(req.title or "").strip(),
            occurred_at=req.occurredAt,
            channel=req.channel if req.channel else "CASH",
            remark=req.remark,
            receipt_url=req.receiptUrl,
            status="NORMAL",
            created_by=user.id,
        )
        db.add(record)
        db.flush()

        add_balance(db, user.class_id, _delta(record))

        creator_name = _creator_name(db, user)
        return record_vo(
            record, category.name, creator_name, created_at=None  # MP 不回填 createdAt
        )


def void_record(db: Session, user: LoginUser, record_id: int) -> None:
    with db.begin():
        record = db.get(FeeRecord, record_id)
        if record is None or user.class_id != record.class_id:
            raise BizException.bad_request("流水不存在或无权操作")
        if record.status == "VOID":
            raise BizException.bad_request("该流水已作废，无需重复操作")
        # 第十七轮归属权：只能作废自己记的流水
        require_ownership(user.id, record.created_by, what="流水")

        result = db.execute(
            update(FeeRecord)
            .where(FeeRecord.id == record_id, FeeRecord.status == "NORMAL")
            # 第十九轮审计：作废留痕（谁、何时）。删除是硬删无痕，所以「作废」是
            # 唯一能回答「这笔账为什么消失、是谁弄的」的路径，必须写。
            .values(status="VOID", voided_by=user.id, voided_at=datetime.now())
        )
        if result.rowcount == 0:
            raise BizException.bad_request("该流水状态已变化，请刷新后重试")

        add_balance(db, record.class_id, -_delta(record))

        # 批次自动流水被作废 → 同事务把缴费状态退回未缴
        if record.batch_id is not None:
            db.execute(
                update(FeePayment)
                .where(
                    FeePayment.record_id == record.id,
                    FeePayment.status == "PAID",
                )
                .values(status="UNPAID")
            )


def delete_record(db: Session, user: LoginUser, record_id: int) -> None:
    # 提交前先取路径：commit 后 record 过期，再读属性会因行已删而抛错
    receipt_path: str | None = None
    with db.begin():
        record = db.get(FeeRecord, record_id)
        if record is None or user.class_id != record.class_id:
            raise BizException.bad_request("流水不存在或无权操作")
        # 第十七轮归属权：只能删自己记的流水（删除会回滚余额、不可恢复，闸门放在最前面）
        require_ownership(user.id, record.created_by, what="流水")

        # 删除条件带上「读到的状态」：并发时命中 0 行并整体回滚，避免双扣
        result = db.execute(
            delete(FeeRecord).where(
                FeeRecord.id == record_id, FeeRecord.status == record.status
            )
        )
        if result.rowcount == 0:
            raise BizException.bad_request("该流水状态已变化，请刷新后重试")

        if record.status == "NORMAL":
            add_balance(db, record.class_id, -_delta(record))

        # 批次流水被删 → 缴费行退回未缴并解除关联
        if record.batch_id is not None:
            db.execute(
                update(FeePayment)
                .where(FeePayment.record_id == record.id)
                .values(status="UNPAID", record_id=None)
            )
        receipt_path = record.receipt_url

    # 提交成功后再回收小票磁盘文件：仅当没有任何流水还引用它（上传按 uuid 生成、
    # 正常 1:1，但 API 层允许复用同一路径）；回收失败不影响删除结果
    if receipt_path:
        try:
            still_used = db.scalar(
                select(FeeRecord.id).where(FeeRecord.receipt_url == receipt_path).limit(1)
            )
            if still_used is None:
                file_service.delete_receipt(receipt_path)
        except Exception:  # noqa: BLE001 —— 删除已提交，回收阶段异常只记日志
            log.warning("failed to recycle receipt file: %s", receipt_path, exc_info=True)
