"""收支类别字典服务（对应 Java CategoryService）。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import BizException
from ..models import FeeCategory, FeeRecord
from ..schemas import CategoryRequest
from ..security import LoginUser
from ..serializers import category_dict


def list_categories(db: Session, user: LoginUser, kind: str | None) -> list[dict]:
    conds = [FeeCategory.class_id == user.class_id, FeeCategory.status == 1]
    has_kind = kind is not None and kind.strip() != ""
    if has_kind:
        # 过滤用原始值（Java .eq 绑定未 trim 的 kind）
        conds.append(FeeCategory.kind == kind)
    rows = db.scalars(
        select(FeeCategory)
        .where(*conds)
        .order_by(FeeCategory.sort.asc(), FeeCategory.id.asc())
    )
    return [category_dict(c) for c in rows]


def _ensure_name_unique(
    db: Session, class_id: int, kind: str | None, name: str | None, exclude_id: int | None
) -> None:
    conds = [
        FeeCategory.class_id == class_id,
        FeeCategory.kind == kind,
        FeeCategory.name == name,
        FeeCategory.status == 1,  # 只查启用中的：软删行不占名字
    ]
    if exclude_id is not None:
        conds.append(FeeCategory.id != exclude_id)
    dup = db.scalar(select(func.count()).select_from(FeeCategory).where(*conds)) or 0
    if dup > 0:
        raise BizException.bad_request("同类下已存在同名类别")


def _require_owned(db: Session, class_id: int, category_id: int) -> FeeCategory:
    existing = db.get(FeeCategory, category_id)
    # 他班类别一律当不存在，避免暴露存在性
    if existing is None or existing.class_id != class_id:
        raise BizException.bad_request("类别不存在或已停用")
    return existing


def create_category(db: Session, user: LoginUser, req: CategoryRequest) -> None:
    with db.begin():
        # CategoryRequest 允许全空（为了支持编辑的「不传=不修改」），新建必须显式给全
        if req.name is None or req.kind is None:
            raise BizException.bad_request("请填写类别名称并选择收支方向")
        _ensure_name_unique(db, user.class_id, req.kind, req.name, None)
        db.add(
            FeeCategory(
                class_id=user.class_id,
                name=req.name,
                kind=req.kind,
                icon=req.icon,
                sort=0 if req.sort is None else req.sort,
                status=1,
            )
        )


def update_category(
    db: Session, user: LoginUser, category_id: int, req: CategoryRequest
) -> None:
    """编辑类别：全部字段可选，**不传 = 不修改**（与账号编辑、公告编辑同口径）。

    第十六轮修掉三个真实缺陷：
    1. 旧实现 `if req.id is None: raise 缺少类别 id` —— 路径里已经有 id，客户端还要在 body 里
       重复一遍才能调通，按 REST 方式 `PUT /categories/124` 永远 400（接口事实上不可用）。
    2. body 里的 `id` **从不与路径 id 比对**，WHERE 用的是路径 id，传什么都无所谓 → 纯误导字段。
       现在传了且不一致直接 400。
    3. `kind`（收入/支出方向）可以随便翻，**包括已被流水引用的类别**——翻完之后历史支出流水
       会挂在一个「收入」类别下，账本分类与仪表盘占比全乱（与「支出抽屉混入收入类别」同源）。
       现在：被引用时禁止改方向，并说明原因。
    4. 顺带把 `sort` 也纳入「不传=不改」——旧实现 `sort: 0 if None else sort` 会在只改名字时
       把排序重置为 0（当时只给 `icon` 加了 null 不写入的保护，漏了 `sort`）。
    """
    with db.begin():
        if req.id is not None and req.id != category_id:
            raise BizException.bad_request("请求体里的类别 id 与路径不一致")
        if (
            req.name is None
            and req.kind is None
            and req.icon is None
            and req.sort is None
        ):
            raise BizException.bad_request("没有需要修改的内容")

        existing = _require_owned(db, user.class_id, category_id)
        target_kind = req.kind if req.kind is not None else existing.kind
        target_name = req.name if req.name is not None else existing.name

        if req.kind is not None and req.kind != existing.kind:
            used = (
                db.scalar(
                    select(func.count())
                    .select_from(FeeRecord)
                    .where(FeeRecord.category_id == category_id)
                )
                or 0
            )
            if used > 0:
                raise BizException.bad_request(
                    f"该类别已有 {used} 笔流水，不能改变收支方向"
                    "（收入/支出方向决定账本与统计口径）"
                )
        if req.name is not None or req.kind is not None:
            _ensure_name_unique(db, existing.class_id, target_kind, target_name, existing.id)

        # null 字段不写入（MyBatis-Plus updateById 语义）
        values: dict = {}
        if req.name is not None:
            values["name"] = req.name
        if req.kind is not None:
            values["kind"] = req.kind
        if req.icon is not None:
            values["icon"] = req.icon
        if req.sort is not None:
            values["sort"] = req.sort
        db.execute(
            FeeCategory.__table__.update()
            .where(FeeCategory.id == existing.id)
            .values(**values)
        )


def delete_category(db: Session, user: LoginUser, category_id: int) -> None:
    """删除类别：**软删除**（status=0），不是硬删。

    第十六轮修：旧实现对未被引用的类别直接 `db.delete()` 硬删，而接口文档、前端注释
    （`api/records.ts`「未被流水引用转停用」）和表设计（`fee_category.status` 列 +
    `_ensure_name_unique` 只查 status=1）全都是按「停用」设计的。硬删的实际后果是：
    误删一个还没用过的类别就**永久消失**，字典里凭空少一行，且没有任何恢复途径
    （回归脚本就踩到过这个坑：断言「删种子类别应被拒」失败，其实是被硬删了）。
    改软删后：列表不再返回它、名字可以被新类别复用、id 仍可用于历史数据还原。
    """
    with db.begin():
        existing = _require_owned(db, user.class_id, category_id)

        used = (
            db.scalar(
                select(func.count())
                .select_from(FeeRecord)
                .where(FeeRecord.category_id == category_id)
            )
            or 0
        )
        if used > 0:
            raise BizException.bad_request(
                f"该类别已有 {used} 笔流水，不能删除；可改名继续使用"
            )

        db.execute(
            FeeCategory.__table__.update()
            .where(FeeCategory.id == existing.id)
            .values(status=0)
        )
