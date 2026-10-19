"""版本接口：`GET /api/version` —— 公开端点，报告当前运行的是哪一版。

**不进 `_STAFF_ROUTES`、进 `PUBLIC_ROUTES`**：登录页要在**还没登录时**就显示版本号
（出问题时第一眼看到的就是「我跑的是哪一版」），所以这个端点免鉴权。
它不含任何业务数据，只回常量，无泄露风险。
"""
from __future__ import annotations

from fastapi import APIRouter

from ..responses import ok
from ..version import version_info

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/version")
def get_version():
    """版本信息。免鉴权（登录页要用）。"""
    return ok(version_info())