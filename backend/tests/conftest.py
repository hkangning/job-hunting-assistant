"""pytest 公共 fixture：独立测试库 + TestClient 与 AI mock 注入点（测试计划 1.1 / 1.3）。

测试数据库一律用 tmp_path 下的独立 SQLite 文件，不碰开发库 backend/app.db。
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app import database, models  # noqa: F401  导入模型以注册到 Base.metadata
from app.database import Base
from app.main import app


@pytest.fixture()
def test_engine(tmp_path, monkeypatch) -> Engine:
    """独立测试库引擎：建 tmp_path 下 SQLite 文件并替换全局 engine/SessionLocal。"""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    event.listen(engine, "connect", database._set_sqlite_pragma)  # 与开发库同样开启 WAL + 外键
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(
        database, "SessionLocal", sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    )
    return engine


@pytest.fixture()
def db_session(test_engine: Engine) -> Generator[Session, None, None]:
    """服务层单测会话：只建表不导种子，用例自造数据。"""
    Base.metadata.create_all(bind=test_engine)
    with database.SessionLocal() as session:
        yield session


@pytest.fixture()
def client(test_engine: Engine) -> Generator[TestClient, None, None]:
    """API 集成测试客户端：lifespan 走真实启动路径（测试库上建表 + 导种子）。"""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
