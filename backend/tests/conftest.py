"""pytest 公共 fixture：独立测试库隔离 + 鉴权账号（测试计划 v1.6 §1.1）。

隔离方式为**模块级环境变量**：在导入任何 `app.*` 之前，把 `DATABASE_URL` 指向临时目录下的独立
SQLite 文件——`app/config.py` 的 `Settings` 在模块导入时即读取环境变量，晚一行就固定成开发库。
因此 `app.database` 的 `engine` / `SessionLocal` 整场指向测试库，用例可直接引用，无需替换全局对象。

步骤 5（账号与鉴权）后**全部业务接口需 Token**，故取账号的入口分四类：

- `client`——出厂即带默认账号的鉴权头，存量业务用例据此免传 `headers`；
- `anon_client`——清掉鉴权头，验证未登录拦截（TC-58）；
- `make_account`——再注册账号，跨账号隔离用例拿第二个（TC-59）；
- `account_id`——服务层用例的账号归属（不经 HTTP）。
"""

import os
import shutil
import tempfile
import time
from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

# —— 测试库隔离：临时目录下的独立 SQLite 文件，不碰开发库（backend/app.db）——
_TEST_TMP_DIR = Path(tempfile.mkdtemp(prefix="jobpilot-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_TMP_DIR.as_posix()}/test.db"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.auth import RegisterRequest  # noqa: E402
from app.services import auth_service  # noqa: E402

API = "/api/v1"

# 测试账号默认口令（满足 ≥6 位；需改密的用例自行传新口令）
PASSWORD = "test123456"

Account = dict[str, object]


def _reset_database() -> None:
    """清空并重建全部表：保证用例之间互不干扰（否则前一个用例的数据会污染后一个的计数断言）。"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _register(client: TestClient, username: str, password: str = PASSWORD) -> Account:
    """经 HTTP 注册一个账号，返回 {id, username, token, headers, password}。"""
    resp = client.post(f"{API}/auth/register", json={"username": username, "password": password})
    assert resp.status_code == 200, f"测试账号注册失败：{resp.status_code} {resp.text}"
    data = resp.json()["data"]
    return {
        "id": data["user"]["id"],
        "username": data["user"]["username"],
        "token": data["token"],
        "headers": {"Authorization": f"Bearer {data['token']}"},
        "password": password,
    }


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    """服务层单测会话：清库建表、**不导种子**，用例自造数据。"""
    _reset_database()
    with SessionLocal() as session:
        yield session


@pytest.fixture()
def account_id(db_session: Session) -> int:
    """服务层用例的账号 id：不经 HTTP，直接用服务层注册一个临时账号。

    服务层方法自步骤 5 起一律要求 `user_id` 入参（系统设计 3.6），用例以本 fixture 取得归属。
    """
    data = auth_service.register(db_session, RegisterRequest(username="tester", password=PASSWORD))
    return data.user.id


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    """API 集成测试客户端：清库 → 走真实启动路径（lifespan 建表 + 导种子）→ 注册默认账号。

    Token 直接写进客户端默认请求头，因此**存量业务用例无需逐个传 `headers`**；
    账号信息用 `account` fixture 取得。要验证未登录行为请改用 `anon_client`。
    """
    _reset_database()
    with TestClient(app, raise_server_exceptions=False) as c:
        default = _register(c, "tester")
        c.auth_account = default  # 具名属性，供 account fixture 取用（与请求头同源）
        c.headers["Authorization"] = default["headers"]["Authorization"]
        yield c


@pytest.fixture()
def account(client: TestClient) -> Account:
    """默认账号（即 `client` 默认请求头所用的那个账号）。"""
    return client.auth_account


@pytest.fixture()
def anon_client(client: TestClient) -> TestClient:
    """匿名客户端：清掉默认鉴权头，用于验证未登录拦截（TC-58）。"""
    client.headers.pop("Authorization", None)
    return client


@pytest.fixture()
def make_account(client: TestClient) -> Callable[..., Account]:
    """账号工厂：再注册一个账号并返回其 Token 与请求头（TC-59 跨账号隔离用例取第二个账号）。"""

    def _make(username: str = "other", password: str = PASSWORD) -> Account:
        return _register(client, username, password)

    return _make


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
