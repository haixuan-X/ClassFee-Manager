"""小票图片存储：上传校验（大小 + 魔数嗅探）、安全读写（防目录穿越）。

约定（第八轮新增 /api/files 资源）：
- 只写磁盘不动库表结构，fee_record.receipt_url 记相对路径 receipts/<uuid>.<ext>
- 文件名服务端 uuid4 生成，不采信客户端文件名 → 天然免疫路径穿越
- 读取时再 resolve() 一层：解析结果必须仍在上传根目录内，否则按不存在处理
- 不依赖 libmagic：jpg/png/gif/webp 四种签名手工嗅探，拒绝伪装扩展名的非图片
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from ..config import settings
from ..errors import BizException

log = logging.getLogger("classfee")

MAX_RECEIPT_BYTES = 5 * 1024 * 1024  # 单张小票上限 5MB

_MEDIA_BY_EXT = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}


def sniff_image(data: bytes) -> str | None:
    """按内容（而非 Content-Type/扩展名）识别图片，返回扩展名或 None。"""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def upload_root() -> Path:
    root = Path(settings()["upload_dir"])
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def save_receipt(data: bytes) -> str:
    """保存小票图片，返回相对路径 receipts/<uuid>.<ext>；不合法则 400。"""
    if not data:
        raise BizException.bad_request("图片内容为空，请重新选择")
    if len(data) > MAX_RECEIPT_BYTES:
        raise BizException.bad_request("图片大小不能超过 5MB")
    ext = sniff_image(data)
    if ext is None:
        raise BizException.bad_request("仅支持 JPG / PNG / WebP / GIF 图片")

    rel = f"receipts/{uuid.uuid4().hex}.{ext}"
    target = upload_root() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return rel


def resolve_receipt(rel: str) -> tuple[Path, str] | None:
    """相对路径 → (绝对路径, media_type)；穿越/不存在/类型不识别统一返回 None。"""
    if not rel or "\\" in rel or ".." in rel.split("/"):
        return None
    root = upload_root()
    target = (root / rel).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    media = _MEDIA_BY_EXT.get(target.suffix.lower().lstrip("."))
    if media is None:
        return None
    return target, media


def delete_receipt(rel: str) -> None:
    """尽力删除（流水物理删除后回收磁盘）；失败只记日志不阻断主流程。"""
    resolved = resolve_receipt(rel)
    if resolved is None:
        return
    try:
        resolved[0].unlink()
    except OSError:
        log.warning("failed to remove receipt file: %s", rel)
