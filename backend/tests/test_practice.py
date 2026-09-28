"""八股陪练（FR-009）：训练系统的用例。

分两块：**纯函数模块**（轮次状态机 `practice_flow` / 掌握度 `mastery`）不经 HTTP、不碰库，
按系统设计 §8 的「可脱离 HTTP 直接单测、全分支覆盖」写；**接口层**走 TestClient + FakeLLM。

命名与断言口径对齐 `docs/05-测试文档/测试计划.md` 的 TC-09 / TC-10 / TC-34 / TC-44 与
步骤 13 新增项（追问链推进与终止、结算幂等与断点判定、薄弱优先选题、限时超时）。
"""

from datetime import datetime, timedelta
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.database import SessionLocal

from app.models.enums import AttackFace, PracticeMode
from app.models.question import Question
from app.utils import mastery as M
from app.utils.practice_flow import is_break, is_stuck, judge_passed, next_turn

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
