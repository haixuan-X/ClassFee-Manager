"""仪表盘统计接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..responses import ok
from ..security import LoginUser, get_current_user, require_min_level
from ..services import dashboard_service, student_service

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


@router.get("/students", summary="学生情况总览")
def students(
    months: int = Query(12),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """仪表盘第二个总览的数据源。**仅院长（系统管理员）可见**。

    ## 为什么是院长而不是「班主任及以上」

    这是**管理级看板**：它给出的是全班注册状态分布与入校趋势这类
    汇总口径，不是某一个人的资料。班主任在「学生信息」里本来就能看到
    全部学生行（`canViewAll`），所以这道闸门**挡的不是数据泄露**，
    挡的是「谁拥有校级看板」这个身份——用户口径是院长的。

    ## 两条腿都要走

    - 后端：这里 `require_min_level` 硬拦（403）
    - 前端：**不渲染**切换器里的「学生情况总览」标签

    只做后端的话，班主任登录后能看到那个标签、点进去弹一句「无权」，
    那比看不到更糟；只做前端的话，手输接口照样能拿到数据。

    进闸之后，可见范围仍复用学生信息表的 `_visible_record_ids`，
    不因为「是院长」就绕过行级权限。
    """
    require_min_level(user, "DEAN", "学生情况总览")
    return ok(student_service.dashboard_stats(db, user, months=months))
