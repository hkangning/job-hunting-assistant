"""错题本（FR-009 / 步骤 14）：入本两形态、列表口径、复习判定与档位推进。

契约见接口文档 §3.9，表结构见数据库设计 §3.9；对应测试计划 TC-11~13（档位推进 / 到期判定 /
客观题规则判定）、TC-45（面试知识点入本两形态）、TC-91（按题型分型判定）。

**为什么不造题库题**：`question` 表不随用例清空（conftest 保留题库种子），造的题收不干净会打挂
`test_seed_questions_fields` 的题库断言。故题库题一律**经抽题接口取真实种子题**；只有知识点形态
会新建题，由 `knowledge_point` fixture 在收尾按前缀清理。入本记录与轮次记录不必手动清——它们
不属保留表，下个用例的 `_reset_database` 会 TRUNCATE 掉。
"""

from datetime import datetime, timedelta
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text

from app.database import SessionLocal
from app.models.question import Question
from app.utils.practice_flow import normalize_text

API = "/api/v1/wrong-questions"
PRACTICE_API = "/api/v1/practice"

# 知识点形态造题的题干前缀：收尾按它清理，与种子题库天然隔离
_KP_PREFIX = "【测试知识点】"


def _auth(account) -> dict[str, str]:
    """显式构造鉴权头——本文件与 test_practice.py 同口径，显式比隐式默认好读。"""
    return {"Authorization": f"Bearer {account['token']}"}


def _pick(client: TestClient, account, qtype: str, count: int = 1) -> list[dict]:
    """抽 `count` 道指定题型的真实种子题（RANDOM——SMART 的加权抽样会让断言不稳定）。"""
    resp = client.post(
        f"{PRACTICE_API}/questions",
        json={"qtypes": [qtype], "count": count, "strategy": "RANDOM"},
        headers=_auth(account),
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]["items"]
    assert items, f"种子题库应含 {qtype} 题"
    return items


def _correct_key(question_id: int, options: list[dict]) -> str:
    """按归一化匹配找出正确项的标识——答案在库里，抽题响应里没有。"""
    with SessionLocal() as session:
        answer = session.get(Question, question_id).answer
    return next(o["key"] for o in options if normalize_text(o["text"]) == normalize_text(answer))


def _add(client: TestClient, account, **payload):
    return client.post(API, json=payload, headers=_auth(account))


def _items(client: TestClient, account, **query) -> dict:
    return client.get(API, params=query, headers=_auth(account)).json()["data"]


@pytest.fixture()
def knowledge_point() -> Generator[dict, None, None]:
    """知识点形态的入参（题干带前缀，收尾连同新建的题一并清掉）。

    同一用例要造第二条时改 `content` 即可（前缀保持不变），清理仍按前缀生效。
    """
    state = {
        "content": f"{_KP_PREFIX}GIL 是什么？",
        "answer": "全局解释器锁：同一进程内同一时刻只有一个线程执行字节码",
        "direction": "PY_BASIC",
        "source_type": "INTERVIEW",
    }
    yield state
    with SessionLocal() as session:
        ids = [
            row
            for (row,) in session.execute(
                text("SELECT id FROM question WHERE content LIKE :p").bindparams(p=f"{_KP_PREFIX}%")
            )
        ]
        if ids:
            expanding = lambda sql: text(sql).bindparams(bindparam("ids", expanding=True))
            session.execute(
                expanding("DELETE FROM wrong_question WHERE question_id IN :ids"), {"ids": ids}
            )
            session.execute(expanding("DELETE FROM question WHERE id IN :ids"), {"ids": ids})
        session.commit()


class TestAdd:
    """入本两形态（接口文档 §3.9 / TC-45）。"""

    def test_from_question_bank_records_manual(self, client: TestClient, account):
        """题库题形态：`{question_id}` → `source_type=MANUAL`，初始 1 档、1 天后复习。"""
        item = _pick(client, account, "CHOICE")[0]

        resp = _add(client, account, question_id=item["id"])
        assert resp.status_code in (200, 201), resp.text
        data = resp.json()["data"]

        assert data["question_id"] == item["id"]
        assert data["source_type"] == "MANUAL"
        assert data["review_stage"] == 1
        assert data["wrong_count"] == 0, "手动添加不是「答错」，不计入次数"
        assert data["mastered_at"] is None

    def test_duplicate_is_10003(self, client: TestClient, account):
        """同账号重复入本 → 409 + 10003。"""
        item = _pick(client, account, "CHOICE")[0]
        _add(client, account, question_id=item["id"])

        resp = _add(client, account, question_id=item["id"])
        assert resp.status_code == 409
        assert resp.json()["code"] == 10003

    def test_missing_question_is_10002(self, client: TestClient, account):
        """题不存在 → 404 + 10002。"""
        resp = _add(client, account, question_id=99_999_999)
        assert resp.status_code == 404
        assert resp.json()["code"] == 10002

    def test_knowledge_point_creates_question(self, client: TestClient, account, knowledge_point):
        """知识点形态：不在题库时自动建题（`AI_GENERATED`）再入本。"""
        resp = _add(client, account, **knowledge_point)
        assert resp.status_code in (200, 201), resp.text
        data = resp.json()["data"]

        assert data["source_type"] == "INTERVIEW"
        assert data["content"].startswith(_KP_PREFIX)
        with SessionLocal() as session:
            row = session.get(Question, data["question_id"])
            assert row is not None and row.source == "AI_GENERATED"

    def test_knowledge_point_reuses_bank_question(self, client: TestClient, account, knowledge_point):
        """题干已在题库 → 复用该题、不重复建题（接口文档 §3.9 实现口径 6）。"""
        item = _pick(client, account, "SUBJECTIVE")[0]
        before = _question_count()

        knowledge_point["content"] = item["content"]
        resp = _add(client, account, **knowledge_point)

        assert resp.json()["data"]["question_id"] == item["id"]
        assert _question_count() == before, "复用不该新建题"

    def test_knowledge_point_accepts_drill_source(self, client: TestClient, account, knowledge_point):
        """练习模式知识点（`DRILL`）同样可入本——该枚举自 v1.7 起在文档、本次代码落地。"""
        knowledge_point["source_type"] = "DRILL"
        resp = _add(client, account, **knowledge_point)
        assert resp.json()["data"]["source_type"] == "DRILL"


def _question_count() -> int:
    with SessionLocal() as session:
        return session.scalar(text("SELECT COUNT(*) FROM question"))


class TestList:
    """列表口径（接口文档 §3.9）。"""

    def test_choice_item_carries_qtype_and_options(self, client: TestClient, account):
        """选择题入本后，列表项带 `qtype` 与 `options`（**不含正确标记**），前端据此渲染点选。"""
        item = _pick(client, account, "CHOICE")[0]
        _add(client, account, question_id=item["id"])

        row = _items(client, account)["items"][0]
        assert row["qtype"] == "CHOICE"
        assert row["options"] == item["options"]
        for opt in row["options"]:
            assert set(opt) == {"key", "text"}, f"选项带契约外字段：{opt}"

    def test_non_choice_options_is_null(self, client: TestClient, account):
        """其余题型的 `options` 为 `null`——与陪练抽题同口径。"""
        item = _pick(client, account, "SUBJECTIVE")[0]
        _add(client, account, question_id=item["id"])

        row = _items(client, account)["items"][0]
        assert row["qtype"] == "SUBJECTIVE"
        assert row["options"] is None

    def test_status_filter_and_page_size_bound(self, client: TestClient, account):
        """`status` 过滤按掌握与否分流；`page_size` 上限 50，越界 → 10001。"""
        item = _pick(client, account, "CHOICE")[0]
        _add(client, account, question_id=item["id"])

        assert _items(client, account, status="PENDING")["total"] == 1
        assert _items(client, account, status="MASTERED")["total"] == 0

        resp = client.get(API, params={"page_size": 51}, headers=_auth(account))
        assert resp.status_code == 400
        assert resp.json()["code"] == 10001

    def test_cross_account_isolation(self, client: TestClient, account, make_account):
        """错题本按账号隔离——另一个账号看不到。"""
        other = make_account("wq_other")
        item = _pick(client, account, "CHOICE")[0]
        _add(client, account, question_id=item["id"])

        assert _items(client, account)["total"] == 1
        assert client.get(API, headers=other["headers"]).json()["data"]["total"] == 0


class TestReview:
    """复习判定与档位推进（TC-11 档位 / TC-13 客观题规则判定 / TC-91 分型判定）。"""

    def _enrolled_choice(self, client: TestClient, account) -> tuple[dict, int]:
        """入本一道选择题，返回 (抽题项, 错题条目 id)。"""
        item = _pick(client, account, "CHOICE")[0]
        wrong_id = _add(client, account, question_id=item["id"]).json()["data"]["id"]
        return item, wrong_id

    def _review(self, client: TestClient, account, wrong_id: int, answer: str):
        return client.post(
            f"{API}/{wrong_id}/review", json={"answer": answer}, headers=_auth(account)
        )

    def test_choice_correct_advances_stage_without_llm(self, client: TestClient, account, fake_llm_client):
        """TC-11 / TC-13：答对推进一档，且**零 AI 调用**（客观题走规则比对）。"""
        item, wrong_id = self._enrolled_choice(client, account)
        key = _correct_key(item["id"], item["options"])

        data = self._review(client, account, wrong_id, key).json()["data"]

        assert data["correct"] is True
        assert data["review_stage"] == 2
        assert data["mastered"] is False
        assert fake_llm_client.stream_calls == [] and fake_llm_client.json_calls == []

    def test_choice_explain_carries_correct_option(self, client: TestClient, account):
        """`explain` 给出正确选项（与陪练同一套比对逻辑，两侧不各写一套）。"""
        item, wrong_id = self._enrolled_choice(client, account)
        correct_key = _correct_key(item["id"], item["options"])
        correct_text = next(o["text"] for o in item["options"] if o["key"] == correct_key)

        data = self._review(client, account, wrong_id, correct_key).json()["data"]
        assert correct_text in data["explain"]

    def test_choice_wrong_resets_to_stage_1(self, client: TestClient, account, fake_llm_client):
        """TC-13：答错 → 回第 1 档、`wrong_count` 递增（先答对进到 2 档，再答错验证回落）。"""
        item, wrong_id = self._enrolled_choice(client, account)
        correct_key = _correct_key(item["id"], item["options"])
        wrong_key = next(o["key"] for o in item["options"] if o["key"] != correct_key)

        self._review(client, account, wrong_id, correct_key)
        data = self._review(client, account, wrong_id, wrong_key).json()["data"]

        assert data["correct"] is False
        assert data["review_stage"] == 1
        assert _items(client, account)["items"][0]["wrong_count"] == 1, "答错计入次数"

    def test_pending_order_follows_review_time(self, client: TestClient, account):
        """TC-12：待复习项按 `next_review_at` 升序（同刻再按 id）——到期近的排在前面。"""
        picked = _pick(client, account, "CHOICE", count=3)
        wrong_ids = [
            _add(client, account, question_id=item["id"]).json()["data"]["id"] for item in picked
        ]
        # 把三条的到期时间改成乱序，验证列表按时间重排而非按插入顺序
        with SessionLocal() as session:
            for wrong_id, offset in zip(wrong_ids, (3, 1, 2)):
                session.execute(
                    text("UPDATE wrong_question SET next_review_at = :t WHERE id = :i"),
                    {"t": datetime.now() + timedelta(days=offset), "i": wrong_id},
                )
            session.commit()

        rows = _items(client, account)["items"]
        assert [r["id"] for r in rows] == [wrong_ids[1], wrong_ids[2], wrong_ids[0]]

    def test_illegal_key_is_judged_wrong_not_rejected(self, client: TestClient, account):
        """不在选项内的标识 → **判错而非报错**。"""
        _, wrong_id = self._enrolled_choice(client, account)

        resp = self._review(client, account, wrong_id, "Z")
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["correct"] is False

    def test_mastered_after_four_advances(self, client: TestClient, account):
        """TC-11：四档走完 → `review_stage=5`、`mastered=true`，随即移出待复习。"""
        item, wrong_id = self._enrolled_choice(client, account)
        key = _correct_key(item["id"], item["options"])

        for _ in range(4):
            data = self._review(client, account, wrong_id, key).json()["data"]

        assert data["review_stage"] == 5
        assert data["mastered"] is True
        assert _items(client, account, status="MASTERED")["total"] == 1
        assert _items(client, account, status="PENDING")["total"] == 0

    def test_subjective_is_judged_by_llm(self, client: TestClient, account, fake_llm_client, llm_configured):
        """TC-91：主观题走 LLM 判定（非流式 JSON），解析结果直接落响应。"""
        item = _pick(client, account, "SUBJECTIVE")[0]
        wrong_id = _add(client, account, question_id=item["id"]).json()["data"]["id"]
        fake_llm_client.json_result = {"correct": True, "explain": "要点齐了"}

        data = self._review(client, account, wrong_id, "堆与方法区").json()["data"]

        assert data["correct"] is True
        assert data["explain"] == "要点齐了"
        assert len(fake_llm_client.json_calls) == 1

    @pytest.mark.xfail(
        strict=True,
        reason="实现缺陷（2026-09-29 发现，已登记问题记录）：接口文档 §3.9 实现口径 5 要求"
        "「空串或全空白 → 400 + 10001」，实现仅靠 pydantic 的 min_length 拦住空串，"
        "全空白会走判定流程返回 200 并判错——用户误触即掉回第 1 档。待后端补 strip 校验后"
        "本标记转为 XPASS，届时摘掉。",
    )
    def test_blank_answer_is_rejected(self, client: TestClient, account):
        """空作答不允许提交（复习是「作答」动作）→ 400 + 10001。"""
        _, wrong_id = self._enrolled_choice(client, account)

        for blank in ("", "   "):
            resp = self._review(client, account, wrong_id, blank)
            assert resp.status_code == 400, f"入参 {blank!r} 应被拒"
            assert resp.json()["code"] == 10001

    def test_cross_account_review_is_30002(self, client: TestClient, account, make_account):
        """跨账号复习 → 404 + 30002（与「条目根本不存在」同码）。"""
        other = make_account("wq_intruder")
        _, wrong_id = self._enrolled_choice(client, account)

        resp = client.post(
            f"{API}/{wrong_id}/review", json={"answer": "x"}, headers=other["headers"]
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == 30002

    def test_delete_removes_entry(self, client: TestClient, account):
        """删除后条目从列表消失。"""
        _, wrong_id = self._enrolled_choice(client, account)

        assert client.delete(f"{API}/{wrong_id}", headers=_auth(account)).json()["code"] == 0
        assert _items(client, account)["total"] == 0
