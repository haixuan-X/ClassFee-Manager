"""业务异常与全局异常处理：错误码/文案与 Java GlobalExceptionHandler 逐一相同。"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .responses import fail

log = logging.getLogger("classfee")


class BizException(Exception):
    """status=HTTP 状态码，code=响应体业务码（BizException.of 时两者相同）。"""

    def __init__(self, status: int, code: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    @classmethod
    def of(cls, status: int, message: str) -> "BizException":
        return cls(status, status, message)

    @classmethod
    def bad_request(cls, message: str) -> "BizException":
        return cls.of(400, message)

    @classmethod
    def unauthorized(cls, message: str) -> "BizException":
        return cls.of(401, message)

    @classmethod
    def forbidden(cls, message: str) -> "BizException":
        return cls.of(403, message)

    @classmethod
    def biz(cls, code: int, message: str) -> "BizException":
        """业务级错误：HTTP 200 + 业务码（如改密码 1002/1003），前端按 code 提示。"""
        return cls(200, code, message)


# PydanticCustomError 用该类型标记“字段级业务校验”（对应 Java @NotBlank 等 → 字段列表）
FIELD_CONSTRAINT = "field_constraint"


def _is_field_error(err: dict[str, Any]) -> bool:
    return err.get("type") == FIELD_CONSTRAINT


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BizException)
    async def _biz(request: Request, exc: BizException) -> JSONResponse:
        if exc.status >= 500:
            log.error("业务异常 code=%s", exc.code, exc_info=exc)
        return fail(exc.code, exc.message, None, status=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        if not errors:
            return fail(400, "参数校验失败", [], status=400)

        loc = list(errors[0].get("loc") or ())
        # body 之外（query/path）：Spring MethodArgumentTypeMismatch → 请求参数不合法
        if not loc or loc[0] not in ("body", "query", "path", "header"):
            return fail(400, "请求参数不合法", None, status=400)
        if loc[0] in ("query", "path", "header"):
            return fail(400, "请求参数不合法", None, status=400)

        # body：缺整体 / JSON 解析失败 / 类型转换失败 → Spring HttpMessageNotReadable
        if len(loc) == 1 or not all(_is_field_error(e) for e in errors):
            return fail(400, "请求体格式不正确", None, status=400)

        # 字段级校验失败（@NotBlank/@Pattern/@Size...）→ 参数校验失败 + 逐字段列表
        items = [
            {"field": str(e["loc"][1]), "message": e.get("msg", "参数校验失败")}
            for e in errors
            if len(e.get("loc") or ()) >= 2
        ]
        return fail(400, "参数校验失败", items, status=400)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return fail(404, "接口不存在", None, status=404)
        detail = exc.detail if isinstance(exc.detail, str) else "接口不存在"
        return fail(exc.status_code, detail, None, status=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("系统异常 %s %s", request.method, request.url.path, exc_info=exc)
        return fail(500, "系统繁忙，请稍后重试", None, status=500)
