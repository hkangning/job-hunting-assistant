"""pytest 公共 fixture：独立测试库隔离 + 鉴权账号（测试计划 §1.1）。

隔离方式为**模块级环境变量**：在导入任何 `app.*` 之前，把 `DATABASE_URL` 指向**独立的测试库**
（MySQL `job_hunter_test`，与开发库 `job_hunter` 物理隔离）——`app/config.py` 的 `Settings`
在模块导入时即读取环境变量，晚一行就固定成开发库。因此 `app.database` 的 `engine` /
`SessionLocal` 整场指向测试库，用例可直接引用，无需替换全局对象。

连接串**从 `backend/.env` 的 `DATABASE_URL` 派生**（只换库名、凭据沿用）：密码是环境相关的、
不入库——写死在这里既会泄露，也会与 `.env` 脱节（换密码要改两处）。

步骤 5（账号与鉴权）后**全部业务接口需 Token**，故取账号的入口分四类：

- `client`——出厂即带默认账号的鉴权头，存量业务用例据此免传 `headers`；
- `anon_client`——清掉鉴权头，验证未登录拦截（TC-58）；
- `make_account`——再注册账号，跨账号隔离用例拿第二个（TC-59）；
- `account_id`——服务层用例的账号归属（不经 HTTP）。
"""

import os
import re
import time
from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"

# 逐例清空时**保留**的表：题库种子内容固定（585 题），清掉再重导纯属浪费
_PRESERVED_TABLES = frozenset({"question"})


def _derive_test_database_url() -> str:
    """从 backend/.env 的 DATABASE_URL 派生测试库连接串：只换库名，凭据沿用。"""
    content = _ENV_FILE.read_text(encoding="utf-8") if _ENV_FILE.exists() else ""
    match = re.search(r"^DATABASE_URL=(.+)$", content, re.MULTILINE)
    if match is None:
        raise RuntimeError(
            f"{_ENV_FILE} 中缺少 DATABASE_URL——测试跑在 MySQL 上，"
            "请先按《数据库设计文档》§7 建库并在 .env 配好连接串"
        )
    url = make_url(match.group(1).strip())
    if url.database != "job_hunter":
        raise RuntimeError(f"开发库名应为 job_hunter，实际为 {url.database}——测试库由它派生")
    return url.set(database="job_hunter_test").render_as_string(hide_password=False)


os.environ["DATABASE_URL"] = _derive_test_database_url()

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.auth import RegisterRequest  # noqa: E402
from app.clients.llm_client import LLMClient, get_llm_client  # noqa: E402
from app.services import auth_service  # noqa: E402

API = "/api/v1"

# 测试账号默认口令（满足 ≥6 位；需改密的用例自行传新口令）
PASSWORD = "test123456"

Account = dict[str, object]

# 题库种子是否已导入（会话级）：见 client fixture 里的说明
_seed_loaded = False


def _reset_database() -> None:
    """清空全部业务表的数据（保留表结构与题库种子），保证用例之间互不干扰。

    换 MySQL 后不再逐例 `DROP` + `CREATE`：MySQL 的 DDL 是重量级操作（隐式提交 + 重建表空间），
    17 张表 × 150+ 用例的代价远超收益。改为 TRUNCATE 清数据——隔离效果相同，且会重置
    AUTO_INCREMENT（id 从 1 开始，对计数断言友好）。

    `question` 表**不清**（题库种子内容固定）；`config` 表中 `user_id = 0` 的系统级行同样保留
    （建表时插入的初始行，清掉会让后续用例缺系统配置），只清账号级行。
    """
    Base.metadata.create_all(bind=engine)  # 幂等：首次调用即建表，之后跳过
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))  # TRUNCATE 不能用于被外键引用的表
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in _PRESERVED_TABLES:
                continue
            if table.name == "config":
                conn.execute(text("DELETE FROM config WHERE user_id != 0"))
                continue
            conn.execute(text(f"TRUNCATE TABLE `{table.name}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


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
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    """API 集成测试客户端：清库 → 走真实启动路径（lifespan 建表 + 导种子）→ 注册默认账号。

    Token 直接写进客户端默认请求头，因此**存量业务用例无需逐个传 `headers`**；
    账号信息用 `account` fixture 取得。要验证未登录行为请改用 `anon_client`。
    """
    global _seed_loaded

    _reset_database()
    if _seed_loaded:
        # 题库已在会话首个用例导入、并被 _reset_database 保留在库里，跳过其后的重复导入：
        # 585 题的 upsert 每例跑一遍是整套测试最大的一笔开销（换 MySQL 后还要叠加网络往返）。
        # 断言题库内容的用例（如 test_seed_questions_*）读的是库中已有的种子，不受影响。
        monkeypatch.setattr("app.database._load_seed_questions", lambda db: 0)

    with TestClient(app, raise_server_exceptions=False) as c:
        _seed_loaded = True
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


# ---------- LLM 对话替身（步骤 10，测试计划 §1.3） ----------


class FakeLLMClient(LLMClient):
    """LLM 对话出口的内存替身：不触网，按预设吐块 / 返回 dict（台账 #39）。

    步骤 11 起的 SSE 与四条 AI 链路（JD / 陪练 / 面试 / 面经）都经 `get_llm_client` 出网，
    统一用本替身挡在网外，用例据此断言落库内容。

    `stream_chat` 写成生成器函数：调用时**不**抛 `error`，迭代到第一次 `next` 才抛——与
    生产实现（`OpenAICompatibleClient.stream_chat` 同为生成器）行为一致。
    """

    def __init__(self, chunks: list[str] | None = None, json_result: dict | None = None) -> None:
        self.chunks = ["假", "回答"] if chunks is None else chunks
        self.json_result = {} if json_result is None else json_result
        self.error: Exception | None = None  # 非空则抛，模拟失败路径
        self.delay = 0.0  # 每块间隔，步骤 11 验 SSE 事件顺序用
        self.stream_calls: list[tuple] = []  # 记录 (config, messages, tools)
        self.json_calls: list[tuple] = []  # 记录 (config, messages)

    def stream_chat(self, config, messages, tools=None):
        self.stream_calls.append((config, messages, tools))
        if self.error is not None:
            raise self.error
        for chunk in self.chunks:
            if self.delay:
                time.sleep(self.delay)
            yield chunk

    def chat_json(self, config, messages) -> dict:
        self.json_calls.append((config, messages))
        if self.error is not None:
            raise self.error
        return dict(self.json_result)


@pytest.fixture()
def fake_llm_client() -> Generator[FakeLLMClient, None, None]:
    """把 LLM 对话出口换成替身（测试计划 §1.3），用例结束后恢复原实现。

    `dependency_overrides` 是 app 级全局字典，**必须清理**——漏掉会静默污染其后所有用例。
    """
    fake = FakeLLMClient()
    app.dependency_overrides[get_llm_client] = lambda: fake
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_llm_client, None)


def pytest_sessionfinish(session, exitstatus) -> None:
    """会话收尾：释放连接池。

    换 MySQL 后不再有临时目录要清理；但仍要 dispose——否则连接悬着直到服务端 `wait_timeout`，
    反复跑测试会攒下一批只读空闲连接。
    """
    engine.dispose()
