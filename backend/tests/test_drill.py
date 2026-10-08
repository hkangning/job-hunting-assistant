"""练习模式（FR-020）：题目 CRUD、逐遍点评与跨次进步对比——测试计划 TC-69 / TC-70。

后端（`drill_topic` / `drill_attempt` 两表 + 6 REST + `/stream/drill-review` SSE）于 2026-10-08
落地（接口文档 v1.51 §3.15），本文件按契约口径逐条核对：ref_id 归属四规则（`WRONG` /
`EXPERIENCE` / `JD` 必填且校验归属、`CUSTOM` / `INTRO` 免 ref、`RESUME` 暂不支持）、题面手填 /
AI 生成双形态（生成失败不落空题面）、归档后作答拦截 409 + 40003、逐遍流 `score` → `review`
两段（标题行随 delta 下发、落库全文 = delta 拼接）、表达力指标复用步骤 25 纯函数（quality=OK
才落库）、跨次进步对比按 `voice_metrics.version` 过滤不可比记录、断连 / 中途失败不落任何记录。

FakeLLM 输出按契约的切段格式（`## 评分` / `## 点评` 标题行）构造；流式前置校验
（404 + 10002 / 409 + 40003 / 400 + 10001）走 TestClient 断言普通响应体，断连与中途失败
走服务层生成器直调（`gen.close()` 模拟 GeneratorExit）。
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import DrillAttempt, DrillTopic, LlmProviderConfig
from app.services import drill_service
from app.utils.security import encrypt_text

API = "/api/v1/drills"
STREAM = "/api/v1/stream/drill-review"
APP_API = "/api/v1/applications"
WRONG_API = "/api/v1/wrong-questions"
PRACTICE_API = "/api/v1/practice"
EXP_API = "/api/v1/experiences"

# FakeLLM 的点评输出（接口文档 §3.15 契约格式）：`## 评分` + 一行「数字/10」 + `## 点评` + 三条正文。
# 标题行随 delta 原样下发并计入落库全文（分段器「标题行原样下发」约定）。
REVIEW_CHUNKS = [
    "## 评分\n",
    "8/10\n",
    "## 点评\n",
    "- 亮点：讲清了 JVM 内存结构。\n",
    "- 不足：缺少 GC 的量化数据。\n",
    "- 参考要点：堆 / 栈 / 方法区 + 分代收集。\n",
]
REVIEW_TEXT = (
    "## 点评\n- 亮点：讲清了 JVM 内存结构。\n"
    "- 不足：缺少 GC 的量化数据。\n- 参考要点：堆 / 栈 / 方法区 + 分代收集。"
)

# 合法语音样例（与 TC-72 同口径）：3 句 / 总时长 16s / 有效语音 10s / 20 字 / 停顿两处 → quality=OK
VALID_SEGMENTS = [
    {"seq": 1, "start_ms": 0, "end_ms": 3000, "text": "第一句话测试"},
    {"seq": 2, "start_ms": 5000, "end_ms": 9000, "text": "然后第二句话就是测试"},
    {"seq": 3, "start_ms": 13000, "end_ms": 16000, "text": "第三句话"},
]


def _auth(account) -> dict[str, str]:
    """显式构造鉴权头（与既有测试文件同口径，显式比隐式默认好读）。"""
    return {"Authorization": f"Bearer {account['token']}"}


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
    """事件流里 `delta` 的 `section` 序列（相邻去重保序）。"""
    sections: list[str | None] = []
    for name, data in events:
        if name != "delta":
            continue
        section = data.get("section")
        if not sections or sections[-1] != section:
            sections.append(section)
    return sections


def _section_text(events: list[tuple[str, dict]], section: str) -> str:
    """某段全部 delta 文本的拼接（应与落库全文一致，标题行在内）。"""
    return "".join(
        d["text"] for name, d in events if name == "delta" and d.get("section") == section
    )


def _done(events: list[tuple[str, dict]]) -> dict:
    for name, data in events:
        if name == "done":
            return data
    raise AssertionError("事件流里没有 done")


def _create(client: TestClient, account, **body) -> dict:
    """建题（期望 201），返回题目 DTO。"""
    resp = client.post(API, json=body, headers=_auth(account))
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _make_topic(client: TestClient, account, **overrides) -> dict:
    """建一道手填题面的题（CUSTOM，不触 LLM）——练习 / 对比用例的通用前置。"""
    body = {"title": "JVM 内存结构", "question": "请说说 JVM 的内存结构。", **overrides}
    return _create(client, account, **body)


def _chat(client: TestClient, account, topic_id: int, **payload) -> list[tuple[str, dict]]:
    """走一遍 `/stream/drill-review`，返回事件序列。"""
    resp = client.post(STREAM, json={"topic_id": topic_id, **payload}, headers=_auth(account))
    assert resp.status_code == 200, resp.text
    return _sse_events(resp.text)


def _attempt_rows(topic_id: int) -> list[DrillAttempt]:
    """按 seq 升序取题目的练习记录（直接读库核对落库字段）。"""
    with SessionLocal() as db:
        return (
            db.query(DrillAttempt)
            .filter(DrillAttempt.topic_id == topic_id)
            .order_by(DrillAttempt.seq)
            .all()
        )


def _wrong_ref(client: TestClient, account) -> int:
    """造一条错题并返回其 id（作为 `WRONG` 来源的 ref_id）。"""
    question = client.post(
        f"{PRACTICE_API}/questions",
        json={"qtypes": ["CHOICE"], "count": 1, "strategy": "RANDOM"},
        headers=_auth(account),
    ).json()["data"]["items"][0]
    resp = client.post(WRONG_API, json={"question_id": question["id"]}, headers=_auth(account))
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["data"]["id"]


def _experience_ref(client: TestClient, account) -> int:
    """造一条面经并返回其 id（作为 `EXPERIENCE` 来源的 ref_id）。"""
    resp = client.post(
        EXP_API, json={"original_text": "一面：问了 JVM 内存结构与 GC。"}, headers=_auth(account)
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["data"]["id"]


def _application_ref(client: TestClient, account) -> int:
    """造一条投递并返回其 id（作为 `JD` 来源的 ref_id）；新增时 `jd_text` 必填（接口口径）。"""
    resp = client.post(
        APP_API,
        json={
            "company": "浩鲸科技",
            "position": "Java 开发",
            "jd_text": "岗位职责：负责后端服务开发。",
            "applied_at": "2026-09-20",
        },
        headers=_auth(account),
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["data"]["id"]


def _configure_provider(db: Session, user_id: int) -> None:
    """给账号配一个供应商（服务层用例走真实 resolve_config 路径）。"""
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


def _make_service_topic(db: Session, user_id: int) -> DrillTopic:
    """服务层建一道手填题（不触 LLM），供断连 / 中途失败用例取 topic_id。"""
    topic = DrillTopic(
        user_id=user_id,
        title="JVM 内存结构",
        question="请说说 JVM 的内存结构。",
        source="CUSTOM",
        archived=0,
    )
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return topic


# ================================================================ TC-69 题目 CRUD 与归属


class TestTopicCrud:
    """TC-69：建题六来源与 ref_id 规则、AI 生成题面、列表筛选与聚合、编辑归档、跨账号隔离。"""

    def test_create_custom_with_manual_question(
        self, client: TestClient, account, fake_llm_client
    ):
        """手填题面：直接落库、不调 LLM（json_calls 为空）。"""
        topic = _create(
            client, account, title="自我介绍", question="请用一分钟介绍你自己。", source="CUSTOM"
        )
        assert topic["source"] == "CUSTOM" and topic["ref_id"] is None
        assert topic["question"] == "请用一分钟介绍你自己。"
        assert topic["archived"] == 0
        assert fake_llm_client.json_calls == []

    def test_create_intro_without_ref(self, client: TestClient, account):
        """INTRO 免 ref_id 可建（IS-68 定夺口径：自我介绍无需来源实体）。"""
        topic = _create(
            client, account, title="自我介绍", question="请介绍下你自己。", source="INTRO"
        )
        assert topic["source"] == "INTRO" and topic["ref_id"] is None

    def test_create_custom_with_ref_rejected(self, client: TestClient, account):
        """CUSTOM 传 ref_id → 400 + 10001（「该来源无需 ref_id」）。"""
        resp = client.post(
            API,
            json={"title": "手写题", "question": "题面", "source": "CUSTOM", "ref_id": 1},
            headers=_auth(account),
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()["code"] == 10001

    def test_create_resume_rejected(self, client: TestClient, account):
        """RESUME 暂不支持（画像经历无独立 id）→ 400 + 10001，不落库。"""
        resp = client.post(
            API,
            json={"title": "项目讲解", "question": "讲讲你的项目", "source": "RESUME"},
            headers=_auth(account),
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()["code"] == 10001
        assert client.get(API, headers=_auth(account)).json()["data"]["total"] == 0

    def test_create_from_wrong_question(self, client: TestClient, account):
        """WRONG：错题 id 存在且归属本账号 → 建题成功、ref_id 记录。"""
        ref_id = _wrong_ref(client, account)
        topic = _create(
            client,
            account,
            title="错题重练",
            question="请重做这道错题。",
            source="WRONG",
            ref_id=ref_id,
        )
        assert topic["source"] == "WRONG" and topic["ref_id"] == ref_id

    def test_create_from_experience_and_jd(self, client: TestClient, account):
        """EXPERIENCE / JD：面经与投递记录同为必填 ref_id 的来源。"""
        exp_id = _experience_ref(client, account)
        topic = _create(
            client,
            account,
            title="面经题",
            question="请讲讲这道面经题。",
            source="EXPERIENCE",
            ref_id=exp_id,
        )
        assert topic["ref_id"] == exp_id

        app_id = _application_ref(client, account)
        topic = _create(
            client,
            account,
            title="JD 讲解",
            question="请按这个岗位的 JD 讲讲你的匹配点。",
            source="JD",
            ref_id=app_id,
        )
        assert topic["ref_id"] == app_id

    def test_create_wrong_without_ref_rejected(self, client: TestClient, account):
        """WRONG 不传 ref_id → 400 + 10001（「该来源必须提供 ref_id」）。"""
        resp = client.post(
            API, json={"title": "错题重练", "source": "WRONG"}, headers=_auth(account)
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()["code"] == 10001

    def test_create_ref_not_found_404(self, client: TestClient, account):
        """ref_id 不存在 → 404 + 10002。"""
        resp = client.post(
            API,
            json={"title": "错题重练", "source": "WRONG", "ref_id": 999_999},
            headers=_auth(account),
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == 10002

    def test_create_ref_cross_account_404(self, client: TestClient, account, make_account):
        """ref_id 属于他人账号 → 404 + 10002（与「不存在」不可区分）。"""
        other = make_account("other")
        ref_id = _wrong_ref(client, other)
        resp = client.post(
            API,
            json={"title": "错题重练", "source": "WRONG", "ref_id": ref_id},
            headers=_auth(account),
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == 10002

    def test_create_generates_question_when_blank(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """题面留空 → chat_json 按标题 + 来源生成题面并落库。"""
        fake_llm_client.json_result = {"question": "请说说 JVM 内存结构的组成。"}
        topic = _create(client, account, title="JVM 内存结构", source="CUSTOM")

        assert topic["question"] == "请说说 JVM 内存结构的组成。"
        assert len(fake_llm_client.json_calls) == 1
        _, messages = fake_llm_client.json_calls[0]
        assert "JVM 内存结构" in messages[-1]["content"]

    def test_create_generate_without_key_10012(
        self, client: TestClient, account, fake_llm_client
    ):
        """手填题面不需配 Key；题面留空且未配 Key → 400 + 10012，不落空题面。"""
        topic = _create(client, account, title="手写题", question="直接给题面")
        assert topic["question"] == "直接给题面"

        resp = client.post(API, json={"title": "JVM 内存结构"}, headers=_auth(account))
        assert resp.status_code == 400, resp.text
        assert resp.json()["code"] == 10012
        assert client.get(API, headers=_auth(account)).json()["data"]["total"] == 1

    def test_create_generate_invalid_output_10011(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """模型产出解析不出题面：重试 1 次仍失败 → 502 + 10011，不落库。"""
        fake_llm_client.json_result = {"other": "无效输出"}
        resp = client.post(API, json={"title": "JVM 内存结构"}, headers=_auth(account))

        assert resp.status_code == 502, resp.text
        assert resp.json()["code"] == 10011
        assert len(fake_llm_client.json_calls) == 2  # 解析不出重试 1 次
        assert client.get(API, headers=_auth(account)).json()["data"]["total"] == 0

    def test_list_default_excludes_archived(self, client: TestClient, account):
        """归档题目不出现在默认列表；`archived=true` 查已归档。"""
        kept = _make_topic(client, account)
        archived_topic = _make_topic(client, account, title="第二题")
        client.put(
            f"{API}/{archived_topic['id']}", json={"archived": True}, headers=_auth(account)
        )

        default = client.get(API, headers=_auth(account)).json()["data"]
        assert [item["id"] for item in default["items"]] == [kept["id"]]

        archived = client.get(
            API, params={"archived": "true"}, headers=_auth(account)
        ).json()["data"]
        assert [item["id"] for item in archived["items"]] == [archived_topic["id"]]

    def test_list_source_filter(self, client: TestClient, account):
        """`source` 过滤：只回该来源的题。"""
        _make_topic(client, account)
        _create(client, account, title="自我介绍", question="介绍", source="INTRO")

        data = client.get(
            API, params={"source": "INTRO"}, headers=_auth(account)
        ).json()["data"]
        assert [item["source"] for item in data["items"]] == ["INTRO"]

    def test_list_aggregates_attempt_stats(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """聚合字段：attempt_count / last_score（最近非空） / best_score（历史最高）。"""
        topic = _make_topic(client, account)
        fake_llm_client.chunks = list(REVIEW_CHUNKS)  # 8/10
        _chat(client, account, topic["id"], answer="第一遍作答")
        fake_llm_client.chunks = ["## 评分\n", "6/10\n", "## 点评\n", "- 亮点：结构清晰。\n"]
        _chat(client, account, topic["id"], answer="第二遍作答")

        item = client.get(API, headers=_auth(account)).json()["data"]["items"][0]
        assert item["attempt_count"] == 2
        assert item["last_score"] == 6 and item["best_score"] == 8

    def test_detail_attempts_ascending_without_review(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """详情：题目字段 + attempts 按 seq 升序；摘要不含点评全文与表达指标。"""
        topic = _make_topic(client, account)
        fake_llm_client.chunks = list(REVIEW_CHUNKS)
        _chat(client, account, topic["id"], answer="第一遍")
        _chat(client, account, topic["id"], answer="第二遍")

        detail = client.get(f"{API}/{topic['id']}", headers=_auth(account)).json()["data"]
        assert detail["title"] == topic["title"] and detail["question"] == topic["question"]
        assert [a["seq"] for a in detail["attempts"]] == [1, 2]
        assert [a["score"] for a in detail["attempts"]] == [8, 8]
        assert all("review" not in item and "voice_metrics" not in item for item in detail["attempts"])

    def test_update_partial_fields(self, client: TestClient, account):
        """编辑：部分更新——只改传了的字段，未传不改。"""
        topic = _make_topic(client, account)
        data = client.put(
            f"{API}/{topic['id']}", json={"title": "改标题"}, headers=_auth(account)
        ).json()["data"]

        assert data["title"] == "改标题"
        assert data["question"] == topic["question"]

    def test_cross_account_topic_404(self, client: TestClient, account, make_account):
        """跨账号访问详情 / 编辑 / 进步对比 → 一律 404 + 10002。"""
        topic = _make_topic(client, account)
        other = make_account("other")
        for resp in (
            client.get(f"{API}/{topic['id']}", headers=_auth(other)),
            client.put(f"{API}/{topic['id']}", json={"title": "改"}, headers=_auth(other)),
            client.get(f"{API}/{topic['id']}/progress", headers=_auth(other)),
        ):
            assert resp.status_code == 404, resp.text
            assert resp.json()["code"] == 10002

    def test_archived_topic_rejects_answer_409(self, client: TestClient, account):
        """归档后作答 → 409 + 40003（校验先于流式建立、普通响应体）。"""
        topic = _make_topic(client, account)
        client.put(f"{API}/{topic['id']}", json={"archived": True}, headers=_auth(account))

        resp = client.post(
            STREAM, json={"topic_id": topic["id"], "answer": "作答"}, headers=_auth(account)
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["code"] == 40003
        assert "text/event-stream" not in resp.headers.get("content-type", "")


# ================================================================ TC-70 连练与跨次对比


class TestReviewStream:
    """TC-70：逐遍点评流、逐次留存、表达指标与跨次进步对比（含版本可比口径）。"""

    def test_review_two_sections_and_persist(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """一遍：`start → delta → done`；score → review 两段；落库全文 = delta 拼接、seq=1。"""
        topic = _make_topic(client, account)
        fake_llm_client.chunks = list(REVIEW_CHUNKS)
        events = _chat(client, account, topic["id"], answer="第一遍作答", duration_ms=12_000)

        assert events[0][0] == "start"
        assert _sections(events) == ["score", "review"]
        done = _done(events)
        assert done["seq"] == 1 and isinstance(done["record_id"], int)

        row = _attempt_rows(topic["id"])[0]
        assert row.answer == "第一遍作答" and row.score == 8
        # 落库全文 = delta 拼接（首尾空白 strip）——标题行在内
        assert row.review == REVIEW_TEXT
        assert _section_text(events, "review").strip() == REVIEW_TEXT
        assert row.is_voice == 0 and row.voice_metrics is None and row.duration_ms == 12_000

    def test_seq_increments_per_attempt(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """同题连练三遍：seq 逐遍递增（max+1）、逐次留存可回看。"""
        topic = _make_topic(client, account)
        fake_llm_client.chunks = list(REVIEW_CHUNKS)
        seqs = [
            _done(_chat(client, account, topic["id"], answer=f"第 {i} 遍作答"))["seq"]
            for i in range(1, 4)
        ]
        assert seqs == [1, 2, 3]
        assert [row.seq for row in _attempt_rows(topic["id"])] == [1, 2, 3]

        detail = client.get(f"{API}/{topic['id']}", headers=_auth(account)).json()["data"]
        assert [a["seq"] for a in detail["attempts"]] == [1, 2, 3]

    def test_score_unparsable_records_null(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """评分段存在但抠不出 0~10 数字：score 记 null（不拦落库，前端从正文兜底）。"""
        topic = _make_topic(client, account)
        fake_llm_client.chunks = [
            "## 评分\n",
            "表现不错\n",
            "## 点评\n",
            "- 亮点：结构清晰。\n",
        ]
        events = _chat(client, account, topic["id"], answer="作答")

        assert _sections(events) == ["score", "review"]
        assert _attempt_rows(topic["id"])[0].score is None

    def test_missing_review_section_reports_10011(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """模型未产出点评段：流内 `error`（10011），不落任何记录（重试 = 整遍重发）。"""
        topic = _make_topic(client, account)
        fake_llm_client.chunks = ["## 评分\n", "8/10\n"]
        resp = client.post(
            STREAM, json={"topic_id": topic["id"], "answer": "作答"}, headers=_auth(account)
        )
        assert resp.status_code == 200

        events = _sse_events(resp.text)
        errors = [d for name, d in events if name == "error"]
        assert errors and errors[0]["code"] == 10011
        assert not any(name == "done" for name, _ in events)
        assert _attempt_rows(topic["id"]) == []

    def test_voice_segments_produce_metrics(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """语音作答随传 segments：done.extra 下发指标、落库、单次详情可回看；prompt 含表达力块。"""
        topic = _make_topic(client, account)
        fake_llm_client.chunks = list(REVIEW_CHUNKS)
        events = _chat(
            client, account, topic["id"], answer="作答内容", is_voice=True, segments=VALID_SEGMENTS
        )
        metrics = _done(events)["extra"]["voice_metrics"]
        assert metrics["quality"] == "OK" and metrics["version"] == 1
        assert metrics["speech_rate"] == 120  # 20 字 ÷ 10s 有效语音

        row = _attempt_rows(topic["id"])[0]
        assert row.is_voice == 1 and json.loads(row.voice_metrics)["speech_rate"] == 120
        # 指标注入点评 prompt（教练可引原话点评表达）
        _, messages, _ = fake_llm_client.stream_calls[0]
        assert "表达力指标" in messages[-1]["content"]

        attempt_id = _done(events)["record_id"]
        detail = client.get(
            f"{API}/{topic['id']}/attempts/{attempt_id}", headers=_auth(account)
        ).json()["data"]
        assert detail["voice_metrics"]["speech_rate"] == 120
        assert detail["review"] == REVIEW_TEXT

    def test_text_answer_and_too_short_produce_no_metrics(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """文字作答与作答过短（TOO_SHORT）都不产指标、列空。

        `is_voice` 由请求字段**显式指定**（前端按本次是否录过音判断，与面试链路的
        「按是否传 segments 判断」不同口径）；`segments` 只决定指标能否算出。
        """
        topic = _make_topic(client, account)
        fake_llm_client.chunks = list(REVIEW_CHUNKS)

        done = _done(_chat(client, account, topic["id"], answer="纯文字作答"))
        assert "voice_metrics" not in (done.get("extra") or {})

        done = _done(
            _chat(client, account, topic["id"], answer="作答", is_voice=True, segments=[])
        )
        assert "voice_metrics" not in (done.get("extra") or {})

        rows = _attempt_rows(topic["id"])
        assert [(row.is_voice, row.voice_metrics) for row in rows] == [(0, None), (1, None)]

    def test_bad_segments_rejected_before_stream(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """坏 segments（缺字段 / 起止颠倒 / 零长）→ 400 + 10001，校验先于流式建立。

        起止颠倒与零长由 `SegmentItem` 跨字段校验拦截（IS-65，后端 2026-10-08 修复）。
        """
        topic = _make_topic(client, account)
        bad_cases = [
            [{"start_ms": 0, "end_ms": 1000, "text": "x"}],  # 缺 seq
            [{"seq": 1, "start_ms": 9000, "end_ms": 1000, "text": "x"}],  # 起止颠倒
            [{"seq": 1, "start_ms": 1000, "end_ms": 1000, "text": "x"}],  # 零长片段
        ]
        for bad in bad_cases:
            resp = client.post(
                STREAM,
                json={"topic_id": topic["id"], "answer": "x", "segments": bad},
                headers=_auth(account),
            )
            assert resp.status_code == 400, resp.text
            assert resp.json()["code"] == 10001
            assert "text/event-stream" not in resp.headers.get("content-type", "")

    def test_progress_deltas_between_comparable_attempts(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """跨次对比：两遍可比记录 → items 两条 + deltas 为最近两遍差值（to - from）。"""
        topic = _make_topic(client, account)
        fake_llm_client.chunks = list(REVIEW_CHUNKS)  # 8/10
        _chat(
            client, account, topic["id"], answer="第一遍", is_voice=True,
            segments=VALID_SEGMENTS, duration_ms=16_000,
        )
        fake_llm_client.chunks = ["## 评分\n", "9/10\n", "## 点评\n", "- 亮点：进步明显。\n"]
        _chat(
            client, account, topic["id"], answer="第二遍", is_voice=True,
            segments=VALID_SEGMENTS, duration_ms=18_000,
        )

        data = client.get(f"{API}/{topic['id']}/progress", headers=_auth(account)).json()["data"]
        assert data["attempt_count"] == 2
        assert [item["seq"] for item in data["items"]] == [1, 2]
        assert [item["score"] for item in data["items"]] == [8, 9]
        assert data["items"][0]["speech_rate"] == 120
        assert data["deltas"] == {
            "score": 1,
            "duration_ms": 2000,
            "filler_count": 0,
            "pause_count": 0,
        }

    def test_progress_filters_incomparable_versions(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """跨 `voice_metrics.version` 的记录整条剔除、无指标记录保留；attempt_count 为全部遍数。"""
        topic = _make_topic(client, account)
        fake_llm_client.chunks = list(REVIEW_CHUNKS)
        _chat(client, account, topic["id"], answer="第一遍", is_voice=True, segments=VALID_SEGMENTS)
        _chat(client, account, topic["id"], answer="第二遍文字")  # 无指标记录

        # 把第一遍的指标版本改成 0（模拟算法口径变更前的旧记录）
        with SessionLocal() as db:
            row = (
                db.query(DrillAttempt)
                .filter(DrillAttempt.topic_id == topic["id"], DrillAttempt.seq == 1)
                .one()
            )
            metrics = json.loads(row.voice_metrics)
            metrics["version"] = 0
            row.voice_metrics = json.dumps(metrics)
            db.commit()

        fake_llm_client.chunks = list(REVIEW_CHUNKS)
        _chat(client, account, topic["id"], answer="第三遍", is_voice=True, segments=VALID_SEGMENTS)

        data = client.get(f"{API}/{topic['id']}/progress", headers=_auth(account)).json()["data"]
        assert data["attempt_count"] == 3
        assert [item["seq"] for item in data["items"]] == [2, 3]  # seq1 跨版本剔除、seq2 无指标保留
        assert data["items"][0]["speech_rate"] is None

    def test_stream_carries_no_wrong_candidates_section(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        """错题候选段当前版本暂缓下发：流内只出 score / review 两段、落库文本不含候选段。"""
        topic = _make_topic(client, account)
        fake_llm_client.chunks = list(REVIEW_CHUNKS)
        events = _chat(client, account, topic["id"], answer="作答")

        assert _sections(events) == ["score", "review"]
        row = _attempt_rows(topic["id"])[0]
        assert "wrong_candidates" not in (row.review or "")

    def test_mid_stream_error_persists_nothing(
        self, db_session: Session, account_id: int, fake_llm_client
    ):
        """流中途上游断流：异常穿透、练习记录零残留（重试 = 整遍重发）。"""
        _configure_provider(db_session, account_id)
        topic = _make_service_topic(db_session, account_id)

        fake_llm_client.chunks = list(REVIEW_CHUNKS)
        fake_llm_client.error = RuntimeError("上游断流")
        with pytest.raises(RuntimeError):
            for _ in drill_service.run_review(
                db_session,
                user_id=account_id,
                topic_id=topic.id,
                answer="作答",
                is_voice=False,
                segments=None,
                duration_ms=None,
                client=fake_llm_client,
            ):
                pass

        assert _attempt_rows(topic.id) == []

    def test_client_disconnect_persists_nothing(
        self, db_session: Session, account_id: int, fake_llm_client
    ):
        """客户端断连：GeneratorExit 穿过业务生成器，落库不执行、练习记录零残留。"""
        _configure_provider(db_session, account_id)
        topic = _make_service_topic(db_session, account_id)

        fake_llm_client.chunks = list(REVIEW_CHUNKS)
        gen = drill_service.run_review(
            db_session,
            user_id=account_id,
            topic_id=topic.id,
            answer="作答",
            is_voice=False,
            segments=None,
            duration_ms=None,
            client=fake_llm_client,
        )
        next(gen)  # 首条 delta 已下发
        gen.close()  # 模拟断连

        assert _attempt_rows(topic.id) == []
