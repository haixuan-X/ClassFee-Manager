"""成员缴费接口：成员列表 + 指定批次的缴费状态，仅管理员（对应 Java MemberController）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..responses import ok
from ..schemas import check_pay_status
from ..security import LoginUser, get_current_user
from ..services import batch_service

router = APIRouter(prefix="/api/members", tags=["members"])


@router.get("")
def list_members(
    keyword: str | None = Query(None),
    payStatus: str | None = Query(None),
    batchId: int | None = Query(None),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_pay_status(payStatus)
    return ok(
        batch_service.members(
            db, user, keyword=keyword, pay_status=payStatus, batch_id=batchId
        )
    )
