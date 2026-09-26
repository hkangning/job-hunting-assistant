"""今日概览聚合服务：面试提醒、投递统计、跟进提醒与个人中心计数（FR-001、FR-013）。

纯 SQL 规则聚合、不调 LLM；数据一律按登录账号过滤（系统设计 3.6）。
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Application, InterviewSession, WrongQuestion
from app.models.enums import ApplicationStatus
from app.schemas.overview import (
    ApplicationStats,
    FollowUpItem,
    OverviewData,
    OverviewStats,
    UpcomingEventItem,
)

UPCOMING_WINDOW_DAYS = 7  # 「待面试/笔试」时间窗（接口文档 3.4）
FOLLOW_UP_MIN_DAYS = 3  # 「无进展」判定阈值：投递满 3 天
# 计入跟进的早期状态：尚未进入面试环节（已获 offer / 已结束不属于「该跟进」）
FOLLOW_UP_STATUSES = (ApplicationStatus.APPLIED, ApplicationStatus.WRITTEN)


def build_overview(db: Session, user_id: int) -> OverviewData:
    """聚合当前账号的今日概览数据。"""
    now = datetime.now()
    return OverviewData(
        upcoming_events=_upcoming_events(db, user_id, now),
        application_stats=_application_stats(db, user_id),
        follow_ups=_follow_ups(db, user_id, now),
        wrong_question_count=_due_wrong_question_count(db, user_id, now),
        # 校招情报四项的数据源（crawl_source / job_posting / subscription）属步骤 21~22，落地前固定空值
        campus_events=[],
        last_crawl_at=None,
        top_job_postings=[],
        match_reminder_count=0,
        stats=_stats(db, user_id),
    )


def _upcoming_events(db: Session, user_id: int, now: datetime) -> list[UpcomingEventItem]:
    """7 日内待笔试/面试：状态未结束、时间点在未来，按时间升序。"""
    rows = (
        db.execute(
            select(Application)
            .where(
                Application.user_id == user_id,
                Application.status != ApplicationStatus.CLOSED,
                Application.next_event_at.is_not(None),
                Application.next_event_at >= now,
                Application.next_event_at <= now + timedelta(days=UPCOMING_WINDOW_DAYS),
            )
            .order_by(Application.next_event_at.asc(), Application.id.asc())
        )
        .scalars()
        .all()
    )
    return [
        UpcomingEventItem(
            application_id=app.id,
            company=app.company,
            position=app.position,
            event_at=app.next_event_at,
            status=ApplicationStatus(app.status),
        )
        for app in rows
    ]


def _application_stats(db: Session, user_id: int) -> ApplicationStats:
    """投递各状态计数（GROUP BY status），无记录的状态补 0。"""
    rows = db.execute(
        select(Application.status, func.count())
        .where(Application.user_id == user_id)
        .group_by(Application.status)
    ).all()
    counts = {status.value: 0 for status in ApplicationStatus}
    counts.update({status: count for status, count in rows})
    return ApplicationStats(**counts)


def _follow_ups(db: Session, user_id: int, now: datetime) -> list[FollowUpItem]:
    """3 天无进展：状态仍处早期且未安排未来的笔试/面试（已安排下一步的视为有进展），按已过天数降序。"""
    rows = (
        db.execute(
            select(Application)
            .where(Application.user_id == user_id, Application.status.in_(FOLLOW_UP_STATUSES))
            .order_by(Application.applied_at.asc(), Application.id.asc())
        )
        .scalars()
        .all()
    )
    items: list[FollowUpItem] = []
    for app in rows:
        days = (now.date() - app.applied_at.date()).days
        if days < FOLLOW_UP_MIN_DAYS:
            continue
        if app.next_event_at is not None and app.next_event_at >= now:
            continue
        items.append(
            FollowUpItem(
                application_id=app.id,
                company=app.company,
                position=app.position,
                applied_at=app.applied_at.date(),
                days=days,
            )
        )
    return items


def _due_wrong_question_count(db: Session, user_id: int, now: datetime) -> int:
    """到期未复习错题数：next_review_at ≤ 当前时间且未掌握（SRS 4.1 复习规则）。"""
    return db.execute(
        select(func.count())
        .select_from(WrongQuestion)
        .where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.mastered_at.is_(None),
            WrongQuestion.next_review_at <= now,
        )
    ).scalar_one()


def _stats(db: Session, user_id: int) -> OverviewStats:
    """个人中心数据概览：投递总数 / 错题总数（不分到期、不分是否掌握）/ 面试会话数。"""

    def count(model: type) -> int:
        return db.execute(
            select(func.count()).select_from(model).where(model.user_id == user_id)
        ).scalar_one()

    return OverviewStats(
        application_count=count(Application),
        wrong_question_count=count(WrongQuestion),
        interview_count=count(InterviewSession),
    )
