"""班级公告接口：全员可读，发布/编辑/下架/删除仅运营角色（M4；Java 存档只有 NoticeVO，无控制器）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..responses import ok
from ..schemas import NoticeRequest
from ..security import LoginUser, get_current_user
from ..services import notice_service

router = APIRouter(prefix="/api/notices", tags=["notices"])


@router.get("")
def list_notices(
    status: str | None = Query(None),
    keyword: str | None = Query(None),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """`status`：1=已发布（默认）｜0=已下架｜all=全部（仅运营角色，其余角色按已发布过滤）。"""
    return ok(notice_service.list_notices(db, user, status=status, keyword=keyword))


@router.post("")
def create_notice(
    req: NoticeRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(notice_service.create_notice(db, user, req))


@router.put("/{notice_id}")
def update_notice(
    notice_id: int,
    req: NoticeRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(notice_service.update_notice(db, user, notice_id, req))


@router.delete("/{notice_id}")
def delete_notice(
    notice_id: int,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notice_service.delete_notice(db, user, notice_id)
    return ok()
