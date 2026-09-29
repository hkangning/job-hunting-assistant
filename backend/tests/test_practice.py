"""八股陪练（FR-009）：训练系统的用例。

分两块：**纯函数模块**（轮次状态机 `practice_flow` / 掌握度 `mastery`）不经 HTTP、不碰库，
按系统设计 §8 的「可脱离 HTTP 直接单测、全分支覆盖」写；**接口层**走 TestClient + FakeLLM。

命名与断言口径对齐 `docs/05-测试文档/测试计划.md` 的 TC-09 / TC-10 / TC-34 / TC-44 与
步骤 13 新增项（追问链推进与终止、结算幂等与断点判定、薄弱优先选题、限时超时）。
"""

import json
from datetime import datetime, timedelta
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.database import SessionLocal

from app.models.enums import AttackFace, PracticeMode
from app.models.question import DomainMastery, Question
from app.utils import mastery as M
from app.utils.practice_flow import is_break, is_stuck, judge_passed, next_turn, normalize_text

# ================================================================ A 轮次状态机


class TestIsStuck:
    """`is_stuck`：字符串匹配，不调 LLM——要的是快和稳，不是准。"""

    def test_blank_answer_is_stuck(self):
        assert is_stuck("") is True
        assert is_stuck(None) is True
        assert is_stuck("   ") is True

    def test_short_giving_up_phrases_are_stuck(self):
        assert is_stuck("不知道") is True
        assert is_stuck("这个我不会") is True
        assert is_stuck("没做过这块") is True
        assert is_stuck("想不起来了") is True

    def test_long_text_with_same_phrase_is_not_stuck(self):
        # 「这块我不清楚，但我知道…」是在展开论述而非认输，故只认短作答
        long_text = "这块我不清楚，但我知道它跟内存屏障有关，具体分几个层面来说，" * 3
        assert len(long_text) > 30
        assert is_stuck(long_text) is False

    def test_normal_answer_is_not_stuck(self):
        assert is_stuck("堆分新生代与老年代，新生代用复制算法") is False


class TestNextTurnQuick:
    def test_quick_always_settles(self):
        decision = next_turn(
            mode=PracticeMode.QUICK, round_index=1, follow_up_count=0, last_result="OK"
        )
        assert decision.action == "SETTLE"

    def test_quick_settles_even_when_stuck(self):
        decision = next_turn(
            mode=PracticeMode.QUICK, round_index=1, follow_up_count=0, last_result="STUCK"
        )
        assert decision.action == "SETTLE"


class TestNextTurnInterviewer:
    """面试官深挖：答不上**不打断**（压力正在于此），追满 4 层或已挖到底才收尾。"""

    def test_first_follow_up_is_layer_one_basis(self):
        decision = next_turn(
            mode=PracticeMode.INTERVIEWER, round_index=1, follow_up_count=0, last_result="OK"
        )
        assert decision.action == "FOLLOW_UP"
        assert decision.layer == 1
        assert decision.face is AttackFace.BASIS

    def test_layers_advance_in_fixed_order(self):
        faces = []
        for count in range(4):
            decision = next_turn(
                mode=PracticeMode.INTERVIEWER,
                round_index=count + 1,
                follow_up_count=count,
                last_result="OK",
            )
            faces.append(decision.face)
        assert faces == [
            AttackFace.BASIS,
            AttackFace.BOUNDARY,
            AttackFace.TRADEOFF,
            AttackFace.LANDING,
        ]

    def test_stuck_does_not_stop_interviewer(self):
        # 这正是本模式与教练模式的分野：答不上照样往下追
        decision = next_turn(
            mode=PracticeMode.INTERVIEWER, round_index=2, follow_up_count=1, last_result="STUCK"
        )
        assert decision.action == "FOLLOW_UP"
        assert decision.layer == 2

    def test_settles_after_max_layers(self):
        decision = next_turn(
            mode=PracticeMode.INTERVIEWER, round_index=5, follow_up_count=4, last_result="OK"
        )
        assert decision.action == "SETTLE"

    def test_settles_when_exhausted(self):
        # 「已挖到底」——答得够完整，没什么可追了，不硬凑层数
        decision = next_turn(
            mode=PracticeMode.INTERVIEWER,
            round_index=2,
            follow_up_count=1,
            last_result="OK",
            exhausted=True,
        )
        assert decision.action == "SETTLE"


class TestNextTurnCoach:
    """教练引导：答不上**先给提示**，提示后仍答不出才记断点并继续追问。"""

    def test_stuck_gives_hint_first(self):
        decision = next_turn(
            mode=PracticeMode.COACH, round_index=1, follow_up_count=0, last_result="STUCK"
        )
        assert decision.action == "HINT"

    def test_hint_used_then_follows_up(self):
        decision = next_turn(
            mode=PracticeMode.COACH, round_index=2, follow_up_count=0, last_result="HINT_USED"
        )
        assert decision.action == "FOLLOW_UP"
        assert decision.layer == 1

    def test_normal_answer_follows_up_like_interviewer(self):
        decision = next_turn(
            mode=PracticeMode.COACH, round_index=1, follow_up_count=0, last_result="OK"
        )
        assert decision.action == "FOLLOW_UP"
        assert decision.face is AttackFace.BASIS

    def test_settles_after_max_layers(self):
        decision = next_turn(
            mode=PracticeMode.COACH, round_index=5, follow_up_count=4, last_result="OK"
        )
        assert decision.action == "SETTLE"


class TestNextTurnDebug:
    """挑错纠错：材料轮与找错轮各占一轮，最多 2 轮材料。"""

    def test_first_round_gives_material(self):
        decision = next_turn(
            mode=PracticeMode.DEBUG, round_index=1, follow_up_count=0, last_result="OK"
        )
        assert decision.action == "FOLLOW_UP"
        assert decision.layer is None  # 材料轮不属于追问链

    def test_settles_after_two_materials(self):
        # round_index 4 = 第 2 轮材料的找错轮已完成
        decision = next_turn(
            mode=PracticeMode.DEBUG, round_index=4, follow_up_count=0, last_result="OK"
        )
        assert decision.action == "SETTLE"

    def test_stuck_ends_debug(self):
        decision = next_turn(
            mode=PracticeMode.DEBUG, round_index=2, follow_up_count=0, last_result="STUCK"
        )
        assert decision.action == "SETTLE"


class TestNextTurnFeynman:
    """费曼复述：针对讲错或含糊处追问，最多 2 轮。"""

    def test_follows_up_once(self):
        decision = next_turn(
            mode=PracticeMode.FEYNMAN, round_index=1, follow_up_count=0, last_result="OK"
        )
        assert decision.action == "FOLLOW_UP"

    def test_settles_after_two_follow_ups(self):
        decision = next_turn(
            mode=PracticeMode.FEYNMAN, round_index=3, follow_up_count=2, last_result="OK"
        )
        assert decision.action == "SETTLE"

    def test_stuck_settles(self):
        decision = next_turn(
            mode=PracticeMode.FEYNMAN, round_index=1, follow_up_count=0, last_result="STUCK"
        )
        assert decision.action == "SETTLE"


class TestIsBreak:
    def test_stuck_and_hint_used_are_breaks(self):
        assert is_break("STUCK") is True
        assert is_break("HINT_USED") is True

    def test_ok_is_not_a_break(self):
        assert is_break("OK") is False


class TestJudgePassed:
    def test_quick_needs_six(self):
        assert judge_passed(mode=PracticeMode.QUICK, overall_score=6, break_count=0) is True
        assert judge_passed(mode=PracticeMode.QUICK, overall_score=5, break_count=0) is False

    def test_interviewer_needs_six_and_fewer_than_two_breaks(self):
        assert judge_passed(mode=PracticeMode.INTERVIEWER, overall_score=7, break_count=1) is True
        # 分够但断点 ≥ 2 —— 追到答不上两次，不算过
        assert judge_passed(mode=PracticeMode.INTERVIEWER, overall_score=8, break_count=2) is False
        assert judge_passed(mode=PracticeMode.COACH, overall_score=7, break_count=2) is False

    def test_debug_needs_hit_rate(self):
        assert judge_passed(mode=PracticeMode.DEBUG, overall_score=9, break_count=0, hit_rate=0.6) is True
        assert judge_passed(mode=PracticeMode.DEBUG, overall_score=9, break_count=0, hit_rate=0.59) is False

    def test_feynman_needs_fewer_than_three_leaks(self):
        assert judge_passed(mode=PracticeMode.FEYNMAN, overall_score=9, break_count=0, leak_count=2) is True
        assert judge_passed(mode=PracticeMode.FEYNMAN, overall_score=9, break_count=0, leak_count=3) is False

    def test_missing_inputs_fall_back_to_not_passed(self):
        # 分数没解析出来（None）时按 0 处理；漏洞数缺省按 99（不可能通过）
        assert judge_passed(mode=PracticeMode.QUICK, overall_score=None, break_count=0) is False
        assert judge_passed(mode=PracticeMode.INTERVIEWER, overall_score=None, break_count=0) is False
        assert judge_passed(mode=PracticeMode.DEBUG, overall_score=9, break_count=0) is False
        assert judge_passed(mode=PracticeMode.FEYNMAN, overall_score=9, break_count=0) is False


# ================================================================ B 掌握度

NOW = datetime(2026, 9, 28, 12, 0, 0)


class TestRecentScore:
    def test_empty_is_zero(self):
        assert M.recent_score([]) == 0.0

    def test_all_none_is_zero(self):
        assert M.recent_score([None, None]) == 0.0

    def test_single_score_normalised(self):
        assert M.recent_score([10]) == pytest.approx(1.0)
        assert M.recent_score([5]) == pytest.approx(0.5)

    def test_recent_weighs_more(self):
        # [5, 10] → (5×1 + 10×2) / (10×3) = 25/30
        assert M.recent_score([5, 10]) == pytest.approx(25 / 30)
        # 反过来分数更低：越新权重越高
        assert M.recent_score([10, 5]) == pytest.approx(20 / 30)

    def test_window_keeps_last_ten(self):
        # 前 10 次全 0、后 10 次全 10 —— 窗口只取最后 10 次
        assert M.recent_score([0] * 10 + [10] * 10) == pytest.approx(1.0)
        # 反过来：前面的高分已被挤出窗口
        assert M.recent_score([10] * 10 + [0] * 10) == pytest.approx(0.0)

    def test_none_scores_are_skipped(self):
        assert M.recent_score([None, 10, None]) == pytest.approx(1.0)


class TestCoverage:
    def test_zero_total_is_zero(self):
        assert M.coverage(0, 0) == 0.0

    def test_partial_coverage(self):
        # 领域题量 100 → 目标 15 题
        assert M.coverage(5, 100) == pytest.approx(5 / 15)

    def test_small_domain_saturates_earlier(self):
        # 领域只有 8 题时，练完 8 题即满
        assert M.coverage(5, 8) == pytest.approx(5 / 8)
        assert M.coverage(8, 8) == pytest.approx(1.0)

    def test_caps_at_one(self):
        assert M.coverage(30, 100) == 1.0


class TestRetention:
    def test_never_wrong_is_one(self):
        assert M.retention(0, 0) == 1.0

    def test_ratio(self):
        assert M.retention(3, 5) == pytest.approx(0.6)

    def test_caps_at_one(self):
        assert M.retention(5, 5) == 1.0


class TestDecay:
    def test_never_practised_is_floor(self):
        # 从未练过不该是 0——否则荒废领域永远抽不到、练不回来
        assert M.decay(None, NOW) == M.DECAY_FLOOR

    def test_one_week_multiplies_once(self):
        assert M.decay(NOW - timedelta(days=7), NOW) == pytest.approx(0.98)

    def test_two_weeks_multiplies_twice(self):
        assert M.decay(NOW - timedelta(days=14), NOW) == pytest.approx(0.98**2)

    def test_floor_holds_for_long_absence(self):
        assert M.decay(NOW - timedelta(days=3650), NOW) == M.DECAY_FLOOR

    def test_future_timestamp_counts_as_zero_days(self):
        assert M.decay(NOW + timedelta(days=3), NOW) == pytest.approx(1.0)


class TestComputeMastery:
    def test_all_zero_needs_no_decay_floor_first(self):
        # 三项因子全空：0.6×0 + 0.25×0 + 0.15×1（从未入本视为健康）= 0.15，再乘衰减下限 0.5
        value = M.compute_mastery(
            scores=[], covered_count=0, domain_total=10,
            mastered_count=0, ever_wrong_count=0,
            last_practiced_at=None, now=NOW,
        )
        assert value == 8  # round(100 × 0.15 × 0.5) = round(7.5)

    def test_perfect_record_is_hundred(self):
        value = M.compute_mastery(
            scores=[10] * 10, covered_count=15, domain_total=15,
            mastered_count=5, ever_wrong_count=5,
            last_practiced_at=NOW, now=NOW,
        )
        assert value == 100

    def test_components_are_weighted(self):
        # 只留近期表现这一项（覆盖度 0、错题健康度 0）：0.6 × 0.5 = 0.3 → 30
        value = M.compute_mastery(
            scores=[5], covered_count=0, domain_total=100,
            mastered_count=0, ever_wrong_count=1,  # 曾入本且未掌握 → 健康度 0
            last_practiced_at=NOW, now=NOW,
        )
        assert value == 30

    def test_never_wrong_counts_as_healthy(self):
        # 与上一条同分，但从未入本 → 健康度按 1 计：0.6×0.5 + 0.15×1 = 0.45
        value = M.compute_mastery(
            scores=[5], covered_count=0, domain_total=100,
            mastered_count=0, ever_wrong_count=0,
            last_practiced_at=NOW, now=NOW,
        )
        assert value == 45

    def test_result_stays_in_range(self):
        for scores in ([], [0], [10] * 10):
            value = M.compute_mastery(
                scores=scores, covered_count=20, domain_total=5,
                mastered_count=9, ever_wrong_count=9,
                last_practiced_at=NOW, now=NOW,
            )
            assert 0 <= value <= 100


# ================================================================ C 接口层

API = "/api/v1/practice"

# (栈, 领域, 题干, 答案, rubric, 题型)
QUESTION_ROWS = [
    ("JAVA_BACKEND", "JVM", "JVM 内存结构是怎样的？", "堆、方法区、虚拟机栈", None, "SUBJECTIVE"),
    ("JAVA_BACKEND", "CONCURRENCY", "synchronized 的实现原理？", "监视器锁", None, "SUBJECTIVE"),
    ("BACKEND_COMMON", "REDIS", "设计一个日均千万请求的短链服务", "分层参考框架", '{"framework":"先拆读写"}', "SCENARIO"),
    ("BACKEND_COMMON", "MYSQL", "哪种隔离级别能防幻读？", "可重复读", None, "CHOICE"),
]


@pytest.fixture()
def questions() -> Generator[list[int], None, None]:
    """造 4 道题覆盖栈 / 领域 / 题型，返回 id 列表——抽题用例自备已知数据。

    两个坑都踩过，记在这里：
    ①**不能用 `db_session`**——那个 fixture 会清库（服务层用例专用），而本文件走 `client`
      （API 用例），清库会把刚注册的账号一并抹掉、后续请求全 401 + 80001；conftest 文件头
      写明「服务层用例用 `db_session`，API 用例用 `client`」，两者不可混用；
    ②**用完必须自己删**——`question` 表不随用例清空（conftest 要保留 589 道种子题库），
      造的数据不收走会一直累积，最终打挂 `test_seed_questions_fields` 的题库断言。
    """
    with SessionLocal() as session:
        rows = [
            Question(stack=s, direction=d, content=c, answer=a, rubric=r, qtype=q, source="BUILTIN")
            for s, d, c, a, r, q in QUESTION_ROWS
        ]
        session.add_all(rows)
        session.commit()
        ids = [row.id for row in rows]
    try:
        yield ids
    finally:
        # 按引用顺序清：结算未通过会写错题本、点评会写轮次，都会引用这些题，直接删题会被外键拦下
        with SessionLocal() as session:
            expanding = lambda sql: text(sql).bindparams(bindparam("ids", expanding=True))
            for table in ("practice_record", "practice_session", "wrong_question"):
                session.execute(
                    expanding(f"DELETE FROM {table} WHERE question_id IN :ids"), {"ids": ids}
                )
            session.execute(expanding("DELETE FROM question WHERE id IN :ids"), {"ids": ids})
            session.commit()


def _auth(account) -> dict[str, str]:
    """显式构造鉴权头。

    conftest 的 `client` 会把 Token 写进默认请求头，但本文件里带 `questions` fixture 的用例
    实测默认头不生效（POST 一律 401 + 80001），故一律显式传——显式也比隐式默认好读。
    """
    return {"Authorization": f"Bearer {account['token']}"}


def _open(client: TestClient, account, question_id: int, mode: str = "QUICK", time_limit=None):
    payload: dict = {"question_id": question_id, "mode": mode}
    if time_limit is not None:
        payload["time_limit"] = time_limit
    resp = client.post(f"{API}/sessions", json=payload, headers=_auth(account))
    assert resp.status_code == 201, resp.text  # 建资源返回 201
    return resp.json()["data"]


class TestPracticeMeta:
    def test_stacks_carry_domains(self, client: TestClient, account):
        data = client.get(f"{API}/meta").json()["data"]
        assert len(data["stacks"]) == 5
        assert all(stack["domains"] for stack in data["stacks"])

    def test_modes_carry_max_rounds(self, client: TestClient, account):
        data = client.get(f"{API}/meta").json()["data"]
        assert {m["value"]: m["max_rounds"] for m in data["modes"]} == {
            "QUICK": 1, "INTERVIEWER": 5, "COACH": 5, "DEBUG": 2, "FEYNMAN": 3,
        }

    def test_attack_faces_are_ordered_by_layer(self, client: TestClient, account):
        data = client.get(f"{API}/meta").json()["data"]
        assert [(f["value"], f["layer"]) for f in data["faces"]] == [
            ("BASIS", 1), ("BOUNDARY", 2), ("TRADEOFF", 3), ("LANDING", 4),
        ]

    def test_time_limits_are_the_four_gears(self, client: TestClient, account):
        data = client.get(f"{API}/meta").json()["data"]
        assert data["time_limits"] == [30, 60, 90, 120]


class TestPickQuestions:
    def _pick(self, client: TestClient, account, **payload):
        return client.post(f"{API}/questions", json=payload, headers=_auth(account))

    def test_picks_without_filters(self, client: TestClient, account, questions):
        data = self._pick(client, account, count=3).json()["data"]
        assert len(data["items"]) == 3

    def test_filters_by_stack(self, client: TestClient, account, questions):
        data = self._pick(client, account, stacks=["JAVA_BACKEND"], count=5).json()["data"]
        assert data["items"]
        assert all(item["stack"] == "JAVA_BACKEND" for item in data["items"])

    def test_filters_by_direction_and_qtype(self, client: TestClient, account, questions):
        data = self._pick(client, account, directions=["REDIS"], qtypes=["SCENARIO"]).json()["data"]
        assert [item["qtype"] for item in data["items"]] == ["SCENARIO"]

    def test_never_returns_answer_or_rubric(self, client: TestClient, account, questions):
        # 抽题不给答案（防止先看答案），场景题的 rubric 同样不下发
        data = self._pick(client, account, count=5).json()["data"]
        assert data["items"]
        for item in data["items"]:
            assert "answer" not in item
            assert "rubric" not in item

    def test_carries_domain_mastery(self, client: TestClient, account, questions):
        # 前端据此标「本题来自你的薄弱领域」；新账号没练过 → 0
        data = self._pick(client, account, count=1).json()["data"]
        assert data["items"][0]["mastery"] == 0

    def test_random_strategy_also_works(self, client: TestClient, account, questions):
        # RANDOM 是 SMART 的对照策略，同样可用（命中不足按实际数量返回、不报错）
        resp = self._pick(client, account, count=3, strategy="RANDOM")
        assert resp.status_code == 200
        assert len(resp.json()["data"]["items"]) == 3

    def test_rejects_invalid_strategy(self, client: TestClient, account, questions):
        resp = self._pick(client, account, strategy="WHATEVER")
        assert resp.status_code == 400
        assert resp.json()["code"] == 10001


class TestSessions:
    def test_open_returns_running_session(self, client: TestClient, account, questions):
        data = _open(client, account, questions[0], time_limit=60)
        assert data["status"] == "RUNNING"
        assert data["time_limit"] == 60
        assert data["round_index"] == 1

    def test_rejects_off_gear_time_limit(self, client: TestClient, account, questions):
        resp = client.post(
            f"{API}/sessions",
            json={"question_id": questions[0], "mode": "QUICK", "time_limit": 45},
            
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 10001

    def test_history_hides_score_until_finished(self, client: TestClient, account, questions):
        _open(client, account, questions[0])
        data = client.get(f"{API}/sessions").json()["data"]
        assert data["total"] == 1
        assert data["items"][0]["overall_score"] is None
        assert data["items"][0]["status"] == "RUNNING"

    def test_detail_carries_time_limit(self, client: TestClient, account, questions):
        """IS-38：回看要带 time_limit，续练据此恢复倒计时。"""
        session = _open(client, account, questions[0], time_limit=90)
        data = client.get(
            f"{API}/sessions/{session['session_id']}"
        ).json()["data"]
        assert data["time_limit"] == 90

    def test_detail_hides_reference_answer_while_running(self, client: TestClient, account, questions):
        session = _open(client, account, questions[0])
        data = client.get(
            f"{API}/sessions/{session['session_id']}"
        ).json()["data"]
        assert data["reference_answer"] is None  # 追问中给答案等于泄题

    def test_other_account_cannot_read(self, client: TestClient, account, make_account, questions):
        session = _open(client, account, questions[0])
        other = make_account("intruder_a")
        resp = client.get(f"{API}/sessions/{session['session_id']}", headers=other["headers"])
        assert resp.status_code == 404
        assert resp.json()["code"] == 10002


class TestFinish:
    def test_finish_is_idempotent(self, client: TestClient, account, questions):
        session = _open(client, account, questions[0])
        url = f"{API}/sessions/{session['session_id']}/finish"
        first = client.post(url).json()["data"]
        second = client.post(url).json()["data"]
        assert first["overall_score"] == second["overall_score"]
        assert first["passed"] == second["passed"]
        assert first["wrong_question_id"] == second["wrong_question_id"]

    def test_finish_other_account_is_404(self, client: TestClient, account, make_account, questions):
        session = _open(client, account, questions[0])
        other = make_account("intruder_b")
        resp = client.post(
            f"{API}/sessions/{session['session_id']}/finish", headers=other["headers"]
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == 10002

    def test_zero_round_settlement_scores_zero(self, client: TestClient, account, fake_llm_client, llm_configured):
        """IS-42：开一场后一轮未答直接结算 → 综合分 **0**（此前为 `null`，结算页曾渲染成空白）。

        `null` 只属于**未结算**的会话（历史列表项），两个值不要混。
        """
        item = _pick_one(client, account, "CHOICE")
        session_id = _open(client, account, item["id"], mode="QUICK")["session_id"]

        data = client.post(
            f"{API}/sessions/{session_id}/finish", headers=_auth(account)
        ).json()["data"]

        assert data["overall_score"] == 0, "零轮结算应为 0 分而非 null"
        assert data["passed"] is False
        assert data["wrong_question_id"] is None, "没答过不该入错题本"
        assert data["rounds"] == []

    def test_unfinished_session_score_stays_null(self, client: TestClient, account, fake_llm_client, llm_configured):
        """未结算的会话在历史列表里仍是 `null`——与零轮结算的 0 分是两回事。"""
        item = _pick_one(client, account, "CHOICE")
        _open(client, account, item["id"], mode="QUICK")

        row = client.get(f"{API}/sessions", headers=_auth(account)).json()["data"]["items"][0]
        assert row["overall_score"] is None
        assert row["status"] == "RUNNING"


# ================================================================ D 选择题（数据库设计 v1.15 / 接口文档 v1.29 §3.8）

PRACTICE_STREAM = "/api/v1/stream/practice-turn"


def _sse_events(body: str) -> list[tuple[str, dict]]:
    """解析响应体里的 SSE 事件序列（`event: <名>` 与 `data: <JSON>` 两行一块）。"""
    events = []
    for block in body.split("\n\n"):
        lines = block.strip().split("\n")
        if len(lines) < 2 or not lines[0].startswith("event: "):
            continue
        events.append((lines[0][len("event: ") :], json.loads(lines[1][len("data: ") :])))
    return events


def _sections(events: list[tuple[str, dict]]) -> dict[str, str]:
    """把带 `section` 的 `delta` 按段归并成 `{section: 全文}`（同段多个 delta 顺序拼接）。

    `section` 是**可选字段**——服务端指定的段（选择题的 `round_score` / `review`、参考答案、
    四维等）才带；AI 点评流本身按标题切段再下发，无标题时整段不带该字段，故此处跳过。
    """
    merged: dict[str, str] = {}
    for name, data in events:
        if name != "delta" or "section" not in data:
            continue
        merged[data["section"]] = merged.get(data["section"], "") + data["text"]
    return merged


def _choice_items(client: TestClient, account, count: int = 5) -> list[dict]:
    """抽 `count` 道选择题（用 RANDOM——SMART 的加权抽样会让断言不稳定）。"""
    resp = client.post(
        f"{API}/questions",
        json={"qtypes": ["CHOICE"], "count": count, "strategy": "RANDOM"},
        headers=_auth(account),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["items"]


def _correct_key(question_id: int, options: list[dict]) -> str:
    """按归一化匹配找出正确项的标识——答案在库里，抽题响应里没有。"""
    with SessionLocal() as session:
        answer = session.get(Question, question_id).answer
    return next(o["key"] for o in options if normalize_text(o["text"]) == normalize_text(answer))


class TestChoicePick:
    """选择题的抽题下发（接口文档 §3.8：`options` 仅 `CHOICE` 有值、不含正确标记）。"""

    def test_options_carry_keys_and_text_only(self, client: TestClient, account):
        """选项为 `[{key, text}]`、键 A~D 且**不含正确标记**——可原样渲染为可点选项而不泄题。"""
        items = _choice_items(client, account)
        assert items, "种子题库应含选择题"
        for item in items:
            assert item["qtype"] == "CHOICE"
            options = item["options"]
            assert isinstance(options, list) and len(options) == 4, options
            for opt in options:
                assert set(opt) == {"key", "text"}, f"选项带契约外字段：{opt}"
                assert opt["key"] and opt["text"]
            assert [o["key"] for o in options] == ["A", "B", "C", "D"]
            assert "answer" not in item, "抽题不得下发答案"

    def test_non_choice_options_is_null(self, client: TestClient, account):
        """其余题型的 `options` 为 `null`——前端据此决定作答区是点选还是文本框。"""
        resp = client.post(
            f"{API}/questions",
            json={"qtypes": ["SUBJECTIVE", "SCENARIO"], "count": 5, "strategy": "RANDOM"},
            headers=_auth(account),
        )
        items = resp.json()["data"]["items"]
        assert items, "种子题库应含主观题与场景题"
        for item in items:
            assert item["qtype"] != "CHOICE"
            assert item["options"] is None


class TestChoiceTurn:
    """选择题首次作答轮的规则判定（接口文档 §3.8 实现口径第 12 条：零 token 即时产出）。"""

    def _turn(self, client, account, question_id: int, *, mode: str = "QUICK", **payload):
        session = _open(client, account, question_id, mode=mode)
        resp = client.post(
            f"{PRACTICE_STREAM}",
            json={"session_id": session["session_id"], **payload},
            headers=_auth(account),
        )
        assert resp.status_code == 200, resp.text
        return session, _sse_events(resp.text)

    def test_correct_key_is_judged_without_llm(self, client, account, fake_llm_client):
        """提交正确标识 → 判对，且**整轮零 LLM 调用**（QUICK 仅一轮、收尾取题库答案）。"""
        item = _choice_items(client, account, count=1)[0]
        key = _correct_key(item["id"], item["options"])

        _, events = self._turn(client, account, item["id"], user_input=key)
        sections = _sections(events)

        assert "round_score" in sections and "review" in sections
        assert "答对了" in sections["round_score"]
        assert fake_llm_client.stream_calls == [], "规则判定不得调模型"
        assert fake_llm_client.json_calls == []

    def test_wrong_key_review_shows_correct_option(self, client, account, fake_llm_client):
        """答错时 `review` 给出正确选项（此反馈不属「追问中不给答案」的约束），同样零调用。"""
        item = _choice_items(client, account, count=1)[0]
        correct_key = _correct_key(item["id"], item["options"])
        wrong_key = next(o["key"] for o in item["options"] if o["key"] != correct_key)
        correct_text = next(o["text"] for o in item["options"] if o["key"] == correct_key)

        _, events = self._turn(client, account, item["id"], user_input=wrong_key)
        sections = _sections(events)

        assert "答错了" in sections["round_score"]
        assert correct_text in sections["review"], "点评要给出正确选项"
        assert fake_llm_client.stream_calls == []

    def test_illegal_key_is_judged_incorrect_not_rejected(self, client, account, fake_llm_client):
        """不在选项内的标识 → **判错而非报错**。"""
        item = _choice_items(client, account, count=1)[0]
        _, events = self._turn(client, account, item["id"], user_input="Z")

        assert "答错了" in _sections(events)["round_score"]
        assert fake_llm_client.stream_calls == []

    def test_stored_answer_is_expanded_option_text(self, client, account):
        """落库 `user_answer` 是**展开后的选项文本**——回看与追问上下文自然可读。"""
        item = _choice_items(client, account, count=1)[0]
        key = _correct_key(item["id"], item["options"])
        expected_text = next(o["text"] for o in item["options"] if o["key"] == key)

        session, _ = self._turn(client, account, item["id"], user_input=key)
        detail = client.get(
            f"{API}/sessions/{session['session_id']}", headers=_auth(account)
        ).json()["data"]

        assert detail["rounds"][0]["user_answer"] == expected_text

    def test_followup_turn_falls_back_to_llm(self, client, account, fake_llm_client, llm_configured):
        """追问轮回到开放作答 → 交 LLM 点评（规则判定只在首次作答轮生效）。"""
        item = _choice_items(client, account, count=1)[0]
        key = _correct_key(item["id"], item["options"])
        session, _ = self._turn(client, account, item["id"], mode="INTERVIEWER", user_input=key)
        before = len(fake_llm_client.stream_calls)

        resp = client.post(
            f"{PRACTICE_STREAM}",
            json={"session_id": session["session_id"], "user_input": "因为间隙锁挡住了插入"},
            headers=_auth(account),
        )
        assert resp.status_code == 200, resp.text
        assert len(fake_llm_client.stream_calls) > before, "追问轮应走 AI 点评"


# ================================================================ E 训练链路（开发计划步骤 13 测试任务）


def _pick_one(client: TestClient, account, qtype: str = "SUBJECTIVE") -> dict:
    resp = client.post(
        f"{API}/questions",
        json={"qtypes": [qtype], "count": 1, "strategy": "RANDOM"},
        headers=_auth(account),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["items"][0]


def _stream_turn(client: TestClient, account, session_id: int, **payload) -> list[tuple[str, dict]]:
    """走一轮 `/stream/practice-turn`，返回事件序列。"""
    resp = client.post(
        f"{PRACTICE_STREAM}", json={"session_id": session_id, **payload}, headers=_auth(account)
    )
    assert resp.status_code == 200, resp.text
    return _sse_events(resp.text)


def _done_extra(events: list[tuple[str, dict]]) -> dict:
    """取 `done` 事件的 `extra`——下一轮的层号与攻击面、以及本场是否该结算。"""
    for name, data in events:
        if name == "done":
            return data["extra"]
    raise AssertionError("事件流里没有 done")


def _finish(client: TestClient, account, session_id: int) -> dict:
    return client.post(f"{API}/sessions/{session_id}/finish", headers=_auth(account)).json()["data"]


class TestFollowUpChain:
    """追问链的推进与终止（接口文档 §3.8：层号与攻击面一一对应、四层封顶）。"""

    def _open(self, client, account, mode: str = "INTERVIEWER", **kw) -> int:
        item = _pick_one(client, account)
        return _open(client, account, item["id"], mode=mode, **kw)["session_id"]

    def test_layers_advance_in_fixed_order(self, client: TestClient, account, fake_llm_client, llm_configured):
        """`done.extra` 给「下一轮」的落点：1·BASIS → 2·BOUNDARY → 3·TRADEOFF → 4·LANDING。

        首轮是 `OPENING`（不算层），所以第 1 轮作答后落点是**第 1 层**而非第 2 层。
        """
        session_id = self._open(client, account)

        for expected_layer, expected_face in ((1, "BASIS"), (2, "BOUNDARY"), (3, "TRADEOFF"), (4, "LANDING")):
            extra = _done_extra(
                _stream_turn(client, account, session_id, user_input=f"第 {expected_layer} 次作答")
            )
            assert extra["layer"] == expected_layer
            assert extra["face"] == expected_face
            assert extra["should_finish"] is False, "还没追完，不该提示结算"

    def test_chain_terminates_after_four_layers(self, client: TestClient, account, fake_llm_client, llm_configured):
        """追满四层（`OPENING` + 四层追问 = 五轮）→ `should_finish=true` 且无下一轮。"""
        session_id = self._open(client, account)

        for _ in range(5):
            extra = _done_extra(_stream_turn(client, account, session_id, user_input="作答"))

        assert extra["should_finish"] is True
        assert extra["layer"] is None and extra["face"] is None

    def test_user_can_end_early(self, client: TestClient, account, fake_llm_client, llm_configured):
        """主动结束（`action=END`）→ 本场该结算了，不必追满四层。"""
        session_id = self._open(client, account)
        _stream_turn(client, account, session_id, user_input="第一轮作答")

        extra = _done_extra(_stream_turn(client, account, session_id, action="END"))
        assert extra["should_finish"] is True


class TestBreakPoint:
    """断点判定与 `break_face`（结算的纯计算口径）。"""

    def _open(self, client, account, mode: str = "INTERVIEWER", **kw) -> int:
        item = _pick_one(client, account)
        return _open(client, account, item["id"], mode=mode, **kw)["session_id"]

    def test_stuck_records_break_at_its_layer(self, client: TestClient, account, fake_llm_client, llm_configured):
        """第 2 轮（即四层里的第 1 层）交白卷 → 该轮记断点、`break_face` 落在 `BASIS`。"""
        session_id = self._open(client, account)
        _stream_turn(client, account, session_id, user_input="第一轮正常作答")
        _stream_turn(client, account, session_id, user_input="")  # 答不上

        data = _finish(client, account, session_id)

        assert data["rounds"][1]["is_break"] is True
        assert data["break_face"] == "BASIS", "断点应落在它发生的层级"

    def test_no_break_means_null_face(self, client: TestClient, account, fake_llm_client, llm_configured):
        """全程答得下来 → `break_face` 为 `null`（没有断点就没有层级）。"""
        session_id = self._open(client, account, mode="QUICK")
        _stream_turn(client, account, session_id, user_input="完整作答")

        data = _finish(client, account, session_id)
        assert all(r["is_break"] is False for r in data["rounds"])
        assert data["break_face"] is None

    def test_timeout_counts_as_break(self, client: TestClient, account, fake_llm_client, llm_configured):
        """限时内一字未写 → `timed_out=true` 且计断点（`timed_out` 由服务端按 `elapsed_ms` 推导）。"""
        session_id = self._open(client, account, mode="QUICK", time_limit=60)

        _stream_turn(client, account, session_id, user_input="", elapsed_ms=60_000, timed_out=True)
        detail = client.get(f"{API}/sessions/{session_id}", headers=_auth(account)).json()["data"]
        assert detail["rounds"][0]["timed_out"] is True

        data = _finish(client, account, session_id)
        assert data["rounds"][0]["is_break"] is True


class TestReferenceAnswerTiming:
    """参考答案的发放时机分模式（接口文档 §3.8：QUICK 轮内给，追问模式推迟到结算）。"""

    def test_quick_gives_it_in_the_turn(self, client: TestClient, account, fake_llm_client, llm_configured):
        """QUICK 只有一轮——轮内直接给参考答案。"""
        item = _pick_one(client, account)
        session_id = _open(client, account, item["id"], mode="QUICK")["session_id"]

        sections = _sections(_stream_turn(client, account, session_id, user_input="作答"))
        assert "reference_answer" in sections

    def test_follow_up_modes_withhold_until_finish(self, client: TestClient, account, fake_llm_client, llm_configured):
        """追问模式轮内不给（追问中给答案等于泄题），结算才给。"""
        item = _pick_one(client, account)
        session_id = _open(client, account, item["id"], mode="INTERVIEWER")["session_id"]

        sections = _sections(_stream_turn(client, account, session_id, user_input="作答"))
        assert "reference_answer" not in sections

        assert _finish(client, account, session_id)["reference_answer"]


class TestSmartPicking:
    """薄弱优先选题（契约：`(100 - 掌握度) / 50 × 练习历史系数` 加权抽样）。

    拿 `OS` 与 `NETWORK` 做对照——种子题库里两者**题量相同**（各 45 道），
    领域占比的差异只可能来自权重，不受题库基数干扰。
    """

    @pytest.fixture()
    def mastery_marks(self, client: TestClient, account) -> tuple[str, str]:
        """把两个领域分别标成掌握度 0 与 100，返回 (弱, 强)。"""
        weak, strong = "OS", "NETWORK"
        with SessionLocal() as session:
            session.add_all(
                [
                    DomainMastery(
                        user_id=account["id"], stack="COMMON", direction=weak,
                        mastery=0, answered_count=0, covered_count=0,
                    ),
                    DomainMastery(
                        user_id=account["id"], stack="COMMON", direction=strong,
                        mastery=100, answered_count=0, covered_count=0,
                    ),
                ]
            )
            session.commit()
        return weak, strong

    def _draw(self, client: TestClient, account, strategy: str, marks: tuple[str, str], times: int) -> list[str]:
        weak, strong = marks
        return [
            client.post(
                f"{API}/questions",
                json={"directions": [weak, strong], "count": 1, "strategy": strategy},
                headers=_auth(account),
            ).json()["data"]["items"][0]["direction"]
            for _ in range(times)
        ]

    def test_smart_never_draws_a_mastered_direction(self, client: TestClient, account, mastery_marks):
        """掌握度 100 的领域权重为 0——`SMART` 抽样里绝不出现（确定性断言，非统计）。"""
        weak, _ = mastery_marks
        assert set(self._draw(client, account, "SMART", mastery_marks, 10)) == {weak}

    def test_random_is_unaffected_by_mastery(self, client: TestClient, account, mastery_marks):
        """`RANDOM` 是纯随机对照——掌握度不该左右它，两个领域都会出现。"""
        _, strong = mastery_marks
        assert strong in self._draw(client, account, "RANDOM", mastery_marks, 15)


# ================================================================ F 追问轮的点选（《选择题作答形态规范》）

_FALLBACK_OPTIONS = [
    {"key": "A", "text": "连接池被打满"},
    {"key": "B", "text": "GC 停顿变长"},
    {"key": "C", "text": "网络抖动"},
]


def _followup_chunks(*, answer: str = "A", options: list | None = None, explain: str = "解析占位") -> list[str]:
    """构造带选项的追问输出——AI 的真实产出形态（`app/prompts.py` 的追问模板）。

    段标题是**中文**「下一轮选项」（内部 section 名才是 `next_choices`），JSON 包在代码块里；
    服务端按段切分后：题干走 `next_question` 流式下发，选项**剥离正确项**后走 `next_choices` 下发，
    完整版落库供下一轮判定。
    """
    payload = {"options": options if options is not None else _FALLBACK_OPTIONS, "answer": answer, "explain": explain}
    return [
        "## 追问\n如果并发再翻十倍，最先崩的是哪一环？\n\n",
        f"## 下一轮选项\n```json\n{json.dumps(payload, ensure_ascii=False)}\n```\n",
    ]


class TestFollowUpChoices:
    """追问轮的点选作答（规范：`docs/superpowers/specs/2026-09-29-选择题作答形态规范-design.md`）。

    追问的选项由 AI 随追问下发（`next_choices` 段）：合法则下发剥离正确项的那份、完整版落库；
    不合法（键不连续、项数越界、`answer` 越界等）则**整段丢弃**，该轮降级回开放作答。
    """

    def _to_followup(self, client: TestClient, account, fake_llm_client) -> tuple[int, list[tuple[str, dict]]]:
        """开一场选择题、答完首轮——服务端据此产出追问（此时 fake 的输出带选项）。"""
        item = _pick_one(client, account, "CHOICE")
        session_id = _open(client, account, item["id"], mode="INTERVIEWER")["session_id"]
        return session_id, _stream_turn(client, account, session_id, user_input="A")

    def test_followup_turn_carries_choices(self, client: TestClient, account, fake_llm_client, llm_configured):
        """追问轮下发 `next_choices` 段：键从 A 连续，且**不含正确项与解析**。"""
        fake_llm_client.chunks = _followup_chunks()
        _, events = self._to_followup(client, account, fake_llm_client)

        payload = None
        for name, data in events:
            if name == "delta" and data.get("section") == "next_choices":
                payload = data["text"]
        assert payload is not None, "追问轮应下发 next_choices 段"

        options = json.loads(payload)["options"]
        assert 3 <= len(options) <= 4, f"选项数应为 3~4，实际 {len(options)}"
        assert [opt["key"] for opt in options] == list("ABC"[: len(options)])
        for opt in options:
            assert set(opt) == {"key", "text"}, f"下发不得含正确项或解析：{opt}"

    def test_followup_choice_is_rule_judged(self, client: TestClient, account, fake_llm_client, llm_configured):
        """追问轮提交选项标识 → 服务端规则判定、即时给对错（与首轮同形）。"""
        fake_llm_client.chunks = _followup_chunks(answer="A")
        session_id, _ = self._to_followup(client, account, fake_llm_client)

        sections = _sections(_stream_turn(client, account, session_id, user_input="A"))
        score = sections.get("round_score", "")
        assert "答对了" in score, f"追问轮的判定应由服务端拼装，实际：{score[:60]}"

    def test_invalid_choices_fall_back_to_open_answer(self, client: TestClient, account, fake_llm_client, llm_configured):
        """选项不合法（键不连续）→ **整段不下发**，该轮回到开放作答（降级路径）。"""
        fake_llm_client.chunks = _followup_chunks(
            options=[{"key": "A", "text": "一"}, {"key": "C", "text": "三"}, {"key": "D", "text": "四"}]
        )
        _, events = self._to_followup(client, account, fake_llm_client)

        sections = [data.get("section") for name, data in events if name == "delta"]
        assert "next_choices" not in sections, "不合法的选项段不得下发"

    def test_answer_key_out_of_range_falls_back(self, client: TestClient, account, fake_llm_client, llm_configured):
        """`answer` 不在选项内 → 同样降级（不合法一律丢弃）。"""
        fake_llm_client.chunks = _followup_chunks(answer="Z")
        _, events = self._to_followup(client, account, fake_llm_client)

        sections = [data.get("section") for name, data in events if name == "delta"]
        assert "next_choices" not in sections


class TestChoiceModeGuards:
    """选择题与不搭模式的互斥（规范 §2.5：挑错 / 费曼不抽、也不接受选择题）。"""

    def test_debug_mode_rejects_choice_question(self, client: TestClient, account, fake_llm_client, llm_configured):
        """挑错模式 + 选择题 → 开一场直接 400 + 10001（训练形式与点选不搭）。"""
        item = _pick_one(client, account, "CHOICE")

        resp = client.post(
            f"{API}/sessions",
            json={"question_id": item["id"], "mode": "DEBUG"},
            headers=_auth(account),
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 10001

    def test_feynman_mode_rejects_choice_question(self, client: TestClient, account, fake_llm_client, llm_configured):
        """费曼复述 + 选择题 → 同样拒绝。"""
        item = _pick_one(client, account, "CHOICE")

        resp = client.post(
            f"{API}/sessions",
            json={"question_id": item["id"], "mode": "FEYNMAN"},
            headers=_auth(account),
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == 10001

    def test_draw_with_debug_mode_excludes_choice(self, client: TestClient, account):
        """抽题带 `mode=DEBUG` → 不返回选择题（从源头不抽，而非等到开一场才报错）。"""
        resp = client.post(
            f"{API}/questions",
            json={"mode": "DEBUG", "qtypes": ["CHOICE"], "count": 3, "strategy": "RANDOM"},
            headers=_auth(account),
        )
        assert resp.json()["data"]["items"] == [], "DEBUG 模式不该抽出选择题"

    def test_draw_without_mode_still_returns_choice(self, client: TestClient, account):
        """不传 `mode` 时不排除——老调用方行为不变。"""
        resp = client.post(
            f"{API}/questions",
            json={"qtypes": ["CHOICE"], "count": 2, "strategy": "RANDOM"},
            headers=_auth(account),
        )
        assert resp.json()["data"]["items"], "不传 mode 时选择题照常可抽"
