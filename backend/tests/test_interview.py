"""模拟面试（FR-007）：会话与问答的用例——测试计划 TC-05~07、TC-33。

**后端 interview 服务层与端点尚未实现**（ORM 模型与枚举已随步骤 2 就位）。
本文件全部断言走 TestClient 的 HTTP 层、不 import 服务层——服务层不存在会让文件在
收集期报错，而 HTTP 层此刻稳定返回 404，用例按预期失败、xfail 生效。
后端落地后本文件转 XPASS，届时摘除标记并做真联调校准（尤其 LLM 输出格式相关的
断言：契约只定 `section` 序列，未定模型输出的切段格式）。
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models.interview import InterviewQa

pytestmark = pytest.mark.xfail(
    reason="后端 interview 服务层与端点未实现（步骤 15 后端未开工）；落地后转 XPASS 摘标",
    strict=False,
)

API = "/api/v1/interview-sessions"
STREAM = "/api/v1/stream/interview-chat"
APP_API = "/api/v1/applications"

# FakeLLM 的首轮输出：契约未定切段格式，用最朴素的「评分 X/10 + 正文」文本，
# 后端落地后若要求结构化输出再校准。
CHUNKS = ["评分 8/10，", "亮点：术语准确。", "不足：缺少量化。", "下一题：说说 GC 算法。"]


def _auth(account) -> dict[str, str]:
    """显式构造鉴权头（与 test_practice 同口径，显式比隐式默认好读）。"""
    return {"Authorization": f"Bearer {account['token']}"}


def _create(client: TestClient, account, **body) -> dict:
    resp = client.post(API, json=body, headers=_auth(account))
    assert resp.status_code == 201, resp.text  # 建资源返回 201
    return resp.json()["data"]


def _chat(client: TestClient, account, session_id: int, **payload) -> list[tuple[str, dict]]:
    """走一轮 `/stream/interview-chat`，返回事件序列。"""
    resp = client.post(STREAM, json={"session_id": session_id, **payload}, headers=_auth(account))
    assert resp.status_code == 200, resp.text
    return _sse_events(resp.text)


def _sse_events(body: str) -> list[tuple[str, dict]]:
    """解析响应体里的 SSE 事件序列（`event: <名>` 与 `data: <JSON>` 两行一块）。"""
    events = []
    for block in body.split("\n\n"):
        lines = block.strip().split("\n")
        if len(lines) < 2 or not lines[0].startswith("event: "):
            continue
        events.append((lines[0][len("event: ") :], json.loads(lines[1][len("data: ") :])))
    return events


def _sections(events: list[tuple[str, dict]]) -> list[str]:
    """事件流里 `delta` 的 `section` 序列（按到达顺序）。"""
    return [data.get("section") for name, data in events if name == "delta"]


def _done(events: list[tuple[str, dict]]) -> dict:
    for name, data in events:
        if name == "done":
            return data
    raise AssertionError("事件流里没有 done")


def _qa_rows(session_id: int) -> list[InterviewQa]:
    """按 seq 升序取会话的问答条目。"""
    with SessionLocal() as db:
        return (
            db.query(InterviewQa)
            .filter(InterviewQa.session_id == session_id)
            .order_by(InterviewQa.seq)
            .all()
        )


# ================================================================ TC-05 创建会话


class TestCreateSession:
    """TC-05：创建会话——带 application_id 自动带入公司岗位；手填路径正常。"""

    def test_with_application_brings_company_and_position(self, client: TestClient, account):
        app = client.post(
            APP_API,
            json={"company": "浩鲸科技", "position": "Java 开发"},
            headers=_auth(account),
        ).json()["data"]
        data = _create(client, account, application_id=app["id"])
        assert data["company"] == "浩鲸科技"
        assert data["position"] == "Java 开发"
        assert data["application_id"] == app["id"]

    def test_manual_path_defaults(self, client: TestClient, account):
        data = _create(client, account, company="某某科技", position="后端开发")
        assert data["company"] == "某某科技"
        assert data["position"] == "后端开发"
        assert data["application_id"] is None
        assert data["status"] == "ACTIVE"
        assert data["direction"] == "GENERAL"  # 默认不限方向
        assert data["question_count"] == 8  # 默认题量
        assert data["summary"] is None and data["finished_at"] is None

    def test_missing_company_and_position_rejected(self, client: TestClient, account):
        resp = client.post(API, json={}, headers=_auth(account))
        assert resp.status_code == 400
        assert resp.json()["code"] == 10001

    def test_question_count_bounds(self, client: TestClient, account):
        """题量 3~15：越界拒绝。"""
        for bad in (2, 16):
            resp = client.post(
                API,
                json={"company": "A", "position": "B", "question_count": bad},
                headers=_auth(account),
            )
            assert resp.status_code == 400
            assert resp.json()["code"] == 10001

    def test_direction_accepts_domain_value(self, client: TestClient, account):
        """direction 可取任一领域枚举值（专项面试）。"""
        data = _create(client, account, company="A", position="B", direction="REDIS")
        assert data["direction"] == "REDIS"

    def test_foreign_application_not_visible(self, client: TestClient, account, make_account):
        """跨账号：用别人账号的投递发起 → 404 + 10002（与不存在同款，不暴露存在性）。

        **先建一场合法会话**：统一异常处理器会把「路由不存在」的 404 也包成 `10002`，
        不多走一步的话，本用例在后端未实现时会以同款响应**误判通过**（XPASS 假阳性）。
        """
        other = make_account("interview_other")
        app = client.post(
            APP_API,
            json={"company": "某公司", "position": "某岗位"},
            headers={"Authorization": f"Bearer {other['token']}"},
        ).json()["data"]
        _create(client, account, company="A", position="B")  # 端点必须在（未实现时此处即失败）

        resp = client.post(API, json={"application_id": app["id"]}, headers=_auth(account))
        assert resp.status_code == 404
        assert resp.json()["code"] == 10002


# ================================================================ TC-06 作答落库


class TestAnswerPersists:
    """TC-06：作答落库——FakeLLM 点评流 → interview_qa 落库（question/answer/score/review 完整）。"""

    def test_first_question_then_answer_lands(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        fake_llm_client.chunks = list(CHUNKS)
        session = _create(client, account, company="浩鲸科技", position="Java 开发")

        # 首题：空 answer 触发开场提问，落一条「有 question、无 answer」的 qa
        events = _chat(client, account, session["id"], answer="")
        assert events[0][0] == "start"
        assert "next_question" in _sections(events)
        assert _done(events)["record_id"]

        rows = _qa_rows(session["id"])
        assert len(rows) == 1
        assert rows[0].seq == 1
        assert rows[0].question
        assert not rows[0].answer and rows[0].score is None

        # 作答：review + next_question，首条补全、落第二条
        events = _chat(client, account, session["id"], answer="堆分新生代与老年代")
        assert _sections(events) == ["review", "next_question"]

        rows = _qa_rows(session["id"])
        assert len(rows) == 2
        first, second = rows
        assert first.answer == "堆分新生代与老年代"
        assert first.review and "亮点" in first.review
        assert first.score is not None  # 分数由点评输出解析/结构化获得，具体值待实现校准
        assert second.seq == 2 and second.question and not second.answer

    def test_answer_into_closed_session_rejected(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """会话已结束（40001）后继续作答被拒。"""
        fake_llm_client.chunks = list(CHUNKS)
        session = _create(client, account, company="A", position="B", question_count=3)
        _chat(client, account, session["id"], answer="")
        for i in range(3):
            _chat(client, account, session["id"], answer=f"第 {i + 1} 题作答")

        resp = client.post(
            STREAM, json={"session_id": session["id"], "answer": "再来一题"}, headers=_auth(account)
        )
        assert resp.json()["code"] == 40001


# ================================================================ TC-07 跳过


class TestSkip:
    """TC-07：跳过——skipped=1、score 为空、序号推进。"""

    def test_skip_marks_skipped_and_advances(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        fake_llm_client.chunks = list(CHUNKS)
        session = _create(client, account, company="A", position="B")
        _chat(client, account, session["id"], answer="")  # 首题

        events = _chat(client, account, session["id"], skip=True)
        assert _done(events)

        rows = _qa_rows(session["id"])
        assert len(rows) == 2
        first, second = rows
        assert first.skipped == 1
        assert not first.answer
        assert first.score is None  # 跳过不计分
        assert second.seq == 2 and second.question and not second.answer


# ================================================================ TC-33 SSE 端到端


class TestStream:
    """TC-33：`/stream/interview-chat` 的事件序列与满题量标记。"""

    def test_first_turn_event_order(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """首题（空 answer）：start 第一 → delta(next_question) → done（含 record_id 与 seq）。"""
        fake_llm_client.chunks = list(CHUNKS)
        session = _create(client, account, company="A", position="B")

        events = _chat(client, account, session["id"], answer="")
        assert events[0][0] == "start"
        assert _sections(events) == ["next_question"]
        done = _done(events)
        assert done["record_id"] and done["seq"] == 1

    def test_answer_turn_has_review_then_next(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        fake_llm_client.chunks = list(CHUNKS)
        session = _create(client, account, company="A", position="B")
        _chat(client, account, session["id"], answer="")

        events = _chat(client, account, session["id"], answer="我的作答")
        assert _sections(events) == ["review", "next_question"]

    def test_session_finished_when_count_reached(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """答满题量：末次 done 带 `extra.session_finished=true`，且不再出下一题。"""
        fake_llm_client.chunks = list(CHUNKS)
        session = _create(client, account, company="A", position="B", question_count=3)

        _chat(client, account, session["id"], answer="")
        _chat(client, account, session["id"], answer="第 1 题作答")
        _chat(client, account, session["id"], answer="第 2 题作答")
        events = _chat(client, account, session["id"], answer="第 3 题作答")

        done = _done(events)
        assert done["extra"]["session_finished"] is True
        assert "next_question" not in _sections(events)
