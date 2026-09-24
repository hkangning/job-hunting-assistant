"""pytest 公共 fixture：独立测试库隔离 + TestClient（测试计划 v1.4 §1.1）。

隔离方式为**模块级环境变量**：在导入任何 `app.*` 之前，把 `DATABASE_URL` 指向临时目录下的独立
SQLite 文件——`app/config.py` 的 `Settings` 在模块导入时即读取环境变量，晚一行就固定成开发库。
因此 `app.database` 的 `engine` / `SessionLocal` 整场指向测试库，用例可直接引用，无需替换全局对象。
"""

import os
import shutil
import tempfile
import time
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

# —— 测试库隔离：临时目录下的独立 SQLite 文件，不碰开发库（backend/app.db）——
_TEST_TMP_DIR = Path(tempfile.mkdtemp(prefix="jobpilot-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_TMP_DIR.as_posix()}/test.db"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


def _reset_database() -> None:
    """清空并重建全部表：保证用例之间互不干扰（否则前一个用例的数据会污染后一个的计数断言）。"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    """服务层单测会话：清库建表、**不导种子**，用例自造数据。"""
    _reset_database()
    with SessionLocal() as session:
        yield session


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    """API 集成测试客户端：清库后走真实启动路径（lifespan 建表 + 导种子）。"""
    _reset_database()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def pytest_sessionfinish(session, exitstatus) -> None:
    """会话收尾：先释放连接再删临时目录。

    Windows 下句柄释放有延迟（杀软扫描、文件系统回收），一次 rmtree 可能只删掉文件而留下
    空目录，故重试三次；仍失败则留给系统临时目录机制清理，不阻断测试结果。
    """
    engine.dispose()
    for _ in range(3):
        try:
            shutil.rmtree(_TEST_TMP_DIR)
            return
        except OSError:
            time.sleep(0.2)
    shutil.rmtree(_TEST_TMP_DIR, ignore_errors=True)
