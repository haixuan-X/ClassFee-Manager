"""班级信息接口：查看全员可读，编辑仅运营角色（M4 新增）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ClsClass
from ..responses import ok
from ..schemas import ClassInfoRequest
from ..security import LoginUser, get_current_user
from ..services import class_service

router = APIRouter(prefix="/api/class", tags=["class"])


@router.get("")
def get_class_info(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(class_service.get_class_info(db, user))


@router.get("/choices")
def class_choices(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """所有**启用**的班（第三十二轮）。

    给「个人信息 → 我带的班」用：老师要能选**所有**班（不限于他已经能管的），
    否则「我带另一个班」这件事根本没法表达。

    ⚠ **只给运营角色以上**：普通同学不需要知道全校有哪些班。
    """
    from ..security import STAFF_ROLES

    if user.role not in STAFF_ROLES:
        return ok({"classes": []})
    rows = db.scalars(
        select(ClsClass).where(ClsClass.status == 1).order_by(ClsClass.id.asc())
    ).all()
    return ok(
        {
            "classes": [
                {"id": c.id, "className": c.class_name, "grade": c.grade or ""}
                for c in rows
            ]
        }
    )


@router.put("")
def update_class_info(
    req: ClassInfoRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(class_service.update_class_info(db, user, req))
