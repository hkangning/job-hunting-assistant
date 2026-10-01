"""面经整理（FR-008）：面经 CRUD、条目检索与结构化提取的用例——测试计划 TC-14 / TC-15、TC-127~TC-133。

后端 6 端点已于 2026-09-30 落地（接口文档 v1.37 §3.10 实现口径 8 条）。FakeLLM 输出按契约的
`{"items":[{question, answer_points}]}` JSON 构造；服务层用例走 `db_session`（自建 provider
配置行、不经 HTTP），SSE 事件与前置校验走 TestClient + `llm_configured`。
"""

import json
import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.exceptions import BizException, ErrorCode
from app.models import Experience, ExperienceItem, LlmProviderConfig
from app.models.enums import ExperienceItemSource
from app.schemas.auth import RegisterRequest
from app.schemas.experience import ExperienceCreateRequest, ExperienceDTO
from app.services import auth_service, experience_service
from app.utils.security import encrypt_text
from app.utils.sse import SSE, _paced

API = "/api/v1/experiences"
SEARCH_API = "/api/v1/experience-items/search"
STREAM_API = "/api/v1/stream/experience-extract"
PASSWORD = "test123456"

ORIGINAL = "一面：先自我介绍，然后问了 JVM 内存结构、GC 算法，最后手撕单例。"

# FakeLLM 的契约输出：两条条目，`"question"` 分块各出现一次——进度计数产出「已提炼 1/2 条…」。
EXTRACT_CHUNKS = [
    '{"items": [\n',
    '{"question": "JVM 内存结构？", "answer_points": "堆、栈、方法区"}',
    ',\n{"question": "GC 算法有哪些？", "answer_points": "分代收集"}',
    "]\n}",
]
EXTRACT_QUESTIONS = ["JVM 内存结构？", "GC 算法有哪些？"]


def _configure_provider(db: Session, user_id: int) -> None:
    """给服务层用例的账号配一个供应商：`resolve_config` 需要生效行（`.env` 无 LLM 兜底配置）。"""
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


def _make(db: Session, user_id: int, **overrides) -> ExperienceDTO:
    """服务层建一条面经（原文默认 ORIGINAL，可覆盖任意请求字段）。"""
    payload = ExperienceCreateRequest(
        original_text=overrides.pop("original_text", ORIGINAL), **overrides
    )
    return experience_service.create_experience(db, user_id=user_id, payload=payload)


def _run_extract(db: Session, user_id: int, experience_id: int, fake) -> tuple[list[tuple[str, dict]], dict]:
    """跑一次服务层提取：返回 (事件序列, done 载荷)——消费生成器直到 StopIteration 取回载荷。"""
    events: list[tuple[str, dict]] = []
    gen = experience_service.run_extract(
        db, user_id=user_id, experience_id=experience_id, client=fake
    )
    try:
        while True:
            events.append(_parse_event(next(gen)))
    except StopIteration as stop:
        return events, stop.value or {}


def _parse_event(raw: str) -> tuple[str, dict]:
    """解析单条 SSE 报文：`event: <名>\\ndata: <JSON>` 两行。"""
    lines = raw.strip().split("\n")
    return lines[0][len("event: ") :], json.loads(lines[1][len("data: ") :])


def _sse_events(body: str) -> list[tuple[str, dict]]:
    """解析 HTTP 响应体里的 SSE 事件序列。"""
    return [_parse_event(block) for block in body.split("\n\n") if block.strip().startswith("event: ")]


def _progress_texts(events: list[tuple[str, dict]]) -> list[str]:
    """事件流里 progress 段的文本序列（面经提取的 delta 恒为该段）。"""
    return [d["text"] for n, d in events if n == "delta" and d.get("section") == "progress"]


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


def _items_chunks(items: list[dict]) -> list[str]:
    """把条目列表打包成 FakeLLM 的单块契约输出（边界数据构造用）。"""
    return [json.dumps({"items": items}, ensure_ascii=False)]


def _items(db: Session) -> list[ExperienceItem]:
    return db.query(ExperienceItem).order_by(ExperienceItem.id).all()


# ================================================================ TC-14 保存与提取落库


class TestCreateAndExtract:
    """TC-14：保存原文 + FakeLLM 提取条目落库；提取失败原文保留。"""

    def test_create_saves_original_only(self, db_session: Session, account_id: int):
        """只存原文、不触发提取；短字段空串按未填存 null。"""
        exp = _make(db_session, account_id, company="  字节跳动  ", position="   ", source="牛客")

        assert exp.item_count == 0 and exp.items == []
        assert exp.company == "字节跳动"  # 去空白
        assert exp.position is None  # 空串按未填
        assert exp.original_text == ORIGINAL
        assert _items(db_session) == []  # 不触发提取

    def test_extract_lands_items_and_reports(
        self, db_session: Session, account_id: int, fake_llm_client
    ):
        """契约输出 → 条目落库、冗余计数更新、done 载荷含落库 id；详情 items 按 id 升序。"""
        _configure_provider(db_session, account_id)
        exp = _make(db_session, account_id)

        fake_llm_client.chunks = list(EXTRACT_CHUNKS)
        events, result = _run_extract(db_session, account_id, exp.id, fake_llm_client)

        assert {n for n, _ in events} == {"delta"}  # 模型输出原文不外发，流里只有进度段
        assert _progress_texts(events) == ["正在阅读原文…", "已提炼 1 条…", "已提炼 2 条…"]
        assert result["record_id"] == exp.id

        items = result["extra"]["items"]
        assert [i["question"] for i in items] == EXTRACT_QUESTIONS
        assert all(isinstance(i["id"], int) for i in items)  # 兜底渲染用的落库 id

        rows = _items(db_session)
        assert [r.question for r in rows] == EXTRACT_QUESTIONS
        assert all(r.source_type == ExperienceItemSource.LLM_EXTRACT for r in rows)
        assert db_session.get(Experience, exp.id).item_count == 2

        detail = experience_service.get_experience(
            db_session, user_id=account_id, experience_id=exp.id
        )
        assert [i.id for i in detail.items] == [r.id for r in rows]  # 按 id 升序 = 提取顺序

    def test_extract_failure_keeps_original_and_items(
        self, db_session: Session, account_id: int, fake_llm_client
    ):
        """不可解析 / 0 条有效条目 → 40002；原文与已有条目原样保留、不自动重试。"""
        _configure_provider(db_session, account_id)
        exp = _make(db_session, account_id)

        # 先成功提取一次，作为「已有条目」
        fake_llm_client.chunks = list(EXTRACT_CHUNKS)
        _run_extract(db_session, account_id, exp.id, fake_llm_client)

        bad_outputs = [
            ["这段输出没有任何 JSON 结构。"],  # 不可解析
            _items_chunks([{"answer_points": "没有题干"}, {"question": "   "}]),  # 0 条有效
        ]
        for bad in bad_outputs:
            fake_llm_client.chunks = list(bad)
            with pytest.raises(BizException) as exc:
                for _ in experience_service.run_extract(
                    db_session, user_id=account_id, experience_id=exp.id, client=fake_llm_client
                ):
                    pass
            assert exc.value.code == ErrorCode.EXPERIENCE_EXTRACT_FAILED

        assert db_session.get(Experience, exp.id).original_text == ORIGINAL
        assert [r.question for r in _items(db_session)] == EXTRACT_QUESTIONS  # 仍是首次结果
        assert db_session.get(Experience, exp.id).item_count == 2


# ================================================================ TC-128 提取即替换


class TestReplaceOnExtract:
    """TC-128：提取即替换——重复提取同事务清旧插新，条目不翻倍。"""

    def test_second_extract_replaces_items(
        self, db_session: Session, account_id: int, fake_llm_client
    ):
        _configure_provider(db_session, account_id)
        exp = _make(db_session, account_id)

        fake_llm_client.chunks = list(EXTRACT_CHUNKS)
        _, first = _run_extract(db_session, account_id, exp.id, fake_llm_client)
        first_ids = [i["id"] for i in first["extra"]["items"]]

        fake_llm_client.chunks = _items_chunks(
            [{"question": "重新提取后的问题", "answer_points": "答案"}]
        )
        _, second = _run_extract(db_session, account_id, exp.id, fake_llm_client)

        rows = _items(db_session)
        assert [r.question for r in rows] == ["重新提取后的问题"]  # 清旧插新，不追加
        assert db_session.get(Experience, exp.id).item_count == 1
        assert second["extra"]["items"][0]["id"] not in first_ids  # 旧条目已被清掉


# ================================================================ TC-129 条目清洗


class TestItemCleaning:
    """TC-129：条目清洗——空白题干丢弃、超长截断、50 条上限、缺失要点记 null。"""

    def test_blank_question_dropped_and_missing_answer_null(
        self, db_session: Session, account_id: int, fake_llm_client
    ):
        _configure_provider(db_session, account_id)
        exp = _make(db_session, account_id)

        fake_llm_client.chunks = _items_chunks(
            [
                {"question": "   ", "answer_points": "空白题干整条丢弃"},
                {"question": "没有要点的题"},
                {"question": "要点为空白串的题", "answer_points": "   "},
            ]
        )
        _, result = _run_extract(db_session, account_id, exp.id, fake_llm_client)

        assert [i["question"] for i in result["extra"]["items"]] == ["没有要点的题", "要点为空白串的题"]
        assert all(i["answer_points"] is None for i in result["extra"]["items"])

    def test_overlong_fields_truncated(
        self, db_session: Session, account_id: int, fake_llm_client
    ):
        """题干 >2000 字、要点 >5000 字按上限截断（不丢弃）。"""
        _configure_provider(db_session, account_id)
        exp = _make(db_session, account_id)

        fake_llm_client.chunks = _items_chunks(
            [{"question": "问" * 2100, "answer_points": "答" * 5100}]
        )
        _, result = _run_extract(db_session, account_id, exp.id, fake_llm_client)

        item = result["extra"]["items"][0]
        assert len(item["question"]) == 2000
        assert len(item["answer_points"]) == 5000

    def test_more_than_50_items_capped(
        self, db_session: Session, account_id: int, fake_llm_client
    ):
        """单次最多 50 条（超出截尾）。"""
        _configure_provider(db_session, account_id)
        exp = _make(db_session, account_id)

        fake_llm_client.chunks = _items_chunks(
            [{"question": f"第 {n} 题", "answer_points": "要点"} for n in range(51)]
        )
        _, result = _run_extract(db_session, account_id, exp.id, fake_llm_client)

        assert len(result["extra"]["items"]) == 50
        assert db_session.get(Experience, exp.id).item_count == 50
        assert _items(db_session)[-1].question == "第 49 题"  # 第 51 条被截掉

    def test_non_object_and_empty_items_dropped(
        self, db_session: Session, account_id: int, fake_llm_client
    ):
        """条目不是对象的单独丢弃；全部无效由调用方报 40002（已在 TC-14 覆盖失败面）。"""
        _configure_provider(db_session, account_id)
        exp = _make(db_session, account_id)

        fake_llm_client.chunks = _items_chunks(
            ["不是对象", {"question": "有效题", "answer_points": "要点"}]
        )
        _, result = _run_extract(db_session, account_id, exp.id, fake_llm_client)

        assert [i["question"] for i in result["extra"]["items"]] == ["有效题"]


# ================================================================ TC-127 / TC-15 列表、详情与检索


class TestListAndSearchOrder:
    """TC-127 / TC-15：列表与检索的排序口径、company 联表、账号隔离。"""

    def test_list_order_created_at_desc_then_id_desc(
        self, db_session: Session, account_id: int
    ):
        """列表按 created_at 倒序；同一秒按 id 倒序。"""
        base = datetime(2026, 9, 30, 12, 0, 0)
        ids = []
        for offset in (0, 0, 1):  # 前两条同秒、第三条 +1 秒
            exp = _make(db_session, account_id, original_text=f"第 {offset} 篇原文")
            row = db_session.get(Experience, exp.id)
            row.created_at = base + timedelta(seconds=offset)
            db_session.commit()
            ids.append(exp.id)

        page = experience_service.list_experiences(
            db_session, user_id=account_id, page=1, page_size=10
        )
        assert [i.id for i in page.items] == [ids[2], ids[1], ids[0]]

    def test_search_like_and_company_join(
        self, db_session: Session, account_id: int, fake_llm_client
    ):
        """keyword LIKE 命中题干、company 联表带出、结果 id 倒序；跨账号条目不可见。"""
        _configure_provider(db_session, account_id)

        exp_a = _make(db_session, account_id, company="字节跳动")
        fake_llm_client.chunks = list(EXTRACT_CHUNKS)
        _run_extract(db_session, account_id, exp_a.id, fake_llm_client)

        exp_b = _make(db_session, account_id, original_text="二面：问 JVM 调优。")  # company 未填
        fake_llm_client.chunks = _items_chunks([{"question": "JVM 调优经验"}])
        _run_extract(db_session, account_id, exp_b.id, fake_llm_client)

        page = experience_service.search_items(
            db_session, user_id=account_id, keyword="JVM", page=1, page_size=10
        )
        assert page.total == 2
        assert [i.question for i in page.items] == ["JVM 调优经验", "JVM 内存结构？"]  # id 倒序
        assert {i.experience_id for i in page.items} == {exp_a.id, exp_b.id}
        assert page.items[0].company is None  # 联表带出的 company
        assert page.items[1].company == "字节跳动"

        # 同账号另一关键词
        page = experience_service.search_items(
            db_session, user_id=account_id, keyword="GC", page=1, page_size=10
        )
        assert [i.question for i in page.items] == ["GC 算法有哪些？"]

        # 跨账号：另一账号搜不到本账号条目
        other_id = auth_service.register(
            db_session, RegisterRequest(username="exp_other", password=PASSWORD)
        ).user.id
        others = experience_service.search_items(
            db_session, user_id=other_id, keyword="JVM", page=1, page_size=10
        )
        assert others.total == 0 and others.items == []


# ================================================================ TC-132 删除级联与归属


class TestDeleteAndOwnership:
    """删除级联清条目；跨账号与不存在同码 404 + 10002（不可区分）。"""

    def test_delete_removes_experience_and_items(
        self, db_session: Session, account_id: int, fake_llm_client
    ):
        _configure_provider(db_session, account_id)
        exp = _make(db_session, account_id)
        fake_llm_client.chunks = list(EXTRACT_CHUNKS)
        _run_extract(db_session, account_id, exp.id, fake_llm_client)
        assert len(_items(db_session)) == 2

        experience_service.delete_experience(db_session, user_id=account_id, experience_id=exp.id)

        assert db_session.get(Experience, exp.id) is None
        assert _items(db_session) == []  # 条目随面经级联删除

    def test_foreign_or_missing_not_found(self, db_session: Session, account_id: int):
        other_id = auth_service.register(
            db_session, RegisterRequest(username="exp_owner", password=PASSWORD)
        ).user.id
        other_exp = _make(db_session, other_id)

        for call in (experience_service.get_experience, experience_service.delete_experience):
            with pytest.raises(BizException) as exc:
                call(db_session, user_id=account_id, experience_id=other_exp.id)  # 跨账号
            assert exc.value.code == ErrorCode.NOT_FOUND

        with pytest.raises(BizException) as exc:
            experience_service.get_experience(db_session, user_id=account_id, experience_id=999999)
        assert exc.value.code == ErrorCode.NOT_FOUND  # 不存在，与跨账号同码


# ================================================================ TC-131 中断不落库


class TestMidFailure:
    """TC-131：流中途失败与客户端断连都不落库（重试即完整重跑）。"""

    def test_llm_mid_stream_error_persists_nothing(
        self, db_session: Session, account_id: int, fake_llm_client
    ):
        _configure_provider(db_session, account_id)
        exp = _make(db_session, account_id)

        fake_llm_client.chunks = list(EXTRACT_CHUNKS)
        fake_llm_client.error = RuntimeError("上游断流")
        with pytest.raises(RuntimeError):
            for _ in experience_service.run_extract(
                db_session, user_id=account_id, experience_id=exp.id, client=fake_llm_client
            ):
                pass

        assert _items(db_session) == []  # 中途失败不落库
        assert db_session.get(Experience, exp.id).item_count == 0

    def test_client_disconnect_persists_nothing(
        self, db_session: Session, account_id: int, fake_llm_client
    ):
        """客户端断连：GeneratorExit 穿过业务生成器，commit 不执行。"""
        _configure_provider(db_session, account_id)
        exp = _make(db_session, account_id)

        fake_llm_client.chunks = list(EXTRACT_CHUNKS)
        gen = experience_service.run_extract(
            db_session, user_id=account_id, experience_id=exp.id, client=fake_llm_client
        )
        next(gen)  # 首条进度已下发
        gen.close()  # 模拟断连

        assert _items(db_session) == []
        assert db_session.get(Experience, exp.id).item_count == 0


# ================================================================ TC-127 REST 四端点与校验


class TestExperienceApi:
    """REST：创建 / 列表（不含原文）/ 详情 / 删除；参数校验与账号隔离。"""

    def test_roundtrip_and_list_excludes_original(self, client: TestClient, account):
        resp = client.post(API, json={"company": "字节跳动", "original_text": ORIGINAL})
        assert resp.status_code == 200
        exp = resp.json()["data"]
        assert exp["item_count"] == 0 and exp["items"] == []

        item = client.get(API).json()["data"]["items"][0]
        assert "original_text" not in item  # 列表精简，大字段只走详情
        assert item["id"] == exp["id"] and item["item_count"] == 0

        detail = client.get(f"{API}/{exp['id']}").json()["data"]
        assert detail["original_text"] == ORIGINAL

        assert client.delete(f"{API}/{exp['id']}").status_code == 200
        assert client.get(f"{API}/{exp['id']}").status_code == 404

    def test_create_validation(self, client: TestClient, account):
        """原文必填 1~10000 字；company 等短字段 ≤100 字——违例一律 400 + 10001。"""
        bad_payloads = [
            {},  # 缺原文
            {"original_text": "   "},  # 空白原文
            {"original_text": "面" * 10001},  # 超长原文
            {"original_text": "x", "company": "c" * 101},  # 短字段超长
        ]
        for payload in bad_payloads:
            resp = client.post(API, json=payload)
            assert resp.status_code == 400, resp.text
            assert resp.json()["code"] == 10001

    def test_search_blank_keyword_rejected(self, client: TestClient, account):
        """keyword 只含空白 → 400 + 10001（避免全表命中）。"""
        resp = client.get(SEARCH_API, params={"keyword": "   "})
        assert resp.status_code == 400
        assert resp.json()["code"] == 10001

    def test_cross_account_isolation(
        self, client: TestClient, account, make_account, fake_llm_client, llm_configured
    ):
        other = make_account("exp_other")
        headers_other = {"Authorization": f"Bearer {other['token']}"}
        exp = client.post(API, json={"original_text": ORIGINAL}, headers=headers_other).json()["data"]

        # 详情 / 删除 / 提取：跨账号与不存在同码 404 + 10002（提取为流式建立前的普通响应）
        assert client.get(f"{API}/{exp['id']}").status_code == 404
        assert client.delete(f"{API}/{exp['id']}").json()["code"] == 10002
        resp = client.post(STREAM_API, json={"experience_id": exp["id"]})
        assert resp.status_code == 404 and resp.json()["code"] == 10002
        # 列表不含别人账号的面经
        assert client.get(API).json()["data"]["total"] == 0

    def test_search_api_roundtrip(self, client: TestClient, account, fake_llm_client, llm_configured):
        """检索正常路径：建面经 → 提取（FakeLLM）→ 命中题干；company 联表带出。"""
        exp = client.post(
            API, json={"company": "字节跳动", "original_text": ORIGINAL}
        ).json()["data"]
        fake_llm_client.chunks = list(EXTRACT_CHUNKS)
        client.post(STREAM_API, json={"experience_id": exp["id"]})

        page = client.get(SEARCH_API, params={"keyword": "JVM"}).json()["data"]
        assert page["total"] == 1
        item = page["items"][0]
        assert item["question"] == "JVM 内存结构？"
        assert item["experience_id"] == exp["id"] and item["company"] == "字节跳动"


# ================================================================ TC-130 / TC-132 流式口径


class TestStreamApi:
    """SSE：事件流与 done 载荷、失败口径、progress 段节奏豁免。"""

    def test_event_flow_and_done_payload(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        exp = client.post(API, json={"original_text": ORIGINAL}).json()["data"]
        fake_llm_client.chunks = list(EXTRACT_CHUNKS)

        resp = client.post(STREAM_API, json={"experience_id": exp["id"]})
        assert resp.status_code == 200
        events = _sse_events(resp.text)

        assert events[0][0] == "start"
        assert events[0][1]["message"] == "正在提取面经条目…"
        assert _progress_texts(events) == ["正在阅读原文…", "已提炼 1 条…", "已提炼 2 条…"]

        done = _done(events)
        assert done["record_id"] == exp["id"]
        assert [i["question"] for i in done["extra"]["items"]] == EXTRACT_QUESTIONS
        assert all(isinstance(i["id"], int) for i in done["extra"]["items"])

        detail = client.get(f"{API}/{exp['id']}").json()["data"]
        assert detail["item_count"] == 2
        assert [i["source_type"] for i in detail["items"]] == ["LLM_EXTRACT", "LLM_EXTRACT"]

    def test_failure_reports_40002_and_preserves(
        self, client: TestClient, account, fake_llm_client, llm_configured
    ):
        exp = client.post(API, json={"original_text": ORIGINAL}).json()["data"]
        fake_llm_client.chunks = list(EXTRACT_CHUNKS)
        client.post(STREAM_API, json={"experience_id": exp["id"]})

        fake_llm_client.chunks = ["完全不是 JSON 的输出"]
        events = _sse_events(client.post(STREAM_API, json={"experience_id": exp["id"]}).text)

        assert _error(events)["code"] == 40002
        detail = client.get(f"{API}/{exp['id']}").json()["data"]
        assert detail["original_text"] == ORIGINAL  # 原文保留
        assert detail["item_count"] == 2  # 已有条目保留

    def test_progress_exempt_from_output_pacing(
        self, client: TestClient, account, fake_llm_client, llm_configured, monkeypatch
    ):
        """开节奏（45 字/秒）后 progress 段仍整句直通——被拆碎会只剩零头、覆盖式渲染失效。

        conftest 默认关节奏（`SSE_PACE_CPS=0`），这里显式打开以验证豁免（接口文档 §1.4）。
        """
        monkeypatch.setattr("app.utils.sse.settings.sse_pace_cps", 45.0)
        exp = client.post(API, json={"original_text": ORIGINAL}).json()["data"]
        fake_llm_client.chunks = list(EXTRACT_CHUNKS)

        events = _sse_events(client.post(STREAM_API, json={"experience_id": exp["id"]}).text)
        texts = _progress_texts(events)

        assert texts[0] == "正在阅读原文…"
        assert all(re.fullmatch(r"正在阅读原文…|已提炼 \d+ 条…", t) for t in texts)
        assert texts == ["正在阅读原文…", "已提炼 1 条…", "已提炼 2 条…"]

    def test_pacing_splits_plain_but_not_progress(self):
        """对照组（纯协议层）：同一批文本，非豁免段被拆成小步、progress 段原样一条。"""
        events = [SSE.delta("正在阅读原文…", "progress"), SSE.delta("普通正文片段")]
        out = [e for e in _paced(iter(events), cps=45.0)]

        assert out[0] == SSE.delta("正在阅读原文…", "progress")  # 整句直通
        plain = out[1:]
        assert len(plain) > 1  # 非豁免段被小步切分
        merged = "".join(json.loads(e.split("data: ")[1])["text"] for e in plain)
        assert merged == "普通正文片段"  # 切分只改条数、不改内容
