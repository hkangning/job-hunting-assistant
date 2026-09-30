"""模拟面试（FR-007）：会话与问答的用例——测试计划 TC-05~07、TC-33、TC-118~119。

后端服务层与 `/stream/interview-chat` 已于 2026-09-30 落地，本文件不再是契约先行的
占位用例：FakeLLM 输出按契约的**切段格式**（`## 点评` / `## 下一题` 标题行）构造，
断言逐条核对接口文档 **v1.33 §3.7** 的实现口径。
"""

import json

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models.interview import InterviewQa

API = "/api/v1/interview-sessions"
STREAM = "/api/v1/stream/interview-chat"
APP_API = "/api/v1/applications"

# FakeLLM 的两组输出，按轮次类型分（接口文档 v1.33 §3.7 实现口径 6 的切段格式）：
# 出题 / 跳过轮只产「## 下一题」段；作答轮产「## 点评」+「## 下一题」两段。
# 标题行随 `delta` 原样下发，并计入落库文本（「落库全文 == delta 拼接」）。
QUESTION_CHUNKS = ["## 下一题\n", "说说 JVM 的内存结构。"]
ANSWER_CHUNKS = [
    "## 点评\n",
    "评分 8/10\n",
    "- 亮点：术语准确。\n",
    "- 不足：缺少量化。\n",
    "## 下一题\n",
    "说说 GC 算法。",
]


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


def _ask_turn(fake, client: TestClient, account, session_id: int, **payload) -> list[tuple[str, dict]]:
    """出题 / 跳过轮：FakeLLM 输出只有「## 下一题」段。"""
    fake.chunks = list(QUESTION_CHUNKS)
    return _chat(client, account, session_id, **payload)


def _answer_turn(
    fake, client: TestClient, account, session_id: int, **payload
) -> list[tuple[str, dict]]:
    """作答轮：FakeLLM 输出「## 点评 + ## 下一题」两段（答满轮时下一题段被服务端丢弃）。"""
    fake.chunks = list(ANSWER_CHUNKS)
    return _chat(client, account, session_id, **payload)


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
    """事件流里 `delta` 的 `section` 序列（相邻去重保序）。

    同一段会有多条 delta——标题行与正文各成一块、块边界取决于模型输出，
    这里断言的是**段落序列**而非 delta 条数。
    """
    sections: list[str | None] = []
    for name, data in events:
        if name != "delta":
            continue
        section = data.get("section")
        if not sections or sections[-1] != section:
            sections.append(section)
    return sections


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


def _settle_pending(session_id: int, answer: str = "已作答") -> None:
    """把会话最后一条 qa 直接标记为已作答——构造「ACTIVE 且无待答题」的中间态用例。

    正常链路一轮一次性落库，不会出现该态；这里是在测防御性校验分支
    （接口文档 v1.33 §3.7 实现口径 2 的「answer 非空但当前无待作答的题」）。
    """
    with SessionLocal() as db:
        qa = (
            db.query(InterviewQa)
            .filter(InterviewQa.session_id == session_id)
            .order_by(InterviewQa.seq.desc())
            .first()
        )
        qa.answer = answer
        db.commit()


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
        session = _create(client, account, company="浩鲸科技", position="Java 开发")

        # 首题：空 answer 触发开场提问，落一条「有 question、无 answer」的 qa
        events = _ask_turn(fake_llm_client, client, account, session["id"], answer="")
        assert events[0][0] == "start"
        assert "next_question" in _sections(events)
        assert _done(events)["record_id"]

        rows = _qa_rows(session["id"])
        assert len(rows) == 1
        assert rows[0].seq == 1
        # 落库全文 == delta 拼接：段标题行计入（前端渲染时剥离）
        assert rows[0].question.startswith("## 下一题")
        assert not rows[0].answer and rows[0].score is None

        # 作答：review + next_question，首条补全、落第二条
        events = _answer_turn(
            fake_llm_client, client, account, session["id"], answer="堆分新生代与老年代"
        )
        assert _sections(events) == ["review", "next_question"]

        rows = _qa_rows(session["id"])
        assert len(rows) == 2
        first, second = rows
        assert first.answer == "堆分新生代与老年代"
        assert first.review.startswith("## 点评")
        assert "亮点" in first.review
        assert first.score == 8  # 从点评首行「评分 8/10」解析
        assert second.seq == 2 and second.question.startswith("## 下一题")
        assert not second.answer

    def test_answer_into_closed_session_rejected(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """会话已结束（40001 → HTTP 409）后继续作答被拒。"""
        session = _create(client, account, company="A", position="B", question_count=3)
        _ask_turn(fake_llm_client, client, account, session["id"], answer="")
        for i in range(3):
            _answer_turn(
                fake_llm_client, client, account, session["id"], answer=f"第 {i + 1} 题作答"
            )

        resp = client.post(
            STREAM, json={"session_id": session["id"], "answer": "再来一题"}, headers=_auth(account)
        )
        assert resp.status_code == 409
        assert resp.json()["code"] == 40001


# ================================================================ TC-07 跳过


class TestSkip:
    """TC-07：跳过——skipped=1、score 为空、序号推进。"""

    def test_skip_marks_skipped_and_advances(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        session = _create(client, account, company="A", position="B")
        _ask_turn(fake_llm_client, client, account, session["id"], answer="")  # 首题

        events = _ask_turn(fake_llm_client, client, account, session["id"], skip=True)
        assert _done(events)
        assert "review" not in _sections(events)  # 跳过轮不出点评（口径 4）

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
        session = _create(client, account, company="A", position="B")

        events = _ask_turn(fake_llm_client, client, account, session["id"], answer="")
        assert events[0][0] == "start"
        assert _sections(events) == ["next_question"]
        done = _done(events)
        assert done["record_id"] and done["seq"] == 1

    def test_answer_turn_has_review_then_next(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        session = _create(client, account, company="A", position="B")
        _ask_turn(fake_llm_client, client, account, session["id"], answer="")

        events = _answer_turn(fake_llm_client, client, account, session["id"], answer="我的作答")
        assert _sections(events) == ["review", "next_question"]

    def test_session_finished_when_count_reached(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """答满题量：末次 done 带 `extra.session_finished=true`，且不再出下一题。"""
        session = _create(client, account, company="A", position="B", question_count=3)

        _ask_turn(fake_llm_client, client, account, session["id"], answer="")
        _answer_turn(fake_llm_client, client, account, session["id"], answer="第 1 题作答")
        _answer_turn(fake_llm_client, client, account, session["id"], answer="第 2 题作答")
        events = _answer_turn(
            fake_llm_client, client, account, session["id"], answer="第 3 题作答"
        )

        done = _done(events)
        assert done["extra"]["session_finished"] is True
        assert "next_question" not in _sections(events)

    def test_unstructured_output_reports_error_and_persists_nothing(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """TC-118：模型未按切段格式输出（无标题行）→ `error 10011`、本轮不落库（口径 6）。"""
        fake_llm_client.chunks = ["评分 8/10，", "下一题：说说 GC 算法。"]  # 没有标题行
        session = _create(client, account, company="A", position="B")

        events = _chat(client, account, session["id"], answer="")
        names = [name for name, _ in events]
        assert names[0] == "start" and "done" not in names
        error = next(data for name, data in events if name == "error")
        assert error["code"] == 10011

        assert not _qa_rows(session["id"])  # 本轮不落库（落库只在流正常结束后一次性执行）


# ================================================================ TC-119 作答前置校验


class TestChatGuards:
    """TC-119：`/stream/interview-chat` 的前置校验——均为 SSE 建立前的普通 JSON 响应（口径 2）。"""

    def test_stale_answer_without_pending_rejected(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """`answer` 非空但当前无待作答的题（如流中断后携带旧答案重试）→ 409 + 40001。"""
        session = _create(client, account, company="A", position="B")
        _ask_turn(fake_llm_client, client, account, session["id"], answer="")
        _settle_pending(session["id"])  # 构造「ACTIVE 且无待答题」的防御分支态

        resp = client.post(
            STREAM,
            json={"session_id": session["id"], "answer": "重试的旧作答"},
            headers=_auth(account),
        )
        assert resp.status_code == 409
        assert resp.json()["code"] == 40001

    def test_skip_with_answer_conflict_rejected(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """`skip` 与 `answer` 同时提交 → 400 + 10001。"""
        session = _create(client, account, company="A", position="B")
        _ask_turn(fake_llm_client, client, account, session["id"], answer="")

        resp = client.post(
            STREAM,
            json={"session_id": session["id"], "answer": "作答", "skip": True},
            headers=_auth(account),
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 10001

    def test_skip_without_pending_rejected(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """`skip=true` 但当前无未作答的题 → 400 + 10001。"""
        session = _create(client, account, company="A", position="B")
        _ask_turn(fake_llm_client, client, account, session["id"], answer="")
        _settle_pending(session["id"])

        resp = client.post(
            STREAM, json={"session_id": session["id"], "skip": True}, headers=_auth(account)
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 10001

    def test_empty_answer_resends_pending_question(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """空 `answer` = 请出当前该出的题——待答题原样重发：不调 LLM、不落库（口径 3）。"""
        session = _create(client, account, company="A", position="B")
        _ask_turn(fake_llm_client, client, account, session["id"], answer="")
        calls_before = len(fake_llm_client.stream_calls)

        events = _chat(client, account, session["id"], answer="")
        assert _sections(events) == ["next_question"]
        assert _done(events)["seq"] == 1
        assert len(_qa_rows(session["id"])) == 1  # 不落新条目
        assert len(fake_llm_client.stream_calls) == calls_before  # 不调 LLM

    def test_stream_cross_account_not_found(self, client: TestClient, account, make_account):
        """跨账号作答：会话不可见 → 404 + 10002（校验先于流式建立）。"""
        other = make_account("interview_other2")
        session = _create(client, account, company="A", position="B")

        resp = client.post(
            STREAM, json={"session_id": session["id"], "answer": "我的作答"}, headers=_auth(other)
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == 10002
