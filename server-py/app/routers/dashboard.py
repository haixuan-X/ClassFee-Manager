"""仪表盘统计接口（对应 Java DashboardController）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..responses import ok
from ..security import LoginUser, get_current_user
from ..services import dashboard_service

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(dashboard_service.summary(db, user))


@router.get("/trend")
def trend(
    months: int = Query(6),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(dashboard_service.trend(db, user, months))


@router.get("/category-pie")
def category_pie(
    months: int = Query(6),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(dashboard_service.category_pie(db, user, months))
