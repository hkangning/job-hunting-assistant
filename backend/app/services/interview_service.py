"""AI 模拟面试：会话管理 + 一问一答流式链路（接口文档 3.7；prompt 见系统设计 5.3）。

一轮请求 = 一次 SSE：作答轮产出「点评 + 下一题」、跳过轮只出下一题、开场 / 续题轮只出题。
**整轮内容生成完、流正常结束才一次性落库**（本轮作答补全 + 点评 + 新题同一事务）；
断连或中途失败不落任何记录，前端重试即整轮重发（`GeneratorExit` 沿 `yield from` 传播，
落库语句不会执行——与 JD 分析「断连落半成品」的口径相反，见接口文档 3.7 实现口径 1）。
"""

import re
from collections.abc import Iterator
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clients.llm_client import LLMClient, LLMConfig, resolve_config
from app.exceptions import BizException, ErrorCode
from app.models import Application, InterviewQa, InterviewSession, JdAnalysisReport
from app.models.enums import Direction, SessionStatus
from app.prompts import (
    INTERVIEW_JD_LIMIT,
    INTERVIEW_SECTION_RULES,
    build_interview_question_messages,
    build_interview_turn_messages,
)
from app.schemas.common import PageData
from app.schemas.interview import (
    InterviewSessionDTO,
    QaItem,
    SessionCreateRequest,
    SessionDetailData,
    SessionListItem,
)
from app.services.practice_service import STACKS
from app.utils.section_splitter import SectionSplitter
from app.utils.sse import SSE

# 领域枚举值 → 中文名（与陪练筛选面板同源）
_DIRECTION_LABELS: dict[str, str] = {d: label for _, _, domains in STACKS for d, label in domains}

# 点评首行的评分口径（与陪练同正则）：容忍冒号、空格等间隔符
_SCORE_RE = re.compile(r"评分[^\d]{0,6}(\d{1,2})")


def create_session(db: Session, *, user_id: int, payload: SessionCreateRequest) -> InterviewSessionDTO:
    """建会话：传投递则公司 / 岗位从中带入（越权 / 不存在 404 + 10002），否则手填两者必填。"""
    if payload.application_id is not None:
        application = db.get(Application, payload.application_id)
        if application is None or application.user_id != user_id:
            raise BizException(ErrorCode.NOT_FOUND, "投递记录不存在")
        company, position = application.company, application.position
    else:
        company = (payload.company or "").strip()
        position = (payload.position or "").strip()
        if not company or not position:
            raise BizException(ErrorCode.PARAM_INVALID, "公司名与岗位名必填")
    session = InterviewSession(
        user_id=user_id,
        application_id=payload.application_id,
        company=company,
        position=position,
        direction=payload.direction.value,
        question_count=payload.question_count,
        status=SessionStatus.ACTIVE.value,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _to_dto(session)


def list_sessions(
    db: Session, *, user_id: int, status: SessionStatus | None, page: int, page_size: int
) -> PageData[SessionListItem]:
    """会话列表：按创建时间倒序（同秒按 id 倒序），`qa_count` 供显示进度。"""
    conditions = [InterviewSession.user_id == user_id]
    if status is not None:
        conditions.append(InterviewSession.status == status.value)

    total = db.execute(
        select(func.count()).select_from(InterviewSession).where(*conditions)
    ).scalar_one()
    rows = db.execute(
        select(InterviewSession, func.count(InterviewQa.id))
        .outerjoin(InterviewQa, InterviewQa.session_id == InterviewSession.id)
        .where(*conditions)
        .group_by(InterviewSession.id)
        .order_by(InterviewSession.created_at.desc(), InterviewSession.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PageData(
        total=total,
        items=[_to_item(session, qa_count) for session, qa_count in rows],
    )


def get_session_detail(db: Session, *, user_id: int, session_id: int) -> SessionDetailData:
    """会话详情：会话字段 + 全部问答（按 seq 升序，含尚未作答的当前题）。"""
    session = db.get(InterviewSession, session_id)
    if session is None or session.user_id != user_id:
        raise BizException(ErrorCode.NOT_FOUND, "面试会话不存在")
    qas = _load_qas(db, session.id)
    return SessionDetailData(
        **_session_fields(session), qa_list=[_to_qa_item(qa) for qa in qas]
    )


def ensure_chattable(
    db: Session, *, user_id: int, session_id: int, answer: str | None, skip: bool
) -> InterviewSession:
    """作答前校验（在 SSE 建立之前执行，接口文档 3.7 实现口径 2）：

    会话不存在 / 不属于当前账号 → 404 + 10002；会话已结束 → 40001；`skip` 但无待答题 →
    10001；`answer` 非空但无待答题 → 40001；`skip` 与 `answer` 同传 → 10001。
    """
    session = db.get(InterviewSession, session_id)
    if session is None or session.user_id != user_id:
        raise BizException(ErrorCode.NOT_FOUND, "面试会话不存在")
    if session.status != SessionStatus.ACTIVE.value:
        raise BizException(ErrorCode.INTERVIEW_STATE_INVALID, "面试会话已结束")

    pending = _pending_qa(_load_qas(db, session.id))
    has_answer = bool((answer or "").strip())
    if skip and has_answer:
        raise BizException(ErrorCode.PARAM_INVALID, "作答与跳过不能同时提交")
    if skip:
        if pending is None:
            raise BizException(ErrorCode.PARAM_INVALID, "当前没有可跳过的题目")
    elif has_answer:
        if pending is None:
            raise BizException(ErrorCode.INTERVIEW_STATE_INVALID, "当前没有待作答的题目")
    elif pending is None and _answered_count(db, session.id) >= session.question_count:
        # 题量已答满但会话仍是 ACTIVE 的异常态（正常应已被置 FINISHED）
        raise BizException(ErrorCode.INTERVIEW_STATE_INVALID, "本场题量已答满")
    return session


def run_chat(
    db: Session,
    *,
    user_id: int,
    session_id: int,
    answer: str | None,
    skip: bool,
    client: LLMClient,
) -> Iterator[str]:
    """作答入口（业务生成器）：按当前进度分派四类轮次，`yield` SSE 事件、`return` done 载荷。"""
    session = ensure_chattable(
        db, user_id=user_id, session_id=session_id, answer=answer, skip=skip
    )
    qas = _load_qas(db, session.id)
    pending = _pending_qa(qas)
    text = (answer or "").strip()
    context = _build_context(db, session)
    asked = [qa.question for qa in qas]

    if skip:
        # 跳过轮：被跳题不计分、不出点评，直接进下一题（跳过最后一题则结束）
        return (
            yield from _skip_round(
                db, session, qas, pending, context=context, asked=asked, client=client
            )
        )
    if not text:
        if pending is not None:
            # 幂等重发：不调 LLM、不落库，断线重试安全（接口文档 3.7 实现口径 3）
            yield SSE.delta(pending.question, "next_question")
            return _done(pending.id, seq=pending.seq)
        # 新会话出首题 / 全部已答未满续出下一题
        return (
            yield from _question_round(
                db, session, qas, context=context, asked=asked, client=client
            )
        )
    return (
        yield from _answer_round(
            db, session, qas, pending, text, context=context, asked=asked, client=client
        )
    )


def _skip_round(
    db: Session,
    session: InterviewSession,
    qas: list[InterviewQa],
    pending: InterviewQa,
    *,
    context: str,
    asked: list[str],
    client: LLMClient,
) -> Iterator[str]:
    """跳过轮：跳过最后一题时无下一题、直接结束；否则把被跳题置 skipped 并出下一题。"""
    if pending.seq >= session.question_count:
        pending.skipped = 1
        _finish(session, now=datetime.now())
        db.commit()
        return _done(pending.id, seq=pending.seq, finished=True)
    return (
        yield from _question_round(
            db, session, qas, context=context, asked=asked, client=client, skipped=pending
        )
    )


def _question_round(
    db: Session,
    session: InterviewSession,
    qas: list[InterviewQa],
    *,
    context: str,
    asked: list[str],
    client: LLMClient,
    skipped: InterviewQa | None = None,
) -> Iterator[str]:
    """出题轮（开场 / 跳过 / 续出下一题）：流正常结束后落新题（跳过轮同时把被跳题置 skipped）。"""
    config = resolve_config(db, session.user_id)
    messages = build_interview_question_messages(context=context, asked=asked)
    sections = yield from _stream(client, config, messages, drop_next=False)
    question_text = sections["next_question"]
    if not question_text:
        raise BizException(ErrorCode.LLM_OUTPUT_INVALID, "模型未产出题目，请重试")

    now = datetime.now()
    if skipped is not None:
        skipped.skipped = 1
    record = InterviewQa(
        session_id=session.id, seq=len(qas) + 1, question=question_text, created_at=now
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _done(record.id, seq=record.seq)


def _answer_round(
    db: Session,
    session: InterviewSession,
    qas: list[InterviewQa],
    pending: InterviewQa,
    answer: str,
    *,
    context: str,
    asked: list[str],
    client: LLMClient,
) -> Iterator[str]:
    """作答轮：点评 + 下一题；答满题量轮只点评并同事务置会话 FINISHED。"""
    last = pending.seq >= session.question_count
    config = resolve_config(db, session.user_id)
    messages = build_interview_turn_messages(
        context=context, asked=asked, question=pending.question, answer=answer, last=last
    )
    sections = yield from _stream(client, config, messages, drop_next=last)
    review = sections["review"]
    if not review or (not last and not sections["next_question"]):
        raise BizException(ErrorCode.LLM_OUTPUT_INVALID, "模型点评内容不完整，请重试")

    now = datetime.now()
    pending.answer = answer
    pending.review = review
    pending.score = _extract_score(review)
    if last:
        _finish(session, now=now)
        record = pending
    else:
        record = InterviewQa(
            session_id=session.id,
            seq=pending.seq + 1,
            question=sections["next_question"],
            created_at=now,
        )
        db.add(record)
    db.commit()
    db.refresh(record)
    return _done(record.id, seq=record.seq, finished=last)


def _stream(
    client: LLMClient,
    config: LLMConfig,
    messages: list[dict],
    *,
    drop_next: bool,
) -> Iterator[str]:
    """流式下发 delta，返回 `{"review": ..., "next_question": ...}`（段内文本恒等于 delta 拼接）。

    段落归属只看标题行：**首个标题出现前的内容（模型的寒暄或没按格式输出）整段丢弃**，
    既不下发也不落库——落库文本恒等于 delta 拼接，且没按格式输出时对应段为空、由调用方报 10011。
    `drop_next=True`（答满题量轮）时模型多输出的下一题段同样整段丢弃。
    """
    buckets: dict[str, list[str]] = {"review": [], "next_question": []}
    for text, section in _iter_pieces(client, config, messages):
        if section is None:
            continue
        if section == "next_question" and drop_next:
            continue
        buckets[section].append(text)
        yield SSE.delta(text, section)
    return {name: "".join(parts).strip() for name, parts in buckets.items()}


def _iter_pieces(
    client: LLMClient, config: LLMConfig, messages: list[dict]
) -> Iterator[tuple[str, str | None]]:
    """逐块喂切分器产出 `(文本, 段名)`，收尾冲刷残留（段名 None = 尚未出现标题的前导文本）。"""
    splitter = SectionSplitter(INTERVIEW_SECTION_RULES)
    for chunk in client.stream_chat(config, messages):
        yield from splitter.feed(chunk)
    yield from splitter.flush()


def _build_context(db: Session, session: InterviewSession) -> str:
    """出题 / 点评共用的背景：公司、岗位、方向（领域中文名），关联投递时附 JD 原文节选。"""
    lines = [f"公司：{session.company}", f"岗位：{session.position}"]
    if session.direction == Direction.GENERAL.value:
        lines.append("方向：不限（综合考察基础知识与项目经历）")
    else:
        label = _DIRECTION_LABELS.get(session.direction, session.direction)
        lines.append(f"方向：{label}（题目须落在该方向内）")
    if session.application_id is not None:
        jd = _latest_jd_text(db, session.application_id)
        if jd:
            lines.append(f"岗位 JD（节选，供出题贴合岗位要求）：\n{jd[:INTERVIEW_JD_LIMIT]}")
    return "\n".join(lines)


def _latest_jd_text(db: Session, application_id: int) -> str:
    """该投递最近一次 JD 分析的原文快照（投递表不存 JD，原文随分析报告落库）。"""
    return (
        db.execute(
            select(JdAnalysisReport.jd_text)
            .where(JdAnalysisReport.application_id == application_id)
            .order_by(JdAnalysisReport.created_at.desc(), JdAnalysisReport.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        or ""
    )


def _load_qas(db: Session, session_id: int) -> list[InterviewQa]:
    return list(
        db.execute(
            select(InterviewQa)
            .where(InterviewQa.session_id == session_id)
            .order_by(InterviewQa.seq)
        ).scalars()
    )


def _answered_count(db: Session, session_id: int) -> int:
    """已作答 / 已跳过的条数（不含尚未作答的当前题）。"""
    return db.execute(
        select(func.count())
        .select_from(InterviewQa)
        .where(
            InterviewQa.session_id == session_id,
            (InterviewQa.skipped == 1) | (InterviewQa.answer.is_not(None)),
        )
    ).scalar_one()


def _pending_qa(qas: list[InterviewQa]) -> InterviewQa | None:
    """当前待答题 = 最后一条既未作答也未跳过的问答；其余情况返回 None。"""
    if not qas:
        return None
    last = qas[-1]
    if not (last.answer or "").strip() and not last.skipped:
        return last
    return None


def _finish(session: InterviewSession, *, now: datetime) -> None:
    """置会话已结束（答满题量 / 跳过最后一题），此后作答与跳过一律 40001。"""
    session.status = SessionStatus.FINISHED.value
    session.finished_at = now


def _extract_score(review: str) -> int | None:
    """从点评首行抠评分（0~10），取不到或越界记 null（与陪练同口径）。"""
    matched = _SCORE_RE.search(review)
    if matched is None:
        return None
    score = int(matched.group(1))
    return score if 0 <= score <= 10 else None


def _done(record_id: int, *, seq: int, finished: bool = False) -> dict:
    """done 载荷（协议层组装事件）：`seq` = 本轮内容对应的题序，答满题量附 `session_finished`。"""
    return {
        "record_id": record_id,
        "seq": seq,
        "extra": {"session_finished": True} if finished else None,
    }


def _session_fields(session: InterviewSession) -> dict:
    """会话 ORM 对象 → DTO 公共字段（三种 DTO 复用）。"""
    return {
        "id": session.id,
        "application_id": session.application_id,
        "company": session.company,
        "position": session.position,
        "direction": session.direction,
        "question_count": session.question_count,
        "status": session.status,
        "summary": session.summary,
        "created_at": session.created_at,
        "finished_at": session.finished_at,
    }


def _to_dto(session: InterviewSession) -> InterviewSessionDTO:
    return InterviewSessionDTO(**_session_fields(session))


def _to_item(session: InterviewSession, qa_count: int) -> SessionListItem:
    return SessionListItem(**_session_fields(session), qa_count=qa_count)


def _to_qa_item(qa: InterviewQa) -> QaItem:
    return QaItem(
        id=qa.id,
        seq=qa.seq,
        question=qa.question,
        answer=qa.answer,
        is_voice=qa.is_voice,
        score=qa.score,
        review=qa.review,
        skipped=qa.skipped,
        created_at=qa.created_at,
    )
