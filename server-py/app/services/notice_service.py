"""班级公告服务：发布 / 编辑 / 置顶 / 下架恢复 / 彻底删除（M4，对应 sys_notice 表）。

权限口径：列表全员可读，**非运营角色只能看到已发布**（status=1）；
写操作（发布/编辑/下架/恢复/删除）由中间件 `_STAFF_ROUTES` 限定 ADMIN/TEACHER。
下架是软删除（可恢复），彻底删除要求先下架，避免误删后无从找回。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..errors import BizException
from ..helpers import like_pattern
from ..models import SysNotice, SysUser
from ..schemas import NoticeRequest
from ..security import STAFF_ROLES, LoginUser, require_ownership
from ..serializers import notice_vo


def _creator_names(db: Session, rows: list[SysNotice]) -> dict[int, str]:
    """批量补发布人与最后编辑人姓名，避免逐条查询（N+1）。"""
    ids = {r.created_by for r in rows if r.created_by is not None}
    ids |= {r.updated_by for r in rows if r.updated_by is not None}
    names: dict[int, str] = {}
    if ids:
        for u in db.scalars(select(SysUser).where(SysUser.id.in_(ids))):
            names.setdefault(u.id, u.real_name)
    return names


def _require_owned(db: Session, class_id: int, notice_id: int) -> SysNotice:
    existing = db.get(SysNotice, notice_id)
    # 他班公告一律当不存在，避免暴露存在性
    if existing is None or existing.class_id != class_id:
        raise BizException.bad_request("公告不存在或已删除")
    return existing


def list_notices(
    db: Session, user: LoginUser, *, status: str | None, keyword: str | None
) -> list[dict]:
    raw = (status or "1").strip() or "1"
    if raw not in ("0", "1", "all"):
        raise BizException.bad_request("公告状态不合法")
    # 第十六轮：原来只把 `all` 归一成 "1"，但**显式传 status=0 仍能读到已下架公告**
    # （实测普通成员 GET /notices?status=0 返回 200 且带出下架内容）——
    # 下架是「撤回」语义，对非运营角色一律只暴露已发布。
    want = raw if user.role in STAFF_ROLES else "1"

    conds = [SysNotice.class_id == user.class_id]
    if want != "all":
        conds.append(SysNotice.status == int(want))
    kw = keyword.strip() if keyword is not None else ""
    if kw != "":
        pattern = like_pattern(kw)
        conds.append(or_(SysNotice.title.like(pattern), SysNotice.content.like(pattern)))

    rows = list(
        db.scalars(
            select(SysNotice)
            .where(*conds)
            .order_by(
                SysNotice.pinned.desc(),
                SysNotice.published_at.desc(),
                SysNotice.id.desc(),
            )
        )
    )
    names = _creator_names(db, rows)
    return [notice_vo(r, names.get(r.created_by), updated_by_name=names.get(r.updated_by)) for r in rows]


def create_notice(db: Session, user: LoginUser, req: NoticeRequest) -> dict:
    """发布公告：恒为「已发布」并记发布时间（草稿语义不在需求内，status 传值忽略）。"""
    if req.title is None:
        raise BizException.bad_request("请输入公告标题")
    if req.content is None:
        raise BizException.bad_request("请输入公告内容")
    with db.begin():
        notice = SysNotice(
            class_id=user.class_id,
            title=req.title.strip(),
            content=req.content.strip(),
            pinned=0 if req.pinned is None else req.pinned,
            status=1,
            published_at=datetime.now(),
            created_by=user.id,
        )
        db.add(notice)
        db.flush()
        creator = db.get(SysUser, user.id)
        return notice_vo(
            notice,
            creator.real_name if creator is not None else user.username,
            created_at=None,  # MP/ORM 插入不回填 createdAt
        )


def update_notice(
    db: Session, user: LoginUser, notice_id: int, req: NoticeRequest
) -> dict:
    """编辑公告 / 切换置顶 / 下架(status=0) / 恢复(status=1)。"""
    values: dict = {}
    if req.title is not None:
        values["title"] = req.title.strip()
    if req.content is not None:
        values["content"] = req.content.strip()
    if req.pinned is not None:
        values["pinned"] = req.pinned
    if req.status is not None:
        values["status"] = req.status
    if not values:
        raise BizException.bad_request("没有需要修改的内容")

    with db.begin():
        notice = _require_owned(db, user.class_id, notice_id)
        # 第十七轮归属权：只能编辑自己发的公告（含置顶 / 下架 / 恢复）
        require_ownership(user.id, notice.created_by, what="公告")
        # 第十九轮审计：编辑 / 置顶 / 下架 / 恢复都落到这两个字段 ——
        # 「这条公告最后是谁改的、什么时候」。发布人（created_by）不变，
        # 所以「谁发的」和「谁最后动的」是两条独立可追的线。
        values["updated_by"] = user.id
        values["updated_at"] = datetime.now()
        # 恢复发布时补发布时间，保证排序稳定
        if req.status == 1 and notice.published_at is None:
            values["published_at"] = datetime.now()
        for key, value in values.items():
            setattr(notice, key, value)
        names = _creator_names(db, [notice])
        return notice_vo(notice, names.get(notice.created_by), updated_by_name=names.get(notice.updated_by))


def delete_notice(db: Session, user: LoginUser, notice_id: int) -> None:
    """彻底删除：必须先下架（软删除可恢复），已发布的直接删会被拒绝。"""
    with db.begin():
        notice = _require_owned(db, user.class_id, notice_id)
        require_ownership(user.id, notice.created_by, what="公告")
        if notice.status == 1:
            raise BizException.bad_request("公告仍处于发布状态，请先下架再彻底删除")
        db.delete(notice)


def pinned_notices(db: Session, class_id: int, limit: int = 3) -> list[dict]:
    """仪表盘置顶公告（对应 Java SummaryVO.pinnedNotices）：已发布且置顶，取最近几条。"""
    rows = list(
        db.scalars(
            select(SysNotice)
            .where(
                SysNotice.class_id == class_id,
                SysNotice.status == 1,
                SysNotice.pinned == 1,
            )
            .order_by(SysNotice.published_at.desc(), SysNotice.id.desc())
            .limit(limit)
        )
    )
    names = _creator_names(db, rows)
    return [notice_vo(r, names.get(r.created_by), updated_by_name=names.get(r.updated_by)) for r in rows]
