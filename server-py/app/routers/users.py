"""账号管理接口（第七轮：老师自助建班；运营角色 ADMIN/TEACHER 可访问）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..responses import ok
from ..schemas import UserCreateRequest, UserUpdateRequest
from ..security import LoginUser, get_current_user
from ..services import user_service

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("")
def list_users(
    keyword: str | None = Query(None),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(user_service.list_users(db, user, keyword=keyword))


@router.post("")
def create_user(
    req: UserCreateRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(user_service.create_user(db, user, req))


@router.put("/{user_id}")
def update_user(
    user_id: int,
    req: UserUpdateRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(user_service.update_user(db, user, user_id, req))


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除账号：仅零引用可删（有流水/缴费/公告/批次历史一律 400，引导改用停用）。"""
    user_service.delete_user(db, user, user_id)
    return ok()
