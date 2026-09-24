"""FastAPI 应用入口：装配日志、生命周期钩子、中间件、异常处理与路由。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.exceptions import register_exception_handlers
from app.routers import applications, health

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动钩子：建库 + 种子导入（步骤 2，幂等）；定时任务注册见步骤 17。"""
    init_db()
    # TODO(步骤 17)：注册每日提醒定时任务
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(health.router, prefix=settings.api_prefix)
app.include_router(applications.router, prefix=settings.api_prefix)
