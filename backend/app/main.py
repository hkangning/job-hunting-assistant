"""FastAPI 应用入口：装配日志、生命周期钩子、中间件、异常处理与路由。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.exceptions import register_exception_handlers
from app.routers import applications, auth, health, llm_providers, profile, settings as settings_router
from app.utils.security import AVATAR_DIR

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
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(profile.router, prefix=settings.api_prefix)
app.include_router(applications.router, prefix=settings.api_prefix)
app.include_router(llm_providers.router, prefix=settings.api_prefix)
app.include_router(settings_router.router, prefix=settings.api_prefix)

# 头像静态访问：库中存的 uploads/avatars/xxx.png 直接拼后端地址即可（系统设计 3.5，本机运行）
AVATAR_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=AVATAR_DIR.parent), name="uploads")
