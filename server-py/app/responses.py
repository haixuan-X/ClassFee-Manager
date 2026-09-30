"""统一响应体：{ code, message, data }（与 Java R.java 逐一相同）。

用 simplejson(use_decimal=True) 渲染，保证 Decimal 保留小数位（2343.50 而非 2343.5），
对齐 Jackson 序列化 BigDecimal 的输出。
"""
from __future__ import annotations

from typing import Any

import simplejson
from fastapi.responses import JSONResponse


class RJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return simplejson.dumps(
            content, ensure_ascii=False, use_decimal=True, separators=(",", ":")
        ).encode("utf-8")


def ok(data: Any = None) -> RJSONResponse:
    return RJSONResponse({"code": 200, "message": "ok", "data": data}, status_code=200)


def fail(code: int, message: str, data: Any = None, status: int | None = None) -> RJSONResponse:
    """status 缺省 = code；BizException.biz 为 status=200 + 业务码（1002/1003）。"""
    return RJSONResponse(
        {"code": code, "message": message, "data": data},
        status_code=status if status is not None else code,
    )
