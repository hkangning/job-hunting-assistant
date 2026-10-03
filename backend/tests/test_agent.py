"""全局 Agent（FR-011）：意图路由、写操作确认卡片、查询回显与会话落库的用例——测试计划 TC-16~19、TC-138~TC-141。

后端 `POST /stream/agent-chat`、两个查询端点（2026-10-01）与执行端点 `POST /agent/tools/{tool}/execute`
（步骤 19，HTTP 全链路用例见台账 #97）均已落地（接口文档 v1.38 / v1.40 §3.11）。
替身说明（[前端待改问题](../../docs/07-工作日志/前端待改问题.md) #94 ②）：`stream_tool_chat` **非抽象、
默认降级为纯文本流**——不覆写也能实例化，但验证 `tool_call` 事件序列的用例必须自行覆写；本文件用
`AgentFake` 按序产出 `TextDelta` / `ToolCallDelta`（不触网）。
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.clients.llm_client import (
    LLMError,
    TextDelta,
    ToolCallDelta,
    get_llm_client,
    resolve_config,
)
from app.database import SessionLocal
from app.exceptions import BizException, ErrorCode
from app.main import app
from app.models import AgentConversation, AgentMessage, Application, LlmProviderConfig
from app.services import agent_service
from app.utils.security import encrypt_text
from app.utils.sse import SSE, _paced

STREAM_API = "/api/v1/stream/agent-chat"
CONV_API = "/api/v1/agent/conversations"
APP_API = "/api/v1/applications"


# ---------------- 替身与辅助 ----------------


class AgentFake:
    """Agent 链路替身：按序产出文本 / 工具调用，并记录各出口的入参供断言。

    - `stream_tool_chat` 产出 `tool_items`（TextDelta / ToolCallDelta 混合）——工具轮；
    - `stream_chat` 产出 `chunks`——查询结果的总结轮（`tools` 恒为 None，防循环）；
    - `chat_json` 返回 `json_result`——意图分类（规则未命中时）；
    - `error` 在文本类出口**产出完后**抛出（可构造「流中途失败」）；分类出口为**立即抛**。
    """

    def __init__(self) -> None:
        self.tool_items: list = []
        self.chunks: list[str] = ["（总结）"]
        self.json_result: dict = {}
        self.error: Exception | None = None
        self.tool_calls: list[tuple] = []  # (config, messages, tools)
        self.chat_calls: list[tuple] = []
        self.json_calls: list[tuple] = []

    def stream_tool_chat(self, config, messages, tools=None):
        self.tool_calls.append((config, messages, tools))
        yield from self.tool_items
        if self.error is not None:
            raise self.error

    def stream_chat(self, config, messages, tools=None):
        self.chat_calls.append((config, messages, tools))
        yield from self.chunks
        if self.error is not None:
            raise self.error

    def chat_json(self, config, messages) -> dict:
        self.json_calls.append((config, messages))
        if self.error is not None:
            raise self.error
        return dict(self.json_result)


@pytest.fixture()
def agent_llm(fake_llm_client) -> AgentFake:
    """把依赖注入换成 Agent 替身；override 的摘除由 `fake_llm_client` 的 teardown 负责。"""
    fake = AgentFake()
    app.dependency_overrides[get_llm_client] = lambda: fake
    return fake


def _configure_provider(db: Session, user_id: int) -> None:
    """服务层用例的账号需要生效的供应商行（`.env` 无 LLM 兜底配置，否则 10012）。"""
    db.add(
        LlmProviderConfig(
            user_id=user_id,
            provider="deepseek",
            api_key=encrypt_text("sk-test"),
            model="test-model",
            is_active=1,
        )
    )
    db.commit()


def _sse_events(body: str) -> list[tuple[str, dict]]:
    """解析响应体里的 SSE 事件序列。"""
    events = []
    for block in body.split("\n\n"):
        if not block.strip().startswith("event: "):
            continue
        lines = block.strip().split("\n")
        events.append((lines[0][len("event: ") :], json.loads(lines[1][len("data: ") :])))
    return events


def _done(events: list[tuple[str, dict]]) -> dict:
    for name, data in events:
        if name == "done":
            return data
    raise AssertionError("事件流里没有 done")


def _error(events: list[tuple[str, dict]]) -> dict:
    for name, data in events:
        if name == "error":
            return data
    raise AssertionError("事件流里没有 error")


def _tool_call(events: list[tuple[str, dict]]) -> dict:
    for name, data in events:
        if name == "tool_call":
            return data
    raise AssertionError("事件流里没有 tool_call")


def _delta_text(events: list[tuple[str, dict]]) -> str:
    """非结构化 delta 的文本拼接（result 等结构化段不计入）。"""
    return "".join(d["text"] for n, d in events if n == "delta" and not d.get("section"))


def _result_blocks(events: list[tuple[str, dict]]) -> list[dict]:
    return [json.loads(d["text"]) for n, d in events if n == "delta" and d.get("section") == "result"]


def _create_application(client: TestClient, company: str, position: str = "后端开发") -> int:
    resp = client.post(APP_API, json={"company": company, "position": position, "jd_text": "岗位 JD 原文"})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["id"]


# ---------------- TC-16 意图路由 ----------------


class TestIntentRoute:
    """TC-16：四类意图路由——规则快筛优先（零分类调用）、未命中走模型分类、非法值归 CHAT。"""

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("记一笔投递：字节跳动", "APPLICATION"),
            ("我投了腾讯的后端", "APPLICATION"),
            ("来几道八股题", "PRACTICE"),
            ("帮我练一练错题", "PRACTICE"),
            ("看看我的面经", "EXPERIENCE"),
            ("面试问了什么", "EXPERIENCE"),
        ],
    )
    def test_rules_hit_without_classify(self, db_session: Session, account_id: int, message, expected):
        _configure_provider(db_session, account_id)
        fake = AgentFake()

        intent = agent_service.route_intent(fake, resolve_config(db_session, account_id), message)

        assert intent == expected
        assert fake.json_calls == []  # 规则命中不调分类模型（零 token）

    def test_classify_fallback_and_invalid_to_chat(self, db_session: Session, account_id: int):
        """规则未命中 → `chat_json` 分类；结果大小写归一、非法值 / 缺失一律归 CHAT。"""
        _configure_provider(db_session, account_id)
        config = resolve_config(db_session, account_id)
        fake = AgentFake()

        fake.json_result = {"intent": "practice"}
        assert agent_service.route_intent(fake, config, "今天想弄点题做做") == "PRACTICE"
        assert len(fake.json_calls) == 1

        for bad in ({"intent": "banana"}, {}):
            fake.json_result = bad
            assert agent_service.route_intent(fake, config, "随便说点啥") == "CHAT"

    def test_classify_failure_not_swallowed(self, db_session: Session, account_id: int):
        """分类调用失败原样抛出（不静默降级）——错误与提示由流式层统一处理。"""
        _configure_provider(db_session, account_id)
        fake = AgentFake()
        fake.error = LLMError(ErrorCode.LLM_CALL_FAILED, "上游故障")

        with pytest.raises(LLMError):
            agent_service.route_intent(fake, resolve_config(db_session, account_id), "随便说点啥")


# ---------------- TC-17 / TC-138 写操作确认卡片 ----------------


class TestWriteCard:
    """TC-17 / TC-138：写操作出确认卡片（不落库）、参数不全降级为普通追问（不报错）。"""

    def test_card_with_complete_args_not_persisted(self, client: TestClient, account, llm_configured, agent_llm):
        agent_llm.tool_items = [
            TextDelta("好的，帮你记一条投递。"),
            ToolCallDelta(
                "create_application",
                json.dumps({"company": "字节跳动", "position": "后端开发"}, ensure_ascii=False),
            ),
        ]
        resp = client.post(STREAM_API, json={"message": "帮我记一笔投递：字节跳动 后端开发"})
        assert resp.status_code == 200
        events = _sse_events(resp.text)

        assert [n for n, _ in events] == ["start", "delta", "tool_call", "done"]
        assert _delta_text(events) == "好的，帮你记一条投递。"
        card = _tool_call(events)
        assert card["tool_name"] == "create_application"
        assert card["args"] == {"company": "字节跳动", "position": "后端开发"}  # 服务端补全后的完整参数

        # 写操作不落库：业务表零新增；消息落 USER + ASSISTANT，后者带工具名与参数元数据
        assert client.get(APP_API).json()["data"]["total"] == 0
        conv_id = _done(events)["conversation_id"]
        msgs = client.get(f"{CONV_API}/{conv_id}/messages").json()["data"]
        assert [m["role"] for m in msgs] == ["USER", "ASSISTANT"]
        assert msgs[1]["tool_name"] == "create_application"

    def test_chat_intent_streams_text_without_tools(self, client: TestClient, account, llm_configured, agent_llm):
        """闲聊：规则未命中走过一次分类 → `CHAT` 不下发工具、纯文本回复。"""
        agent_llm.tool_items = [TextDelta("你好！可以说「记一笔投递」让我试试。")]
        events = _sse_events(client.post(STREAM_API, json={"message": "你好呀"}).text)

        assert [n for n, _ in events] == ["start", "delta", "done"]
        assert len(agent_llm.json_calls) == 1  # 未命中 → 分类一次
        _, _, tools = agent_llm.tool_calls[0]
        assert tools == []  # CHAT 不带工具

    def test_missing_field_follows_up_as_plain_delta(self, client: TestClient, account, llm_configured, agent_llm):
        """参数不全 → 追问文案走普通 delta、无 tool_call、done 正常（不报错）。"""
        agent_llm.tool_items = [
            ToolCallDelta("create_application", json.dumps({"company": "字节跳动"}, ensure_ascii=False))
        ]
        events = _sse_events(client.post(STREAM_API, json={"message": "帮我记一笔投递：字节跳动"}).text)

        assert all(n != "tool_call" for n, _ in events)
        assert "岗位名称" in _delta_text(events)
        assert _done(events)
        assert client.get(APP_API).json()["data"]["total"] == 0

    def test_status_update_matched_by_company(self, client: TestClient, account, llm_configured, agent_llm):
        """只给公司名 → 服务端模糊匹配本账号最近一条投递、补全 `application_id`。"""
        app_id = _create_application(client, "浩鲸科技", "Java 开发")
        agent_llm.tool_items = [
            ToolCallDelta(
                "update_application_status",
                json.dumps({"company": "浩鲸", "status": "INTERVIEW"}, ensure_ascii=False),
            )
        ]
        events = _sse_events(client.post(STREAM_API, json={"message": "帮我更新投递状态：浩鲸科技到面试中"}).text)

        card = _tool_call(events)
        assert card["args"]["application_id"] == app_id
        assert card["args"]["status"] == "INTERVIEW"
        # 未确认不落库：状态仍是 APPLIED
        assert client.get(f"{APP_API}/{app_id}").json()["data"]["status"] == "APPLIED"

    def test_status_update_company_miss_follows_up(self, client: TestClient, account, llm_configured, agent_llm):
        agent_llm.tool_items = [
            ToolCallDelta(
                "update_application_status",
                json.dumps({"company": "查无此司", "status": "INTERVIEW"}, ensure_ascii=False),
            )
        ]
        events = _sse_events(client.post(STREAM_API, json={"message": "帮我更新投递状态：查无此司到面试中"}).text)

        assert all(n != "tool_call" for n, _ in events)
        assert "没找到" in _delta_text(events)

    def test_closed_without_reason_follows_up(self, client: TestClient, account, llm_configured, agent_llm):
        """转 CLOSED 缺 `close_reason` → 先追问原因（否则确认卡片点下去才报错，体验更差）。"""
        app_id = _create_application(client, "腾讯")
        agent_llm.tool_items = [
            ToolCallDelta(
                "update_application_status",
                json.dumps({"application_id": app_id, "status": "CLOSED"}, ensure_ascii=False),
            )
        ]
        events = _sse_events(client.post(STREAM_API, json={"message": "帮我更新投递状态：腾讯已结束"}).text)

        assert all(n != "tool_call" for n, _ in events)
        assert "原因" in _delta_text(events)

    def test_unknown_tool_and_bad_args_follow_up(self, client: TestClient, account, llm_configured, agent_llm):
        """未知工具 / 参数 JSON 不可解析 → 降级追问（不报错、不出卡片）。"""
        for items in (
            [ToolCallDelta("make_coffee", "{}")],
            [ToolCallDelta("create_application", "not-a-json")],
        ):
            agent_llm.tool_items = items
            events = _sse_events(client.post(STREAM_API, json={"message": "帮我记一笔投递"}).text)

            assert all(n != "tool_call" for n, _ in events)
            assert _done(events)


# ---------------- TC-139 查询类执行与 result 段 ----------------


class TestQueryEcho:
    """TC-139：查询类工具由后端直接执行——文字总结 + `section="result"` 结构化块；总结不带 tools 防循环。"""

    def test_list_applications_result_block(self, client: TestClient, account, llm_configured, agent_llm):
        _create_application(client, "字节跳动")
        _create_application(client, "腾讯")
        agent_llm.tool_items = [ToolCallDelta("list_applications", "{}")]
        agent_llm.chunks = ["你目前共 2 条投递记录……"]

        events = _sse_events(client.post(STREAM_API, json={"message": "帮我看看投递进度怎么样"}).text)

        assert "你目前共 2 条投递记录……" in _delta_text(events)  # 文字总结走普通 delta
        blocks = _result_blocks(events)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "list_applications"
        assert blocks[0]["data"]["total"] == 2
        assert len(blocks[0]["data"]["items"]) == 2

        # 工具轮带 tools；总结轮回灌请求不带 tools（防模型拿到结果后再选工具形成循环）
        assert agent_llm.tool_calls[0][2]
        assert agent_llm.chat_calls[0][2] is None

        # TOOL 行落库（结果存档）；消息正序 USER → TOOL → ASSISTANT
        conv_id = _done(events)["conversation_id"]
        msgs = client.get(f"{CONV_API}/{conv_id}/messages").json()["data"]
        assert [m["role"] for m in msgs] == ["USER", "TOOL", "ASSISTANT"]
        assert msgs[1]["tool_name"] == "list_applications"
        assert msgs[2]["tool_name"] == "list_applications"

    def test_query_missing_required_follows_up(self, client: TestClient, account, llm_configured, agent_llm):
        """查询类缺必填参数 → 追问、不执行、无 result 段。"""
        agent_llm.tool_items = [ToolCallDelta("search_experience", "{}")]
        events = _sse_events(client.post(STREAM_API, json={"message": "查查我的面经里有没有 JVM"}).text)

        assert not _result_blocks(events)
        assert "检索关键词" in _delta_text(events)
        assert _done(events)
        assert agent_llm.chat_calls == []  # 未执行查询、无总结轮

    def test_result_block_pacing_exempt(self):
        """协议层对照组：同一批事件，`result` 段整块直通、普通文本被拆步（接口文档 §1.4）。"""
        events = [SSE.delta("普通总结文本"), SSE.delta('{"type": "x", "data": {}}', "result")]
        out = list(_paced(iter(events), cps=45.0))

        assert out[-1] == SSE.delta('{"type": "x", "data": {}}', "result")  # 整块直通
        assert len(out[:-1]) > 1  # 非豁免段被小步切分


# ---------------- TC-18 工具执行（execute_tool 直测） ----------------


class TestExecuteTool:
    """TC-18：写操作执行函数直测（HTTP 全链路已于台账 #97 补入 `TestExecuteToolHttp`）。"""

    def test_create_application_without_jd(self, db_session: Session, account_id: int):
        """Agent 录入路径 `jd_text` 可选（自然语言口述未必带 JD）；表单路径仍必填（TC-120 覆盖）。"""
        dto = agent_service.execute_tool(
            db_session,
            user_id=account_id,
            tool_name="create_application",
            args={"company": " 字节跳动 ", "position": "后端开发", "city": "南京"},
        )

        assert dto["company"] == "字节跳动" and dto["city"] == "南京"
        assert db_session.get(Application, dto["id"]).jd_text is None

    def test_create_application_missing_args(self, db_session: Session, account_id: int):
        with pytest.raises(BizException) as exc:
            agent_service.execute_tool(
                db_session,
                user_id=account_id,
                tool_name="create_application",
                args={"company": "字节跳动"},
            )
        assert exc.value.code == ErrorCode.AGENT_TOOL_ARGS_MISSING

    def test_update_status_and_closed_reason(self, db_session: Session, account_id: int):
        created = agent_service.execute_tool(
            db_session,
            user_id=account_id,
            tool_name="create_application",
            args={"company": "腾讯", "position": "后端"},
        )

        dto = agent_service.execute_tool(
            db_session,
            user_id=account_id,
            tool_name="update_application_status",
            args={"application_id": created["id"], "status": "OFFER"},
        )
        assert dto["status"] == "OFFER"

        with pytest.raises(BizException) as exc:  # CLOSED 缺原因 → 50001
            agent_service.execute_tool(
                db_session,
                user_id=account_id,
                tool_name="update_application_status",
                args={"application_id": created["id"], "status": "CLOSED"},
            )
        assert exc.value.code == ErrorCode.AGENT_TOOL_ARGS_MISSING

    def test_execute_errors(self, db_session: Session, account_id: int):
        with pytest.raises(BizException) as exc:  # 查询类工具不走执行端点
            agent_service.execute_tool(
                db_session, user_id=account_id, tool_name="list_applications", args={}
            )
        assert exc.value.code == ErrorCode.PARAM_INVALID

        with pytest.raises(BizException) as exc:  # 不存在 / 跨账号同码
            agent_service.execute_tool(
                db_session,
                user_id=account_id,
                tool_name="update_application_status",
                args={"application_id": 999999, "status": "OFFER"},
            )
        assert exc.value.code == ErrorCode.NOT_FOUND


# ---------------- 台账 #97：执行端点 HTTP 全链路 ----------------


EXECUTE_API = "/api/v1/agent/tools"


class TestExecuteToolHttp:
    """台账 #97：`POST /agent/tools/{tool}/execute` HTTP 全链路（接口文档 v1.40 §3.11 实现口径 3 条）。

    服务层直测见 `TestExecuteTool`；本类覆盖 HTTP 层——**请求体宽收**（缺失 / 非法 → 400 + 50001，
    不被请求校验层拦成 10001）、鉴权、跨账号 404 + 10002、宽转与「无幂等」设计口径。
    """

    def _exec(self, client: TestClient, tool: str, body, headers: dict | None = None):
        kwargs = {"headers": headers} if headers else {}
        return client.post(f"{EXECUTE_API}/{tool}/execute", json=body, **kwargs)

    # ---- ① 正常路径 ----

    def test_create_application_ok(self, client: TestClient, account):
        resp = self._exec(
            client, "create_application", {"company": "美团", "position": "后端开发", "city": "北京"}
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert (data["company"], data["status"]) == ("美团", "APPLIED")
        with SessionLocal() as session:  # 业务表确有新增行，归属当前账号
            row = session.get(Application, data["id"])
            assert row is not None and row.user_id == account["id"]

    def test_update_status_ok(self, client: TestClient, account):
        created = self._exec(
            client, "create_application", {"company": "腾讯", "position": "后端开发"}
        ).json()["data"]

        resp = self._exec(
            client,
            "update_application_status",
            {"application_id": created["id"], "status": "INTERVIEW"},
        )

        assert resp.status_code == 200 and resp.json()["data"]["status"] == "INTERVIEW"
        with SessionLocal() as session:
            assert session.get(Application, created["id"]).status == "INTERVIEW"

    # ---- ② 50001 各态：宽收口径——缺失 / 非法不被请求校验层拦成 10001 ----

    @pytest.mark.parametrize(
        ("tool", "body"),
        [
            ("create_application", {"company": "美团"}),  # 缺必填 position
            ("create_application", {}),  # 空 body
            ("create_application", {"company": "   ", "position": "  "}),  # 全空白值
            ("update_application_status", {"application_id": 1, "status": "CLOSED"}),  # CLOSED 缺原因
            ("update_application_status", {"application_id": 1, "status": "NOT_A_STATUS"}),  # 非法状态
        ],
    )
    def test_missing_or_invalid_args_report_50001(self, client: TestClient, tool, body):
        resp = self._exec(client, tool, body)

        assert resp.status_code == 400 and resp.json()["code"] == 50001  # 不是 10001

    # ---- ③ 10001：非写操作工具 / 请求体非 JSON 对象 ----

    def test_non_write_tool_reports_10001(self, client: TestClient):
        resp = self._exec(client, "list_applications", {})

        assert resp.status_code == 400 and resp.json()["code"] == 10001

    def test_unknown_tool_reports_10001(self, client: TestClient):
        assert self._exec(client, "no_such_tool", {}).json()["code"] == 10001

    def test_non_object_body_reports_10001(self, client: TestClient):
        """数组请求体走全局校验处理器 → 400 + 10001（不是 50001：还没进到工具层）。"""
        resp = client.post(f"{EXECUTE_API}/create_application/execute", json=[1, 2])

        assert resp.status_code == 400 and resp.json()["code"] == 10001

    # ---- ④ 404 + 10002：不存在 / 跨账号 ----

    def test_not_found_and_cross_account(self, client: TestClient, account, make_account):
        resp = self._exec(
            client, "update_application_status", {"application_id": 999999, "status": "OFFER"}
        )
        assert resp.status_code == 404 and resp.json()["code"] == 10002

        created = self._exec(
            client, "create_application", {"company": "字节跳动", "position": "后端"}
        ).json()["data"]
        other = make_account("exec_other")
        resp = self._exec(
            client,
            "update_application_status",
            {"application_id": created["id"], "status": "OFFER"},
            headers=other["headers"],
        )
        assert resp.status_code == 404 and resp.json()["code"] == 10002  # 跨账号同码，不暴露存在性

    # ---- ⑤ 鉴权 ----

    def test_requires_token(self, anon_client: TestClient):
        resp = anon_client.post(
            f"{EXECUTE_API}/create_application/execute",
            json={"company": "美团", "position": "后端"},
        )

        assert resp.status_code == 401 and resp.json()["code"] == 80001

    # ---- ⑥ 宽转：字符串数字 id 与中文状态标签 ----

    def test_wide_coercion_id_and_label(self, client: TestClient, account):
        created = self._exec(
            client, "create_application", {"company": "阿里", "position": "后端"}
        ).json()["data"]

        resp = self._exec(
            client,
            "update_application_status",
            {"application_id": str(created["id"]), "status": "面试中"},
        )

        assert resp.status_code == 200 and resp.json()["data"]["status"] == "INTERVIEW"

    # ---- ⑦ 无幂等（设计使然）：同一请求连发两次 = 两条 ----

    def test_no_idempotency_by_design(self, client: TestClient, account):
        body = {"company": "京东", "position": "后端开发"}
        first = self._exec(client, "create_application", body).json()["data"]
        second = self._exec(client, "create_application", body).json()["data"]

        assert first["id"] != second["id"]  # 防重复由前端承担（接口文档 §3.11 口径 3）


# ---------------- TC-140 会话与消息 ----------------


class TestSessionHistory:
    """TC-140：会话延迟创建（done 回 id）、续轮携带历史、两个查询端点口径。"""

    def test_conversation_created_on_finish_and_listed(self, client: TestClient, account, llm_configured, agent_llm):
        agent_llm.tool_items = [TextDelta("好的～")]
        events = _sse_events(client.post(STREAM_API, json={"message": "你好呀，随便聊聊这个周末的安排"}).text)
        conv_id = _done(events)["conversation_id"]

        page = client.get(CONV_API).json()["data"]
        assert page["total"] == 1
        assert page["items"][0]["id"] == conv_id
        assert page["items"][0]["title"] == "你好呀，随便聊聊这个周末的安排"[:30]  # 标题=首条输入前 30 字

    def test_second_turn_carries_history(self, client: TestClient, account, llm_configured, agent_llm):
        agent_llm.tool_items = [TextDelta("你好！")]
        done1 = _done(_sse_events(client.post(STREAM_API, json={"message": "第一句话"}).text))

        agent_llm.tool_items = [TextDelta("好的～")]
        done2 = _done(
            _sse_events(
                client.post(
                    STREAM_API,
                    json={"message": "第二句话", "conversation_id": done1["conversation_id"]},
                ).text
            )
        )

        assert done2["conversation_id"] == done1["conversation_id"]  # 同会话复用、不新建
        _, messages, _ = agent_llm.tool_calls[1]
        assert {"role": "user", "content": "第一句话"} in messages  # 历史注入
        assert {"role": "assistant", "content": "你好！"} in messages

        msgs = client.get(f"{CONV_API}/{done1['conversation_id']}/messages").json()["data"]
        assert [m["content"] for m in msgs] == ["第一句话", "你好！", "第二句话", "好的～"]  # 正序

    def test_message_query_roles_and_missing(self, client: TestClient, account, llm_configured, agent_llm):
        agent_llm.tool_items = [TextDelta("答复")]
        conv_id = _done(_sse_events(client.post(STREAM_API, json={"message": "会话一"}).text))["conversation_id"]

        msgs = client.get(f"{CONV_API}/{conv_id}/messages").json()["data"]
        assert [m["role"] for m in msgs] == ["USER", "ASSISTANT"]  # role 三值之一的正常形态
        assert all(m["tool_name"] is None for m in msgs)

        assert client.get(f"{CONV_API}/999999/messages").status_code == 404


# ---------------- TC-141 / TC-19 失败与隔离 ----------------


class TestStreamGuards:
    """TC-141 / TC-19：失败不静默、已收 delta 保留、跨账号不可达、未配 Key 即时报错、断连零残留。"""

    def test_classify_failure_streams_error_event(self, client: TestClient, account, llm_configured, agent_llm):
        agent_llm.error = LLMError(ErrorCode.LLM_CALL_FAILED, "上游故障")
        events = _sse_events(client.post(STREAM_API, json={"message": "随便聊点"}).text)

        assert events[0][0] == "start"
        assert _error(events)["code"] == 10010
        assert all(n != "done" for n, _ in events)
        assert client.get(CONV_API).json()["data"]["total"] == 0  # 失败零残留

    def test_mid_stream_failure_keeps_deltas(self, client: TestClient, account, llm_configured, agent_llm):
        """流中途失败：已收 delta 保留、error 事件收尾、本轮不落库（TC-36 口径）。

        消息命中规则（跳过分类出口）——错误落在工具轮，构造「先收到部分 delta」的形态。
        """
        agent_llm.tool_items = [TextDelta("前半段回复")]
        agent_llm.error = LLMError(ErrorCode.LLM_CALL_FAILED, "断流")
        events = _sse_events(client.post(STREAM_API, json={"message": "帮我记一笔投递：字节跳动"}).text)

        assert _delta_text(events) == "前半段回复"
        assert _error(events)["code"] == 10010
        assert client.get(CONV_API).json()["data"]["total"] == 0

    def test_cross_account_conversation_rejected(
        self, client: TestClient, account, make_account, llm_configured, agent_llm
    ):
        agent_llm.tool_items = [TextDelta("答复")]
        conv_id = _done(_sse_events(client.post(STREAM_API, json={"message": "会话一"}).text))["conversation_id"]

        other = make_account("agent_other")
        resp = client.post(
            STREAM_API,
            json={"message": "偷看", "conversation_id": conv_id},
            headers=other["headers"],
        )
        assert resp.status_code == 404 and resp.json()["code"] == 10002  # 普通响应、先于流式建立

    def test_unconfigured_key_reports_10012(self, client: TestClient, account, fake_llm_client):
        events = _sse_events(client.post(STREAM_API, json={"message": "记一笔投递"}).text)

        assert events[0][0] == "start"
        assert _error(events)["code"] == 10012

    def test_message_validation_and_missing_conversation(self, client: TestClient, account, llm_configured, agent_llm):
        assert client.post(STREAM_API, json={"message": "   "}).status_code == 400  # 空白输入 → 10001

        resp = client.post(STREAM_API, json={"message": "你好", "conversation_id": 999999})
        assert resp.status_code == 404 and resp.json()["code"] == 10002

    def test_disconnect_persists_nothing(self, db_session: Session, account_id: int):
        """客户端断连：`GeneratorExit` 穿过业务生成器，会话与消息零残留（重试 = 整轮重发）。"""
        _configure_provider(db_session, account_id)
        fake = AgentFake()
        fake.tool_items = [TextDelta("回复中…")]

        gen = agent_service.run_agent_chat(
            db_session, user_id=account_id, conversation_id=None, message="你好", client=fake
        )
        next(gen)  # 首条 delta 已下发
        gen.close()  # 模拟断连

        assert db_session.query(AgentConversation).count() == 0
        assert db_session.query(AgentMessage).count() == 0
