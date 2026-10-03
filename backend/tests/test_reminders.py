"""提醒测试：TC-21（纯规则判定三类边界）+ TC-22（文案回退与任务互斥）+ TC-30（生成幂等与已读）。

覆盖：三类判定的边界（满 3 天 / 未满 / 有未来安排 / 已结束；错题到期 / 未到期 / 已掌握；
7 日窗口内外 / 已过时点）、未配 AI 时模板文案精确断言、同日幂等与增量补生成、任务互斥
（持锁跳过不排队）、列表过滤与排序口径、标记已读幂等与跨账号隔离、`/reminders/run` 多账号遍历。

口径出处：接口文档 v1.42 §3.14 实现口径 9 条、系统设计 v1.39 §5.5（判定阈值与 /overview 同源）。
"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Application, Question, Reminder, WrongQuestion
from app.models.enums import ApplicationStatus, ReminderType, WrongSourceType
from app.services import reminder_engine

API = "/api/v1"
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
    """造一条错题：due_days_ago 天前到期（负数为尚未到期）；mastered=True 为已掌握。

    `wrong_question` 有 `UNIQUE(user_id, question_id)`（同账号一题只入本一次），
    故按该账号已有条数错开取题——否则同一用例内加第二条会撞唯一约束。
    """
    used = db.scalar(
        select(func.count()).select_from(WrongQuestion).where(WrongQuestion.user_id == user_id)
    )
    question_id = db.scalars(
        select(Question.id).order_by(Question.id).offset(used).limit(1)
    ).one_or_none()
    assert question_id is not None, "题库题数不足——测试库应保留种子题库"
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


def _question_content(db, user_id: int) -> str:
    """取该账号最新一条错题对应的题干（用于模板文案的摘录断言）。"""
    row = db.execute(
        select(Question.content)
        .join(WrongQuestion, WrongQuestion.question_id == Question.id)
        .where(WrongQuestion.user_id == user_id)
        .order_by(WrongQuestion.id.desc())
        .limit(1)
    ).scalar_one()
    return row


def _run(client: TestClient) -> int:
    """触发手动执行，返回本次新增条数。"""
    resp = client.post(f"{API}/reminders/run")
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["generated"]


def _list(client: TestClient, headers: dict | None = None, **params) -> dict:
    resp = client.get(f"{API}/reminders", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


# ---------- TC-21：三类判定的边界 ----------


def test_follow_up_boundary(client: TestClient, account) -> None:
    """满 3 天无进展才命中：恰满命中、未满不命中、已安排未来事件不命中、已结束不命中。"""
    with SessionLocal() as db:
        _add_application(db, account["id"], company="满三天", applied_days_ago=3)
        _add_application(db, account["id"], company="差一天", applied_days_ago=2)
        _add_application(
            db, account["id"], company="有面试", applied_days_ago=5, next_event_in_days=1
        )
        _add_application(
            db,
            account["id"],
            company="已结束",
            status=ApplicationStatus.CLOSED,
            applied_days_ago=10,
        )
        db.commit()

    _run(client)

    items = _list(client)["items"]
    follow_ups = [i for i in items if i["reminder_type"] == "FOLLOW_UP"]
    assert len(follow_ups) == 1
    assert "满三天" in follow_ups[0]["content"]


def test_wrong_question_boundary(client: TestClient, account) -> None:
    """错题到期才命中：到期未掌握命中、未到期不命中、已掌握不命中。"""
    with SessionLocal() as db:
        _add_wrong_question(db, account["id"], due_days_ago=1)
        _add_wrong_question(db, account["id"], due_days_ago=-1)
        _add_wrong_question(db, account["id"], due_days_ago=3, mastered=True)
        db.commit()

    _run(client)

    items = _list(client)["items"]
    wrongs = [i for i in items if i["reminder_type"] == "WRONG_QUESTION"]
    assert len(wrongs) == 1


def test_interview_window(client: TestClient, account) -> None:
    """7 日内待笔试/面试才命中：窗口内命中、超 7 日不命中、时点已过不命中、已结束不命中。"""
    with SessionLocal() as db:
        _add_application(db, account["id"], company="三天后", next_event_in_days=3)
        _add_application(db, account["id"], company="八天后", next_event_in_days=8)
        _add_application(db, account["id"], company="昨天", next_event_in_days=-1)
        _add_application(
            db,
            account["id"],
            company="结束但有安排",
            status=ApplicationStatus.CLOSED,
            next_event_in_days=2,
        )
        db.commit()

    _run(client)

    items = _list(client)["items"]
    interviews = [i for i in items if i["reminder_type"] == "INTERVIEW"]
    assert len(interviews) == 1
    assert "三天后" in interviews[0]["content"]


# ---------- TC-22：文案回退与任务互斥 ----------


def test_templates_exact(client: TestClient, account) -> None:
    """未配 AI 时三类文案为固定模板，可逐字断言（口径：接口文档 v1.42 §3.14）。"""
    with SessionLocal() as db:
        _add_application(db, account["id"], company="甲公司", position="Java 开发",
                         status=ApplicationStatus.INTERVIEW, next_event_in_days=2)
        _add_application(db, account["id"], company="乙公司", position="后端开发",
                         applied_days_ago=4)
        _add_wrong_question(db, account["id"], due_days_ago=1)
        excerpt = _question_content(db, account["id"]).strip().replace("\n", " ")[:30]
        db.commit()

    _run(client)

    by_type = {i["reminder_type"]: i["content"] for i in _list(client)["items"]}
    event_at = (TODAY + timedelta(days=2)).strftime("%m-%d %H:%M")
    assert by_type["INTERVIEW"] == f"甲公司 · Java 开发 将于 {event_at} 进行笔试/面试，注意提前准备"
    assert by_type["FOLLOW_UP"] == "乙公司 · 后端开发 已投递 4 天仍无进展，建议主动跟进"
    assert by_type["WRONG_QUESTION"] == f"错题「{excerpt}」已到复习时间，去复习一下加深记忆"


def test_run_mutex_skips_when_locked(client: TestClient, account) -> None:
    """任务互斥：执行中再次触发返回 0（不报错、不排队）——定时与手动触发共用入口。"""
    with SessionLocal() as db:
        _add_application(db, account["id"], applied_days_ago=5)
        db.commit()

    assert reminder_engine._RUN_LOCK.acquire(blocking=False)
    try:
        assert _run(client) == 0
        assert _list(client)["total"] == 0  # 被跳过的触发不应生成任何提醒
    finally:
        reminder_engine._RUN_LOCK.release()

    assert _run(client) == 1  # 锁释放后恢复正常


# ---------- TC-30：生成幂等与已读 ----------


def test_run_idempotent_then_incremental(client: TestClient, account) -> None:
    """同日同对象不重复生成：重复触发 0；新到期对象增量补生成。"""
    with SessionLocal() as db:
        _add_application(db, account["id"], applied_days_ago=5)
        db.commit()

    assert _run(client) == 1
    assert _run(client) == 0
    assert _list(client)["total"] == 1

    with SessionLocal() as db:
        _add_wrong_question(db, account["id"], due_days_ago=1)
        db.commit()

    assert _run(client) == 1  # 只补新增的错题，已生成的跟进不重复
    assert _list(client)["total"] == 2


def test_check_idempotent_and_isolated(client: TestClient, account, make_account) -> None:
    """标记已读：重复标记仍 200；不存在 / 跨账号一律 404 + 10002（不可区分）。"""
    with SessionLocal() as db:
        _add_application(db, account["id"], applied_days_ago=5)
        db.commit()
    _run(client)
    reminder_id = _list(client)["items"][0]["id"]

    first = client.put(f"{API}/reminders/{reminder_id}/check")
    second = client.put(f"{API}/reminders/{reminder_id}/check")
    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["data"] is None
    assert _list(client, checked="true")["total"] == 1

    other = make_account("reminder_other")
    cross = client.put(f"{API}/reminders/{reminder_id}/check", headers=other["headers"])
    missing = client.put(f"{API}/reminders/{reminder_id + 9999}/check")
    assert cross.status_code == 404 and cross.json()["code"] == 10002
    assert missing.status_code == 404 and missing.json()["code"] == 10002


def test_run_covers_all_accounts(client: TestClient, account, make_account) -> None:
    """`/reminders/run` 遍历全部账号：`generated` 为全站新增总数，各账号列表互不可见。"""
    other = make_account("reminder_second")
    with SessionLocal() as db:
        _add_application(db, account["id"], applied_days_ago=5)
        _add_application(db, other["id"], applied_days_ago=6)
        db.commit()

    assert _run(client) == 2

    assert _list(client)["total"] == 1
    assert _list(client, headers=other["headers"])["total"] == 1


# ---------- TC-30：列表口径与参数校验 ----------


def test_list_filters_and_order(client: TestClient, account) -> None:
    """列表：`date` 恰好该日 / `checked` 过滤 / `remind_date` 倒序同日 `id` 倒序 / `ref_type` 恒 null。"""
    with SessionLocal() as db:
        for i, (day_offset, checked) in enumerate(
            [(0, 0), (0, 0), (1, 1), (2, 0)], start=1
        ):
            db.add(
                Reminder(
                    user_id=account["id"],
                    reminder_type=ReminderType.FOLLOW_UP.value,
                    ref_id=100 + i,
                    content=f"第 {i} 条",
                    remind_date=TODAY.date() - timedelta(days=day_offset),
                    checked=checked,
                )
            )
        db.commit()

    all_rows = _list(client, page_size=50)
    assert all_rows["total"] == 4
    assert [i["content"] for i in all_rows["items"]] == ["第 2 条", "第 1 条", "第 3 条", "第 4 条"]
    assert all(i["ref_type"] is None for i in all_rows["items"])
    assert all(isinstance(i["checked"], bool) for i in all_rows["items"])

    today_rows = _list(client, date=TODAY.date().isoformat())
    assert today_rows["total"] == 2

    unchecked = _list(client, checked="false")
    assert unchecked["total"] == 3
    assert all(i["checked"] is False for i in unchecked["items"])


def test_list_param_validation(client: TestClient) -> None:
    """参数校验先于业务：`page_size` 越界、非法日期 → 10001（普通响应体，非 SSE 语义）。"""
    for params in (
        {"page_size": 0},
        {"page_size": 51},
        {"page": 0},
        {"date": "2026-13-99"},
    ):
        resp = client.get(f"{API}/reminders", params=params)
        assert resp.status_code == 400, f"{params} → {resp.status_code}"
        assert resp.json()["code"] == 10001, f"{params} → {resp.json()}"


def test_requires_token(anon_client: TestClient) -> None:
    """未带 Token → 401 + 80001（列表 / 标记已读受保护）。"""
    assert anon_client.get(f"{API}/reminders").status_code == 401
    assert anon_client.put(f"{API}/reminders/1/check").status_code == 401
    assert anon_client.get(f"{API}/reminders").json()["code"] == 80001


@pytest.mark.xfail(
    reason="IS-62：/reminders/run 漏挂鉴权依赖，无 Token 返回 200（接口文档 §1.1 要求 401 + 80001）；后端修复后摘标",
    strict=True,
)
def test_run_requires_token(anon_client: TestClient) -> None:
    """手动触发端点同受鉴权保护（接口文档 §1.1：除三个白名单外全部接口需 Token）。"""
    assert anon_client.post(f"{API}/reminders/run").status_code == 401
