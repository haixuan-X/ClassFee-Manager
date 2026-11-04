"""FastAPI 应用装配：中间件（CORS → 鉴权）→ 异常处理 → 路由 → 启动初始化。

运行：uvicorn app.main:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import logging
import logging.handlers
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import ping_db
from .errors import install_exception_handlers
from .responses import RJSONResponse
from .routers import (
    auth,
    batches,
    categories,
    class_info,
    college,
    dashboard,
    files,
    members,
    meta,
    records,
    students,
    tasks,
    users,
)
from .security import install_auth_middleware
from .seed import bootstrap
from .version import VERSION

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

# ---- 运行日志：控制台 + log/backend/backend.log（5MB×6 份轮转）----
#
# 落盘位置跟着**仓库根**走（<root>/log/backend/），与启动时的 cwd 无关；
# 服务器直跑 / PyCharm 直接 Run / docker 都一样。只读文件系统（只读根容器）
# 时只告警、不阻断启动。
_LOG_DIR = Path(
    os.environ.get("CLASSFEE_LOG_DIR", str(Path(__file__).resolve().parents[2] / "log" / "backend"))
)
try:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    _file_handler = logging.handlers.RotatingFileHandler(
        _LOG_DIR / "backend.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    _file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    logging.getLogger().addHandler(_file_handler)
    # uvicorn 自带 handler 且（视版本）可能向根传播——两头都挂会让每条打两遍；
    # 这里统一：三个 uvicorn logger 各挂文件 handler 且**不再向根传播**，
    # 其余（classfee 等）走根 logger 的同一个文件 handler
    for _name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        _uv = logging.getLogger(_name)
        _uv.addHandler(_file_handler)
        _uv.propagate = False
except OSError as exc:
    logging.getLogger("classfee").warning("cannot write file log in %s: %s", _LOG_DIR, exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ping_db()      # 数据库连接重试（适配 compose 慢启动）
    bootstrap()    # schema.sql 幂等执行 + 种子数据
    yield


app = FastAPI(
    title="classfee-server",
    # OpenAPI 文档页上直接显示版本，省得再多一个地方同步版本号
    version=VERSION,
    default_response_class=RJSONResponse,
    lifespan=lifespan,
)

# 顺序重要：鉴权中间件先于路由/请求体校验（= Spring 拦截器 preHandle 顺序）；
# CORS 最后添加 → 最外层，预检 OPTIONS 不会被鉴权拦截。
install_auth_middleware(app)
install_exception_handlers(app)

for _router in (
    auth,
    records,
    categories,
    members,
    users,
    batches,
    dashboard,
    files,
    class_info,
    students,
    tasks,
    college,
    meta,
):
    app.include_router(_router.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
