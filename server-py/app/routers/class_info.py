"""班级信息接口：查看全员可读，编辑仅运营角色（M4 新增）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
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


@router.put("")
def update_class_info(
    req: ClassInfoRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(class_service.update_class_info(db, user, req))
