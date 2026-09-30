"""认证接口（对应 Java AuthController）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import LoginRequest, PasswordRequest, ProfileUpdateRequest
from ..security import LoginUser, get_current_user
from ..responses import ok
from ..services import auth_service, user_service  # user_service: update_profile 在那边（与运营编辑共用字段逻辑）

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    return ok(auth_service.login(db, req))


@router.get("/me")
def me(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(auth_service.me(db, user))


@router.put("/password")
def change_password(
    req: PasswordRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    auth_service.change_password(db, user, req)
    return ok()


@router.get("/profile")
def read_profile(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """第十五轮：读取本人完整资料（`account_vo`，含学号 / 手机号 / 状态 / 时间戳）。

    为什么不用 `GET /api/users` 找自己那一行：那个接口**仅运营角色可读**，
    普通成员会拿到 403，页面就显示不出自己的学号（更糟的是若据此回填空值，
    用户一点保存就把学号清掉了）。本端点只认登录令牌里的 id，**结构上只能读自己**。
    """
    return ok(user_service.my_profile(db, user))


@router.put("/profile")
def update_profile(
    req: ProfileUpdateRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """第十五轮：本人自助修改个人信息（姓名 / 学号 / 手机号）。

    **全员可用（含普通成员）**，因此刻意**不进** `_STAFF_ROUTES`。
    改的是谁由登录令牌决定，请求体不接受 id —— 结构上无法改到别人的资料。
    角色、启用状态、登录名、班级不在本接口范围（分别走 /users/{id}、/auth/password）。
    """
    user_service.update_profile(db, user, req)
    return ok(auth_service.me(db, user))
