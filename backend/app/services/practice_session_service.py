"""训练会话生命周期：开一场 / 结算 / 历史 / 回看（接口文档 3.8；链路设计见系统设计 §5.10）。

每轮的内容生成在 `practice_turn_service`（走 SSE），本模块只做落库与结算计算——结算**纯计算、不调 LLM**。
"""

import re
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clients.llm_client import parse_json_block
from app.exceptions import BizException, ErrorCode
from app.models import PracticeRecord, PracticeSession, Question, WrongQuestion
from app.models.enums import (
    AttackFace,
    PracticeMode,
    PracticeSessionStatus,
    RoundKind,
    WrongSourceType,
)
from app.prompts import PRACTICE_TURN_SECTION_RULES
from app.schemas.common import PageData
from app.schemas.practice import (
    MasteryDelta,
    QuestionBrief,
    RoundBrief,
    SessionCreateData,
    SessionDetailData,
    SessionFinishData,
    SessionListItem,
    SessionRoundItem,
)
from app.services import practice_service
from app.utils.practice_flow import (
    ATTACK_FACE_ORDER,
    MAX_LAYERS,
    is_stuck,
    judge_passed,
)
from app.utils.section_splitter import internal_text, public_text

REVIEW_STAGE_DAYS = (1, 3, 7, 15)  # 复习档位 1~4 对应的间隔天数（数据库设计 §3.9）
QUESTION_PREVIEW_LIMIT = 60  # 历史列表的题干预览截断长度
GAP_ITEM_LIMIT = 50  # 单条缺口的字数上限
GAPS_LIMIT = 5  # 缺口清单条数上限
MODE_VALUES = {m.value for m in PracticeMode}

# 有用户作答的轮次类型（提示轮与材料轮是 AI 单方产出，既不算断点也不参与综合分）
ANSWER_KINDS = (RoundKind.OPENING, RoundKind.FOLLOW_UP, RoundKind.REBUTTAL, RoundKind.RETELL)
# 点评里像「缺口条目」的行：`- 未提及 X` / `1. 没给量级`
_BULLET_RE = re.compile(r"^(?:[-*•·]|\d+[.、)）])\s*")
_LEAK_RE = re.compile(r"\d+")


def open_session(
    db: Session, *, user_id: int, question_id: int, mode: str, time_limit: int | None
) -> SessionCreateData:
    """开一场训练。**纯落库、零 LLM 调用**；同一道题可开多场，会话之间互不影响。"""
    if db.get(Question, question_id) is None:
        raise BizException(ErrorCode.NOT_FOUND, "题目不存在")
    if mode not in MODE_VALUES:
        raise BizException(ErrorCode.PARAM_INVALID, "训练模式非法")
    if time_limit is not None and time_limit not in practice_service.TIME_LIMITS:
        raise BizException(
            ErrorCode.PARAM_INVALID,
            f"限时档位须为 {'/'.join(str(t) for t in practice_service.TIME_LIMITS)} 之一",
        )

    session = PracticeSession(
        user_id=user_id,
        question_id=question_id,
        mode=mode,
        status=PracticeSessionStatus.RUNNING,
        time_limit=time_limit,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return SessionCreateData(
        session_id=session.id,
        question_id=question_id,
        mode=session.mode,
        status=session.status,
        time_limit=session.time_limit,
        round_index=1,
        started_at=session.started_at,
    )


def get_session(db: Session, *, user_id: int, session_id: int) -> PracticeSession:
    """取会话；不存在或不属于当前账号 → 404 + 10002（二者不可区分）。"""
    session = db.get(PracticeSession, session_id)
    if session is None or session.user_id != user_id:
        raise BizException(ErrorCode.NOT_FOUND, "训练会话不存在")
    return session


def assert_running(session: PracticeSession) -> None:
    """终态会话不可再提交轮次（接口文档 §3.8 实现口径 4）。"""
    if session.status != PracticeSessionStatus.RUNNING:
        raise BizException(ErrorCode.PARAM_INVALID, "该场训练已结束，无法继续作答")


def finish_session(db: Session, *, user_id: int, session_id: int) -> SessionFinishData:
    """结算：聚合各轮评分算综合分 → 判通过 → 未通过则入错题本 → 重算掌握度 → 会话置 FINISHED。

    已结算的会话重复调用**幂等**——返回既有结果，不重复入本、不重复重算掌握度。
    """
    session = get_session(db, user_id=user_id, session_id=session_id)
    if session.status == PracticeSessionStatus.ABORTED:
        raise BizException(ErrorCode.PARAM_INVALID, "该场训练已作废，无法结算")
    question = db.get(Question, session.question_id)
    records = load_rounds(db, session_id=session.id)

    if session.status == PracticeSessionStatus.FINISHED:
        current = practice_service.mastery_of(db, user_id=user_id, direction=question.direction)
        return _build_finish_data(session, question, records, before=current, after=current)

    mode = PracticeMode(session.mode)
    scores = [r.score for r in records if r.score is not None]
    overall_score = round(sum(scores) / len(scores)) if scores else None
    break_face = _first_break_face(records)
    passed = judge_passed(
        mode=mode,
        overall_score=overall_score,
        break_count=sum(1 for r in records if _record_is_break(r)),
        hit_rate=_debug_hit_rate(records) if mode is PracticeMode.DEBUG else None,
        leak_count=_feynman_leak_count(records) if mode is PracticeMode.FEYNMAN else None,
    )

    session.overall_score = overall_score
    session.break_face = break_face.value if break_face else None
    session.passed = 1 if passed else 0
    session.status = PracticeSessionStatus.FINISHED
    session.finished_at = datetime.now()
    answered = any(r.round_kind in ANSWER_KINDS and (r.user_answer or "").strip() for r in records)
    if not passed and answered:  # 一场都没答就结算的，不判「未通过」、也不入本
        session.wrong_question_id = _upsert_wrong_question(
            db, user_id=user_id, question_id=session.question_id, now=session.finished_at
        ).id
    db.commit()

    before, after = practice_service.recompute_mastery(
        db, user_id=user_id, direction=question.direction
    )
    db.commit()
    return _build_finish_data(session, question, records, before=before, after=after)


def list_sessions(
    db: Session, *, user_id: int, mode: str | None = None, page: int = 1, page_size: int = 10
) -> PageData[SessionListItem]:
    """训练历史：按开始时间倒序（同秒按 id 倒序），题干预览截断展示。"""
    if mode is not None and mode not in MODE_VALUES:
        raise BizException(ErrorCode.PARAM_INVALID, "训练模式非法")

    conditions = [PracticeSession.user_id == user_id]
    if mode:
        conditions.append(PracticeSession.mode == mode)
    total = (
        db.execute(select(func.count()).select_from(PracticeSession).where(*conditions)).scalar() or 0
    )
    sessions = list(
        db.execute(
            select(PracticeSession)
            .where(*conditions)
            .order_by(PracticeSession.started_at.desc(), PracticeSession.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        ).scalars()
    )
    if not sessions:
        return PageData(total=total, items=[])

    contents = dict(
        db.execute(
            select(Question.id, Question.content).where(
                Question.id.in_({s.question_id for s in sessions})
            )
        ).all()
    )
    counts = dict(
        db.execute(
            select(PracticeRecord.session_id, func.count())
            .where(PracticeRecord.session_id.in_([s.id for s in sessions]))
            .group_by(PracticeRecord.session_id)
        ).all()
    )
    return PageData(
        total=total,
        items=[
            SessionListItem(
                id=s.id,
                question_id=s.question_id,
                question_content=_preview(contents.get(s.question_id, "")),
                mode=s.mode,
                status=s.status,
                time_limit=s.time_limit,
                overall_score=s.overall_score,
                passed=bool(s.passed) if s.passed is not None else None,
                break_face=s.break_face,
                round_count=counts.get(s.id, 0),
                started_at=s.started_at,
                finished_at=s.finished_at,
            )
            for s in sessions
        ],
    )


def get_session_detail(db: Session, *, user_id: int, session_id: int) -> SessionDetailData:
    """单场回看：会话信息 + 逐轮记录（升序）；**参考答案仅结算后返回**（追问中给等于泄题）。"""
    session = get_session(db, user_id=user_id, session_id=session_id)
    question = db.get(Question, session.question_id)
    records = load_rounds(db, session_id=session.id)
    return SessionDetailData(
        id=session.id,
        mode=session.mode,
        status=session.status,
        time_limit=session.time_limit,
        question=QuestionBrief(
            id=question.id,
            content=question.content,
            qtype=question.qtype,
            stack=question.stack,
            direction=question.direction,
        ),
        overall_score=session.overall_score,
        passed=bool(session.passed) if session.passed is not None else None,
        break_face=session.break_face,
        hint_count=session.hint_count,
        rounds=[_round_item(r, time_limit=session.time_limit) for r in records],
        reference_answer=question.answer
        if session.status == PracticeSessionStatus.FINISHED
        else None,
    )


def load_rounds(db: Session, *, session_id: int) -> list[PracticeRecord]:
    """本场逐轮记录，按轮次升序（每轮驱动也读它，故为公开接口）。"""
    return list(
        db.execute(
            select(PracticeRecord)
            .where(PracticeRecord.session_id == session_id)
            .order_by(PracticeRecord.round_index, PracticeRecord.id)
        ).scalars()
    )


def _build_finish_data(
    session: PracticeSession,
    question: Question,
    records: list[PracticeRecord],
    *,
    before: int,
    after: int,
) -> SessionFinishData:
    return SessionFinishData(
        session_id=session.id,
        mode=session.mode,
        question_id=session.question_id,
        overall_score=session.overall_score,
        passed=bool(session.passed),
        rounds=_round_briefs(records),
        break_face=session.break_face,
        hint_count=session.hint_count,
        reference_answer=question.answer,
        gaps=_collect_gaps(records),
        mastery_delta=MasteryDelta(direction=question.direction, before=before, after=after),
        wrong_question_id=session.wrong_question_id,
    )


def _round_briefs(records: list[PracticeRecord]) -> list[RoundBrief]:
    return [
        RoundBrief(
            index=r.round_index,
            kind=r.round_kind,
            score=r.score,
            is_break=_record_is_break(r),
        )
        for r in records
    ]


def _round_item(record: PracticeRecord, *, time_limit: int | None) -> SessionRoundItem:
    return SessionRoundItem(
        index=record.round_index,
        kind=record.round_kind,
        user_answer=record.user_answer,
        score=record.score,
        review=public_text(record.review or "", PRACTICE_TURN_SECTION_RULES) or None,
        elapsed_ms=record.elapsed_ms,
        timed_out=bool(time_limit and (record.elapsed_ms or 0) >= time_limit * 1000),
        created_at=record.created_at,
    )


def _record_is_break(record: PracticeRecord) -> bool:
    """该轮是否记为断点：有作答的轮次里答不上（限时内一字未写亦计，接口文档 §3.8 实现口径 6）。

    提示轮与材料轮（`HINT`）是 AI 单方产出、用户没作答，不算断点——作答轮一律落空串而非
    null，`user_answer` 为空值只可能出现在这类轮次或历史数据上。
    """
    if record.round_kind not in ANSWER_KINDS or record.user_answer is None:
        return False
    return is_stuck(record.user_answer)


def _first_break_face(records: list[PracticeRecord]) -> AttackFace | None:
    """首个断点所在攻击面——层号 = 该轮之前已发生的追问轮数 + 1，与 `next_turn` 的分层同源。"""
    follow_ups = 0
    for record in records:
        if _record_is_break(record):
            layer = min(follow_ups + 1, MAX_LAYERS)
            return ATTACK_FACE_ORDER[layer - 1]
        if record.round_kind == RoundKind.FOLLOW_UP:
            follow_ups += 1
    return None


def _debug_hit_rate(records: list[PracticeRecord]) -> float | None:
    """挑错模式命中率：从找错轮点评的「判定」内部段抠 JSON（命中数 / 埋雷数）。

    抠不出来按不通过处理（fail-closed）——宁可判他没过，也不白送一次通过。
    """
    for record in reversed(records):
        if record.round_kind != RoundKind.REBUTTAL:
            continue
        raw = internal_text(record.review or "", PRACTICE_TURN_SECTION_RULES, "_verdict")
        if not raw:
            return None
        try:
            data = parse_json_block(raw)
            total = int(data.get("total") or 0)
            hit = int(data.get("hit") or 0)
        except (ValueError, TypeError):
            return None
        return hit / total if total > 0 else None
    return None


def _feynman_leak_count(records: list[PracticeRecord]) -> int | None:
    """费曼模式漏洞条数：从复述轮点评的「漏洞计数」内部段抠数字；抠不出来按不通过处理。"""
    for record in reversed(records):
        if record.round_kind != RoundKind.RETELL:
            continue
        raw = internal_text(record.review or "", PRACTICE_TURN_SECTION_RULES, "_leak")
        match = _LEAK_RE.search(raw)
        return int(match.group()) if match else None
    return None


def _collect_gaps(records: list[PracticeRecord]) -> list[str]:
    """缺口清单：从**有作答的轮次**点评里汇总（越新的越贴近当前水平），去重、上限 5 条。

    服务端汇总，**不额外调 LLM**；内部段（判定 / 漏洞计数）不下发，材料轮的正文也不进缺口
    ——那是 AI 给的错误答案，不是用户的缺口。
    """
    gaps: list[str] = []
    for record in reversed(records):
        if record.round_kind not in ANSWER_KINDS:
            continue
        text = public_text(record.review or "", PRACTICE_TURN_SECTION_RULES)
        for line in _gap_lines(text):
            item = line[:GAP_ITEM_LIMIT]
            if item and item not in gaps:
                gaps.append(item)
            if len(gaps) >= GAPS_LIMIT:
                return gaps
    return gaps


def _gap_lines(text: str) -> list[str]:
    """点评里像「缺口」的行：列表项优先，没有列表就退化为首句（标题行不算缺口）。"""
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    bullets = [_BULLET_RE.sub("", line).strip() for line in lines if _BULLET_RE.match(line)]
    bullets = [b for b in bullets if b]
    if bullets:
        return bullets
    if lines:
        return [re.split(r"[。！？]", lines[0])[0].strip() + "。"]
    return []


def _upsert_wrong_question(
    db: Session, *, user_id: int, question_id: int, now: datetime
) -> WrongQuestion:
    """未通过则入错题本：已在本则档位重置回第 1 档、答错次数累加、退出「已掌握」。"""
    row = db.execute(
        select(WrongQuestion).where(
            WrongQuestion.user_id == user_id, WrongQuestion.question_id == question_id
        )
    ).scalar_one_or_none()
    if row is None:
        row = WrongQuestion(
            user_id=user_id,
            question_id=question_id,
            source_type=WrongSourceType.PRACTICE,
            review_stage=1,
            next_review_at=now + timedelta(days=REVIEW_STAGE_DAYS[0]),
            wrong_count=1,
        )
        db.add(row)
    else:
        row.review_stage = 1
        row.wrong_count += 1
        row.next_review_at = now + timedelta(days=REVIEW_STAGE_DAYS[0])
        # 又错了就退出「已掌握」，否则该题此后再不复现（数据库设计 §3.9）
        row.mastered_at = None
    db.flush()
    return row


def _preview(text: str) -> str:
    """题干预览：折成一行的同时截断，避免列表被长题干撑破。"""
    flat = " ".join(text.split())
    return flat if len(flat) <= QUESTION_PREVIEW_LIMIT else flat[:QUESTION_PREVIEW_LIMIT] + "…"
