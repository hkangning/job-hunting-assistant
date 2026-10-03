"""每日提醒引擎：纯规则判定 + 文案生成 + 幂等落库（FR-013，系统设计 5.5）。

判定全为纯 SQL（不调 LLM），**与 /overview 的区块口径保持同源**——阈值与状态集直接取自
`overview_service` 常量，两处不可各定一套；文案每账号调一次 LLM 批量改写，未配置 / 调用失败 /
解析异常一律回退模板文案。同一账号同日同对象不重复生成（先查后插 + 唯一约束兜底）；
任务互斥：定时与手动触发、并发手动触发都不重入（TC-22）。
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.llm_client import LLMClient, get_llm_client, resolve_config
from app.database import SessionLocal
from app.models import Application, Question, Reminder, User, WrongQuestion
from app.models.enums import ApplicationStatus, ReminderType
from app.prompts import build_reminder_messages
from app.services import campus_service
from app.services.overview_service import (
    FOLLOW_UP_MIN_DAYS,
    FOLLOW_UP_STATUSES,
    UPCOMING_WINDOW_DAYS,
)

logger = logging.getLogger(__name__)

_RUN_LOCK = threading.Lock()  # 任务互斥（TC-22）：拿不到锁直接返回，不排队不等待

# LLM 输入里给模型看的类型标签（INFO_MATCH 属步骤 22 的订阅提醒，暂不参与生成）
_TYPE_LABELS = {
    ReminderType.FOLLOW_UP: "投递跟进",
    ReminderType.WRONG_QUESTION: "错题复习",
    ReminderType.INTERVIEW: "面试提醒",
}

_MAX_CONTENT_LEN = 200  # LLM 文案长度兜底（超长截断，模板本身远短于此）
_QUESTION_EXCERPT_LEN = 30  # 错题题干在文案里的摘录长度


@dataclass(frozen=True)
class ReminderPlan:
    """一条待生成的提醒（判定产物）：text 既作 LLM 改写输入，也作失败回退的模板文案。"""

    reminder_type: ReminderType
    ref_id: int
    text: str


def run_daily(
    *,
    db_factory: Callable[[], Session] | None = None,
    client_getter: Callable[[], LLMClient] | None = None,
) -> int:
    """执行每日提醒任务：逐账号判定并生成，返回本次实际新增的提醒条数。

    - 互斥：任务执行中再次触发直接返回 0（定时与手动触发共用本入口）；
    - 容错：单账号失败回滚并跳过，不中断其余账号（系统设计 5.5）。
    """
    if not _RUN_LOCK.acquire(blocking=False):
        logger.info("每日提醒任务已在执行中，本次触发跳过")
        return 0
    try:
        factory = db_factory or SessionLocal
        getter = client_getter or get_llm_client
        total = 0
        with factory() as db:
            # 校招信息采集：公共任务全站执行一次（步骤 21，受 crawl_enabled 总开关控制）；
            # 先采集后判定，订阅命中的提醒（步骤 22）才能读到本次新入库的条目。
            # 内部已隔离异常与总开关，失败不阻塞提醒生成。
            campus_service.run_scheduled(db_factory=factory)
            for user_id in db.scalars(select(User.id)).all():
                try:
                    total += generate_for_user(db, user_id, client_getter=getter)
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception("账号 %s 的提醒生成失败，已跳过", user_id)
        return total
    finally:
        _RUN_LOCK.release()


def generate_for_user(
    db: Session,
    user_id: int,
    *,
    client_getter: Callable[[], LLMClient] | None = None,
    now: datetime | None = None,
) -> int:
    """单账号：判定 → 过滤当天已生成 → 生成文案 → 批量落库（不 commit，由调用方提交）。"""
    now = now or datetime.now()
    plans = collect_plans(db, user_id, now=now)
    if not plans:
        return 0
    today = now.date()
    # 同日同对象的提醒已存在即跳过（唯一约束 uq_reminder_user_type_ref_date 兜底并发场景）
    existing = {
        (row[0], row[1])
        for row in db.execute(
            select(Reminder.reminder_type, Reminder.ref_id).where(
                Reminder.user_id == user_id, Reminder.remind_date == today
            )
        ).all()
    }
    fresh = [plan for plan in plans if (plan.reminder_type.value, plan.ref_id) not in existing]
    if not fresh:
        return 0
    contents = _build_contents(db, user_id, fresh, client_getter or get_llm_client)
    db.add_all(
        [
            Reminder(
                user_id=user_id,
                reminder_type=plan.reminder_type.value,
                ref_id=plan.ref_id,
                ref_type=None,  # 仅 INFO_MATCH 有值，属步骤 22 的订阅命中提醒
                content=content,
                remind_date=today,
            )
            for plan, content in zip(fresh, contents)
        ]
    )
    return len(fresh)


def collect_plans(db: Session, user_id: int, now: datetime | None = None) -> list[ReminderPlan]:
    """纯规则判定当前账号今日应生成的提醒（TC-21 单测入口；条件与 /overview 区块一致）。"""
    now = now or datetime.now()
    plans = _follow_up_plans(db, user_id, now)
    plans += _wrong_question_plans(db, user_id, now)
    plans += _interview_plans(db, user_id, now)
    return plans


def _follow_up_plans(db: Session, user_id: int, now: datetime) -> list[ReminderPlan]:
    """满 3 天无进展：状态处早期且未安排未来的笔试/面试（同 /overview 的 follow_ups 条件）。"""
    rows = (
        db.execute(
            select(Application)
            .where(Application.user_id == user_id, Application.status.in_(FOLLOW_UP_STATUSES))
            .order_by(Application.applied_at.asc(), Application.id.asc())
        )
        .scalars()
        .all()
    )
    plans: list[ReminderPlan] = []
    for app in rows:
        days = (now.date() - app.applied_at.date()).days
        if days < FOLLOW_UP_MIN_DAYS:
            continue
        if app.next_event_at is not None and app.next_event_at >= now:
            continue
        plans.append(
            ReminderPlan(
                reminder_type=ReminderType.FOLLOW_UP,
                ref_id=app.id,
                text=f"{app.company} · {app.position} 已投递 {days} 天仍无进展，建议主动跟进",
            )
        )
    return plans


def _wrong_question_plans(db: Session, user_id: int, now: datetime) -> list[ReminderPlan]:
    """错题到期：next_review_at ≤ 当前时间且未掌握（同 /overview 计数条件），题干取前 30 字。"""
    rows = db.execute(
        select(WrongQuestion, Question)
        .join(Question, WrongQuestion.question_id == Question.id)
        .where(
            WrongQuestion.user_id == user_id,
            WrongQuestion.mastered_at.is_(None),
            WrongQuestion.next_review_at <= now,
        )
        .order_by(WrongQuestion.next_review_at.asc(), WrongQuestion.id.asc())
    ).all()
    plans: list[ReminderPlan] = []
    for wrong, question in rows:
        excerpt = question.content.strip().replace("\n", " ")[:_QUESTION_EXCERPT_LEN]
        plans.append(
            ReminderPlan(
                reminder_type=ReminderType.WRONG_QUESTION,
                ref_id=wrong.id,
                text=f"错题「{excerpt}」已到复习时间，去复习一下加深记忆",
            )
        )
    return plans


def _interview_plans(db: Session, user_id: int, now: datetime) -> list[ReminderPlan]:
    """7 日内待笔试/面试：状态未结束、时间点在 [now, now+7d]（同 /overview 的 upcoming_events 条件）。"""
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
        ReminderPlan(
            reminder_type=ReminderType.INTERVIEW,
            ref_id=app.id,
            text=(
                f"{app.company} · {app.position} 将于 "
                f"{app.next_event_at.strftime('%m-%d %H:%M')} 进行笔试/面试，注意提前准备"
            ),
        )
        for app in rows
    ]


def _build_contents(
    db: Session, user_id: int, plans: list[ReminderPlan], client_getter: Callable[[], LLMClient]
) -> list[str]:
    """生成本批提醒的文案：LLM 一次批量改写，整调用失败全部回退模板，单条缺失只回退该条。"""
    templates = [plan.text for plan in plans]
    try:
        config = resolve_config(db, user_id)  # 未配 Key 抛 10012，直接走模板
        fact_lines = [
            f"{i}. [{_TYPE_LABELS.get(plan.reminder_type, '提醒')}] {plan.text}"
            for i, plan in enumerate(plans, start=1)
        ]
        data = client_getter().chat_json(config, build_reminder_messages(fact_lines))
    except Exception:
        logger.info("账号 %s 的提醒文案生成失败，回退模板文案", user_id)
        return templates

    items = data.get("items")
    if not isinstance(items, list):
        logger.info("账号 %s 的提醒文案输出缺少 items，回退模板文案", user_id)
        return templates

    contents = list(templates)
    for item in items:
        if not isinstance(item, dict):
            continue
        index = _as_index(item.get("index"), len(plans))
        content = item.get("content")
        if index is None or not isinstance(content, str) or not content.strip():
            continue  # index 非法 / 文案为空的单条保留模板
        contents[index - 1] = content.strip()[:_MAX_CONTENT_LEN]
    return contents


def _as_index(value: object, total: int) -> int | None:
    """LLM 输出的 index 归一化为 1 起有效序号（容忍数字字符串）；非法返回 None。"""
    try:
        index = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return index if 1 <= index <= total else None
