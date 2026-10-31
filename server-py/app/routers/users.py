"""账号管理接口（第七轮：老师自助建班；运营角色 ADMIN/TEACHER 可访问）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..responses import ok
from ..schemas import UserBatchRequest, UserCreateRequest, UserUpdateRequest
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


@router.post("/batch", summary="批量停用 / 启用 / 删除 / 重置密码")
def batch_users(
    req: UserBatchRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量操作勾选的成员（第四十四轮）。

    规则与单条完全同口径：目标须在**我能管的班**里、不能动自己、
    操作者等级须**严格高于**目标、删除只对**零引用**账号生效。

    「能做就做，做不了的跳过并说明」：不会因为一条删不掉就整批不动
    （那在用户看来就是「点了没反应」），回执里逐条给出跳过原因。
    """
    return ok(
        user_service.batch_users(
            db,
            user,
            action=req.action,
            user_ids=req.userIds,
            password=req.password,
        )
    )


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
