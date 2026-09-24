"""pytest 公共 fixture：独立测试库隔离 + TestClient（测试计划 v1.4 §1.1）。"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

# —— 测试库隔离：临时目录下的独立 SQLite 文件，不碰开发库（backend/app.db）——
# 必须在任何 app.* 导入之前执行：app/config.py 的 Settings 在模块导入时即读取环境变量，
# 一旦 app.config 先被导入，数据库地址就固定为开发库，改不动了。
_TEST_TMP_DIR = Path(tempfile.mkdtemp(prefix="jobpilot-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_TMP_DIR.as_posix()}/test.db"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402


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


def pytest_sessionfinish(session, exitstatus) -> None:
    """会话收尾：先释放连接再删临时目录（Windows 下未 dispose 会因句柄占用而删不掉）。"""
    engine.dispose()
    shutil.rmtree(_TEST_TMP_DIR, ignore_errors=True)
