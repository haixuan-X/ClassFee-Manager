"""认证与账号服务（对应 Java AuthService）。"""
from __future__ import annotations

import time
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..errors import BizException
from ..models import ClsClass, SysUser
from ..schemas import LoginRequest, PasswordRequest
from ..security import LoginUser, create_token, verify_password
from ..serializers import user_vo


def _class_name(db: Session, class_id: int | None) -> str | None:
    if class_id is None:
        return None
    row = db.get(ClsClass, class_id)
    return row.class_name if row is not None else None


def login(db: Session, req: LoginRequest) -> dict:
    with db.begin():
        user = db.scalars(
            select(SysUser).where(SysUser.username == req.username).limit(1)
        ).first()

        # 用户名不存在与密码错误返回同一提示，避免账号枚举
        if user is None or not verify_password(req.password or "", user.password):
            raise BizException(401, 40101, "账号或密码错误")
        if user.status != 1:
            raise BizException.forbidden("账号已被停用，请联系班长")

        db.execute(
            update(SysUser)
            .where(SysUser.id == user.id)
            .values(last_login_at=datetime.now())
        )

        login_user = LoginUser(
            id=user.id, username=user.username, role=user.role, class_id=user.class_id
        )
        return {
            "token": create_token(login_user),
            "user": user_vo(user, _class_name(db, user.class_id)),
        }


def me(db: Session, current: LoginUser) -> dict:
    with db.begin():
        user = db.get(SysUser, current.id)
        if user is None:
            raise BizException.unauthorized("账号不存在或已被删除")
        return user_vo(user, _class_name(db, user.class_id))


def change_password(db: Session, current: LoginUser, req: PasswordRequest) -> None:
    with db.begin():
        user = db.get(SysUser, current.id)
        if user is None:
            raise BizException.unauthorized("账号不存在或已被删除")
        if not verify_password(req.oldPassword or "", user.password):
            raise BizException.biz(1002, "原密码错误")
        if req.oldPassword == req.newPassword:
            raise BizException.biz(1003, "新密码不能与原密码相同")

        from ..security import hash_password

        db.execute(
            update(SysUser)
            .where(SysUser.id == user.id)
            .values(password=hash_password(req.newPassword or ""))
        )
