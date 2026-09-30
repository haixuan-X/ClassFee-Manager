"""收支流水接口：查询全员可读，记账/作废/删除/导出仅管理员（对应 Java RecordController）。"""
from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..responses import ok
from ..schemas import RecordRequest, check_paging
from ..security import LoginUser, get_current_user
from ..services import export_service, record_service

router = APIRouter(prefix="/api/records", tags=["records"])


@router.get("")
def list_records(
    page: int = Query(1),
    size: int = Query(20),
    type: str | None = Query(None),
    categoryId: int | None = Query(None),
    keyword: str | None = Query(None),
    status: str | None = Query(None),
    id: int | None = Query(None),
    start: str | None = Query(None),
    end: str | None = Query(None),
    channel: str | None = Query(None),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    check_paging(page, size)
    return ok(
        record_service.list_records(
            db,
            user,
            page=page,
            size=size,
            type_=type,
            category_id=categoryId,
            keyword=keyword,
            status=status,
            record_id=id,
            start=start,
            end=end,
            channel=channel,
        )
    )


@router.get("/export")
def export_records(
    type: str | None = Query(None),
    categoryId: int | None = Query(None),
    keyword: str | None = Query(None),
    status: str | None = Query(None),
    id: int | None = Query(None),
    start: str | None = Query(None),
    end: str | None = Query(None),
    channel: str | None = Query(None),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """账本筛选导出（xlsx，M4）：与列表同一套筛选条件，不受分页限制。

    注意路径顺序：本路由必须声明在 `/{record_id}` 之类动态段之前，避免被吞掉。
    """
    content = export_service.build_export_bytes(
        db,
        user,
        type_=type,
        category_id=categoryId,
        keyword=keyword,
        status=status,
        record_id=id,
        start=start,
        end=end,
        channel=channel,
    )
    filename = export_service.export_filename()
    quoted = urllib.parse.quote(filename)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            # RFC 5987：中文文件名用 filename* 传 UTF-8，filename 兜底 ASCII
            "Content-Disposition": f"attachment; filename=records.xlsx; filename*=UTF-8''{quoted}",
            "Content-Length": str(len(content)),
        },
    )


@router.post("")
def create_record(
    req: RecordRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(record_service.create_record(db, user, req))


@router.post("/{record_id}/void")
def void_record(
    record_id: int,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record_service.void_record(db, user, record_id)
    return ok()


@router.delete("/{record_id}")
def delete_record(
    record_id: int,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record_service.delete_record(db, user, record_id)
    return ok()
