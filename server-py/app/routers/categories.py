"""收支类别字典接口：读全员，写仅管理员（对应 Java CategoryController）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..responses import ok
from ..schemas import CategoryRequest
from ..security import LoginUser, get_current_user
from ..services import category_service

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("")
def list_categories(
    kind: str | None = Query(None),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(category_service.list_categories(db, user, kind))


@router.post("")
def create_category(
    req: CategoryRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    category_service.create_category(db, user, req)
    return ok()


@router.put("/{category_id}")
def update_category(
    category_id: int,
    req: CategoryRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    category_service.update_category(db, user, category_id, req)
    return ok()


@router.delete("/{category_id}")
def delete_category(
    category_id: int,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    category_service.delete_category(db, user, category_id)
    return ok()
