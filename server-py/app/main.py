"""FastAPI 应用装配：中间件（CORS → 鉴权）→ 异常处理 → 路由 → 启动初始化。

运行：uvicorn app.main:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

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
    dashboard,
    files,
    members,
    notices,
    records,
    users,
)
from .security import install_auth_middleware
from .seed import bootstrap

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    ping_db()      # 数据库连接重试（适配 compose 慢启动）
    bootstrap()    # schema.sql 幂等执行 + 种子数据（同 Java spring.sql.init + DataInitializer）
    yield


app = FastAPI(
    title="classfee-server",
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
    notices,
    class_info,
):
    app.include_router(_router.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
