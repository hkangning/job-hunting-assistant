"""今日概览测试：TC-27（`GET /overview` 聚合）+ 接口文档 v1.14 §3.4「区块判定口径」四条。

覆盖：鉴权与字段恒返回、投递各状态计数（无记录补 0）、待面试/笔试的 7 日窗口与升序、
3 天无进展跟进的阈值与「已安排下一步视为有进展」、错题到期数（排除已掌握）、
个人中心 `stats` 三项计数与跨账号隔离、校招情报四项在校招功能落地前固定为空值。

口径出处：接口文档 v1.14 §3.4「区块判定口径」（步骤 9 后端落地时细化的实现细则）。
"""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Application, InterviewSession, Question, WrongQuestion
from app.models.enums import ApplicationStatus, SessionStatus, WrongSourceType

API = "/api/v1/overview"
TODAY = datetime.now()


def _add_application(
    db,
    user_id: int,
    *,
    company: str = "某公司",
    position: str = "后端开发",
    status: ApplicationStatus = ApplicationStatus.APPLIED,
    applied_days_ago: int = 0,
    next_event_in_days: float | None = None,
) -> Application:
    """造一条投递：applied_days_ago 天前投递；next_event_in_days=None 表示未安排下一步。"""
    app = Application(
        user_id=user_id,
        company=company,
        position=position,
        status=status.value,
        applied_at=TODAY - timedelta(days=applied_days_ago),
        next_event_at=(
            TODAY + timedelta(days=next_event_in_days) if next_event_in_days is not None else None
        ),
    )
    db.add(app)
    db.flush()
    return app


def _add_wrong_question(db, user_id: int, *, due_days_ago: int = 1, mastered: bool = False) -> None:
    """造一条错题：due_days_ago 天前到期（负数 = 尚未到期）；mastered=True 为已掌握。

    `wrong_question` 有 `UNIQUE(user_id, question_id)`（同账号一题只入本一次，见数据库设计 §3），
    故按该账号已有条数**错开取题**——否则同一用例内加第二条会撞唯一约束。
    """
    used = db.scalar(
        select(func.count()).select_from(WrongQuestion).where(WrongQuestion.user_id == user_id)
    )
    question_id = db.scalars(
        select(Question.id).order_by(Question.id).offset(used).limit(1)
    ).one_or_none()
    assert question_id is not None, "题库题数不足——测试库应保留种子题库（585 题）"
    db.add(
        WrongQuestion(
            user_id=user_id,
            question_id=question_id,
            source_type=WrongSourceType.PRACTICE.value,
            next_review_at=TODAY - timedelta(days=due_days_ago),
            mastered_at=TODAY if mastered else None,
        )
    )
    db.flush()


def test_overview_requires_token(anon_client: TestClient) -> None:
    """未带 Token → 401 + 80001（概览与其他业务接口同等受保护）。"""
    resp = anon_client.get(API)
    assert resp.status_code == 401
    assert resp.json()["code"] == 80001


def test_overview_all_fields_always_present(client: TestClient) -> None:
    """9 个字段恒返回：账号无任何数据时也是 `[]` / `0` / `null`，不是缺字段。"""
    data = client.get(API).json()["data"]

    assert set(data) == {
        "upcoming_events",
        "application_stats",
        "follow_ups",
        "wrong_question_count",
        "campus_events",
        "last_crawl_at",
        "top_job_postings",
        "match_reminder_count",
        "stats",
    }
    assert data["upcoming_events"] == []
    assert data["follow_ups"] == []
    assert data["wrong_question_count"] == 0
    assert set(data["application_stats"]) == {"APPLIED", "WRITTEN", "INTERVIEW", "OFFER", "CLOSED"}
    assert data["stats"] == {
        "application_count": 0,
        "wrong_question_count": 0,
        "interview_count": 0,
    }


def test_campus_fields_empty_until_campus_module(client: TestClient) -> None:
    """校招情报四项在步骤 21~22 落地前固定为空值（数据源 `crawl_source` / `job_posting` 尚未建）。"""
    data = client.get(API).json()["data"]

    assert data["campus_events"] == []
    assert data["top_job_postings"] == []
    assert data["match_reminder_count"] == 0
    assert data["last_crawl_at"] is None


def test_application_stats_counts_by_status(client: TestClient, account) -> None:
    """各状态计数正确，且**无记录的状态补 0**（不是缺键）。"""
    with SessionLocal() as db:
        for _ in range(3):
            _add_application(db, account["id"], status=ApplicationStatus.APPLIED)
        _add_application(db, account["id"], status=ApplicationStatus.INTERVIEW)
        _add_application(db, account["id"], status=ApplicationStatus.CLOSED)
        db.commit()

    stats = client.get(API).json()["data"]["application_stats"]

    assert stats == {"APPLIED": 3, "WRITTEN": 0, "INTERVIEW": 1, "OFFER": 0, "CLOSED": 1}


def test_stats_counts_include_all_statuses_and_are_per_account(
    client: TestClient, account, make_account
) -> None:
    """个人中心 `stats`：投递数**含已结束**、错题数为总数、面试数为会话数；且**按账号隔离**。"""
    other = make_account("other_stats")
    with SessionLocal() as db:
        _add_application(db, account["id"], status=ApplicationStatus.CLOSED)  # 已结束也计入
        _add_application(db, account["id"], status=ApplicationStatus.APPLIED)
        _add_wrong_question(db, account["id"], due_days_ago=-5)  # 未到期也算「总数」
        _add_wrong_question(db, account["id"], due_days_ago=1, mastered=True)  # 已掌握也算
        db.add(
            InterviewSession(
                user_id=account["id"],
                company="甲公司",
                position="后端开发",
                direction="JAVA",
                status=SessionStatus.ACTIVE.value,
            )
        )
        # 另一账号的数据不得计入
        _add_application(db, other["id"])
        _add_wrong_question(db, other["id"], due_days_ago=1)
        db.commit()

    stats = client.get(API).json()["data"]["stats"]

    assert stats == {"application_count": 2, "wrong_question_count": 2, "interview_count": 1}


def test_upcoming_events_window_and_order(client: TestClient, account) -> None:
    """待面试/笔试：仅「未结束 + 当前时间起 7 日内」，按时间升序；已结束/已过时点/超窗口均排除。"""
    with SessionLocal() as db:
        _add_application(
            db, account["id"], company="三天后", status=ApplicationStatus.INTERVIEW,
            next_event_in_days=3,
        )
        _add_application(
            db, account["id"], company="明天", status=ApplicationStatus.WRITTEN,
            next_event_in_days=1,
        )
        _add_application(  # 已结束——即便有未来时点也不展示
            db, account["id"], company="已结束", status=ApplicationStatus.CLOSED,
            next_event_in_days=2,
        )
        _add_application(  # 时点已过
            db, account["id"], company="已过时点", status=ApplicationStatus.INTERVIEW,
            next_event_in_days=-1,
        )
        _add_application(  # 超出 7 日窗口
            db, account["id"], company="十天后", status=ApplicationStatus.INTERVIEW,
            next_event_in_days=10,
        )
        _add_application(db, account["id"], company="无安排", status=ApplicationStatus.APPLIED)
        db.commit()

    events = client.get(API).json()["data"]["upcoming_events"]

    assert [e["company"] for e in events] == ["明天", "三天后"]  # 升序
    assert events[0]["status"] == "WRITTEN"
    assert {"application_id", "company", "position", "event_at", "status"} <= set(events[0])


def test_follow_ups_threshold_status_and_order(client: TestClient, account) -> None:
    """跟进提醒：满 3 天 + 状态仍处 APPLIED/WRITTEN + **未安排未来的笔试/面试**，按 days 降序。"""
    with SessionLocal() as db:
        _add_application(db, account["id"], company="拖了五天", applied_days_ago=5)
        _add_application(db, account["id"], company="刚好三天", applied_days_ago=3)
        _add_application(db, account["id"], company="才两天", applied_days_ago=2)  # 未满 3 天
        _add_application(  # 已进入面试——不属「该跟进」
            db, account["id"], company="面试中", status=ApplicationStatus.INTERVIEW,
            applied_days_ago=9,
        )
        _add_application(  # 已安排明天的笔试——视为有进展
            db, account["id"], company="已安排下一步", applied_days_ago=8,
            next_event_in_days=1,
        )
        _add_application(  # 安排已过——仍算无进展
            db, account["id"], company="安排已过", applied_days_ago=6,
            next_event_in_days=-1,
        )
        db.commit()

    follow_ups = client.get(API).json()["data"]["follow_ups"]

    assert [f["company"] for f in follow_ups] == ["安排已过", "拖了五天", "刚好三天"]
    assert [f["days"] for f in follow_ups] == [6, 5, 3]  # days 降序
    assert {"application_id", "company", "position", "applied_at", "days"} <= set(follow_ups[0])


def test_wrong_question_count_excludes_mastered_and_future(client: TestClient, account) -> None:
    """错题到期数：`next_review_at ≤ 现在` **且未掌握**；已掌握与未到期均不计入。"""
    with SessionLocal() as db:
        _add_wrong_question(db, account["id"], due_days_ago=2)  # 到期未复习——计入
        _add_wrong_question(db, account["id"], due_days_ago=5)  # 计入
        _add_wrong_question(db, account["id"], due_days_ago=1, mastered=True)  # 已掌握——不计
        _add_wrong_question(db, account["id"], due_days_ago=-3)  # 尚未到期——不计
        db.commit()

    data = client.get(API).json()["data"]

    assert data["wrong_question_count"] == 2
    # 与 stats 的总数语义不同：总数不分到期与掌握，这里 4 条全算
    assert data["stats"]["wrong_question_count"] == 4
