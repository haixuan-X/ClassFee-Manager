"""收费批次接口：全部仅管理员（对应 Java BatchController）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..responses import ok
from ..schemas import BatchPayRequest, BatchRequest
from ..security import LoginUser, get_current_user
from ..services import batch_service

router = APIRouter(prefix="/api/batches", tags=["batches"])


@router.get("")
def list_batches(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(batch_service.list_batches(db, user))


@router.post("")
def create_batch(
    req: BatchRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(batch_service.create_batch(db, user, req))


@router.get("/{batch_id}/payments")
def batch_detail(
    batch_id: int,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(batch_service.detail(db, user, batch_id))


@router.post("/{batch_id}/pay")
def pay(
    batch_id: int,
    req: BatchPayRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batch_service.pay(db, user, batch_id, req)
    return ok()


@router.post("/{batch_id}/close")
def close_batch(
    batch_id: int,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batch_service.close(db, user, batch_id)
    return ok()


@router.delete("/{batch_id}")
def delete_batch(
    batch_id: int,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batch_service.delete_batch(db, user, batch_id)
    return ok()
