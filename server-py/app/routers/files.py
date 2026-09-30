"""小票图片上传与查看（第八轮新增；Java 原版只有 fee_record.receipt_url 字段、未实现接口）。

- POST /api/files           multipart 上传（运营角色，中间件 _STAFF_ROUTES 拦截）
- GET  /api/files/{path}    登录即可查看，且必须被本班流水引用（越权/孤儿路径 404）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from ..db import get_db
from ..errors import BizException
from ..models import FeeRecord
from ..responses import ok
from ..security import LoginUser, get_current_user
from ..services import file_service

router = APIRouter(prefix="/api/files", tags=["files"])

# multipart 解析前的 Content-Length 预检，避免超大请求体先落盘再被拒；
# 预留 64KB 给 boundary / filename 等开销
_MAX_POST_BYTES = file_service.MAX_RECEIPT_BYTES + 64 * 1024


@router.post("")
async def upload_receipt(
    request: Request,
    # 登录要求由中间件保证（运营角色在 _STAFF_ROUTES 拦截）；这里保留依赖，
    # 避免端点在这层配置变动后变成匿名可写
    user: LoginUser = Depends(get_current_user),
):
    length = request.headers.get("content-length")
    if length is not None and length.isdigit() and int(length) > _MAX_POST_BYTES:
        raise BizException.bad_request("图片大小不能超过 5MB")

    form = await request.form()
    item = form.get("file")
    if not isinstance(item, StarletteUploadFile):
        raise BizException.bad_request("请选择要上传的图片")
    # 多读 1 字节：让超限文件由 save_receipt 统一走 400 文案
    data = item.file.read(file_service.MAX_RECEIPT_BYTES + 1)
    return ok({"path": file_service.save_receipt(data)})


@router.get("/{file_path:path}")
def get_receipt(
    file_path: str,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    resolved = file_service.resolve_receipt(file_path)
    if resolved is None:
        raise BizException.of(404, "小票不存在或已被删除")

    # 班级归属：只有引用该文件的流水属于本班才放行（跨班/孤儿路径一律 404）
    owned = db.scalar(
        select(FeeRecord.id)
        .where(FeeRecord.receipt_url == file_path, FeeRecord.class_id == user.class_id)
        .limit(1)
    )
    if owned is None:
        raise BizException.of(404, "小票不存在或已被删除")

    target, media = resolved
    return FileResponse(
        target,
        media_type=media,
        headers={
            "Content-Disposition": f'inline; filename="{target.name}"',
            "Cache-Control": "private, max-age=86400",
        },
    )
