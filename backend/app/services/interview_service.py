"""AI 模拟面试：会话管理 + 一问一答流式链路 + 整场总结（接口文档 3.7；prompt 见系统设计 5.3）。

一轮请求 = 一次 SSE：作答轮产出「点评 + 下一题」、跳过轮只出下一题、开场 / 续题轮只出题。
**整轮内容生成完、流正常结束才一次性落库**（本轮作答补全 + 点评 + 新题同一事务）；
断连或中途失败不落任何记录，前端重试即整轮重发（`GeneratorExit` 沿 `yield from` 传播，
落库语句不会执行——与 JD 分析「断连落半成品」的口径相反，见接口文档 3.7 实现口径 1）。

面试按**阶段化流程**推进（FR-007）：自我介绍 1 题 → 技术问答余量 →（画像有经历条目时）项目深挖——
计划在建会话时算好存 `interview_session.stage_plan`，每题的阶段由计划推出、落在 `interview_qa.stage`，
prompt 按阶段分派。总结报告见 `run_summary`（全文随流落库、会话置 FINISHED）。
"""

import json
import re
from collections.abc import Iterator
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clients.llm_client import LLMClient, LLMConfig, resolve_config
from app.exceptions import BizException, ErrorCode
from app.models import Application, InterviewQa, InterviewSession, JdAnalysisReport, UserProfile
from app.models.enums import Direction, InterviewIntensity, InterviewStage, SessionStatus
from app.prompts import (
    INTERVIEW_EXPERIENCE_LIMIT,
    INTERVIEW_JD_LIMIT,
    INTERVIEW_SECTION_RULES,
    build_experience_digest,
    build_interview_question_messages,
    build_interview_summary_messages,
    build_interview_turn_messages,
    interview_intensity_note,
    interview_review_stage_note,
    interview_stage_note,
)
from app.schemas.common import PageData
from app.schemas.interview import (
    InterviewSessionDTO,
    QaItem,
    SessionCreateRequest,
    SessionDetailData,
    SessionListItem,
    StagePlanItem,
)
from app.services.practice_service import STACKS
from app.utils.section_splitter import SectionSplitter
from app.utils.sse import SSE

# 领域枚举值 → 中文名（与陪练筛选面板同源）
_DIRECTION_LABELS: dict[str, str] = {d: label for _, _, domains in STACKS for d, label in domains}

# 点评首行的评分口径（与陪练同正则）：容忍冒号、空格等间隔符
_SCORE_RE = re.compile(r"评分[^\d]{0,6}(\d{1,2})")


def create_session(db: Session, *, user_id: int, payload: SessionCreateRequest) -> InterviewSessionDTO:
    """建会话：传投递则公司 / 岗位从中带入（越权 / 不存在 404 + 10002），否则手填两者必填。

    同时按「画像是否已填经历条目」定阶段计划（FR-007）：自我介绍 1 题 + 技术问答余量，有经历
    再加项目深挖段。计划在创建时算好落库，后续每题的阶段由它推出（模型只管出题内容）。
    """
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
    plan = _build_stage_plan(payload.question_count, has_experience=bool(_experience_text(db, user_id)))
    session = InterviewSession(
        user_id=user_id,
        application_id=payload.application_id,
        company=company,
        position=position,
        direction=payload.direction.value,
        question_count=payload.question_count,
        intensity=payload.intensity.value,
        stage_plan=json.dumps(plan, ensure_ascii=False),
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


def ensure_summarizable(db: Session, *, user_id: int, session_id: int) -> InterviewSession:
    """生成总结前校验（在 SSE 建立之前执行，接口文档 3.7）：

    会话不存在 / 不属于当前账号 → 404 + 10002；无任何已完成问答（作答或跳过）→ 400 + 10001。
    进行中（ACTIVE）的会话同样允许——「提前结束」即从此端点生成总结并置 FINISHED。
    """
    session = db.get(InterviewSession, session_id)
    if session is None or session.user_id != user_id:
        raise BizException(ErrorCode.NOT_FOUND, "面试会话不存在")
    if _answered_count(db, session.id) < 1:
        raise BizException(ErrorCode.PARAM_INVALID, "本场还没有已作答的题目，无法生成总结")
    return session


def run_summary(
    db: Session, *, user_id: int, session_id: int, client: LLMClient
) -> Iterator[str]:
    """总结生成（业务生成器）：`yield` SSE 事件（delta section 恒为 `summary`）、`return` done 载荷。

    已有总结时直接回放、不调 LLM（重复调用不重复计费）；否则流式生成，**全文随流落库**
    （`summary` 列即 delta 拼接，不做分节——模型没按格式输出也不会丢内容），
    同事务将会话置 FINISHED。断连不落库（与 `interview-chat` 同口径）：
    `GeneratorExit` 沿链上抛，commit 不执行。
    """
    session = ensure_summarizable(db, user_id=user_id, session_id=session_id)
    if session.summary:
        yield SSE.delta(session.summary, "summary")
        return {"record_id": session.id}

    qas = [qa for qa in _load_qas(db, session.id) if (qa.answer or "").strip() or qa.skipped]
    turns = [
        {
            "seq": qa.seq,
            "question": qa.question,
            "answer": qa.answer,
            "review": qa.review,
            "score": qa.score,
            "skipped": bool(qa.skipped),
        }
        for qa in qas
    ]
    config = resolve_config(db, session.user_id)
    messages = build_interview_summary_messages(
        context=_build_context(db, session, include_jd=False), turns=turns
    )
    pieces: list[str] = []
    for chunk in client.stream_chat(config, messages):
        pieces.append(chunk)
        yield SSE.delta(chunk, "summary")

    summary = "".join(pieces).strip()
    if not summary:
        raise BizException(ErrorCode.LLM_OUTPUT_INVALID, "模型未产出总结内容，请重试")

    now = datetime.now()
    session.summary = summary
    session.status = SessionStatus.FINISHED.value
    if session.finished_at is None:
        session.finished_at = now
    db.commit()
    return {"record_id": session.id}


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
    asked = [qa.question for qa in qas]

    if skip:
        # 跳过轮：被跳题不计分、不出点评，直接进下一题（跳过最后一题则结束）
        return (
            yield from _skip_round(db, session, qas, pending, asked=asked, client=client)
        )
    if not text:
        if pending is not None:
            # 幂等重发：不调 LLM、不落库，断线重试安全（接口文档 3.7 实现口径 3）
            yield SSE.delta(pending.question, "next_question")
            return _done(pending.id, seq=pending.seq)
        # 新会话出首题 / 全部已答未满续出下一题
        return (
            yield from _question_round(db, session, qas, asked=asked, client=client)
        )
    return (
        yield from _answer_round(db, session, qas, pending, text, asked=asked, client=client)
    )


def _skip_round(
    db: Session,
    session: InterviewSession,
    qas: list[InterviewQa],
    pending: InterviewQa,
    *,
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
        yield from _question_round(db, session, qas, asked=asked, client=client, skipped=pending)
    )


def _question_round(
    db: Session,
    session: InterviewSession,
    qas: list[InterviewQa],
    *,
    asked: list[str],
    client: LLMClient,
    skipped: InterviewQa | None = None,
) -> Iterator[str]:
    """出题轮（开场 / 跳过 / 续出下一题）：流正常结束后落新题（跳过轮同时把被跳题置 skipped）。

    新题的阶段由会话的阶段计划推出；项目深挖轮把画像经历一并送进背景（其余阶段不送，省 prefill）。
    """
    seq = len(qas) + 1
    plan = _stage_plan_of(session)
    stage, index, count = _stage_for_seq(plan, seq)
    config = resolve_config(db, session.user_id)
    messages = build_interview_question_messages(
        context=_build_context(db, session, include_experience=_needs_experience(stage)),
        asked=asked,
        stage_note=interview_stage_note(stage, index=index, count=count, plan=plan) if plan else "",
    )
    sections = yield from _stream(client, config, messages, drop_next=False)
    question_text = sections["next_question"]
    if not question_text:
        raise BizException(ErrorCode.LLM_OUTPUT_INVALID, "模型未产出题目，请重试")

    now = datetime.now()
    if skipped is not None:
        skipped.skipped = 1
    record = InterviewQa(
        session_id=session.id, seq=seq, stage=stage, question=question_text, created_at=now
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
    asked: list[str],
    client: LLMClient,
) -> Iterator[str]:
    """作答轮：点评 + 下一题；答满题量轮只点评并同事务置会话 FINISHED。

    点评按本题阶段定侧重（自我介绍 / 技术 / 项目的评判标准不同），下一题按阶段计划推进——
    进入项目深挖段时逐字告诉模型「接下来问什么」，并注入画像经历供其抓项目细节。
    """
    last = pending.seq >= session.question_count
    plan = _stage_plan_of(session)
    next_seq = pending.seq + 1
    next_stage, next_index, next_count = _stage_for_seq(plan, next_seq)
    config = resolve_config(db, session.user_id)
    messages = build_interview_turn_messages(
        context=_build_context(
            db, session, include_experience=_needs_experience(pending.stage, next_stage)
        ),
        asked=asked,
        question=pending.question,
        answer=answer,
        last=last,
        stage_note=interview_review_stage_note(pending.stage),
        next_stage_note=(
            interview_stage_note(next_stage, index=next_index, count=next_count, plan=plan)
            if plan and not last
            else ""
        ),
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
            seq=next_seq,
            stage=next_stage,
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


# ---- 阶段化流程（FR-007）----

INTERVIEW_INTRO_COUNT = 1  # 自我介绍固定 1 题（开场）
INTERVIEW_PROJECT_MAX = 4  # 项目深挖题量上限


def _build_stage_plan(question_count: int, *, has_experience: bool) -> list[dict]:
    """阶段计划：自我介绍 1 题 + 技术问答余量（画像有经历条目再含项目深挖段）。

    项目深挖按题量约 1/4 折算、上限 4 题；无经历条目不设该段——没有项目素材可问。
    """
    project = min(INTERVIEW_PROJECT_MAX, max(1, round(question_count / 4))) if has_experience else 0
    tech = question_count - INTERVIEW_INTRO_COUNT - project
    plan = [
        {"stage": InterviewStage.INTRO.value, "count": INTERVIEW_INTRO_COUNT},
        {"stage": InterviewStage.TECH.value, "count": tech},
    ]
    if project:
        plan.append({"stage": InterviewStage.PROJECT.value, "count": project})
    return plan


def _stage_plan_of(session: InterviewSession) -> list[dict] | None:
    """解析会话的阶段计划；无计划（阶段化上线前的老会话）或数据异常返回 None。"""
    if not session.stage_plan:
        return None
    try:
        plan = json.loads(session.stage_plan)
    except ValueError:
        return None
    return plan if isinstance(plan, list) and plan else None


def _stage_for_seq(plan: list[dict] | None, seq: int) -> tuple[str, int, int]:
    """题号 →（阶段, 阶段内序号, 阶段题量）；无计划按技术问答处理（老会话续答）。"""
    if not plan:
        return InterviewStage.TECH.value, seq, 0
    start = 0
    for item in plan:
        count = int(item.get("count") or 0)
        if seq <= start + count:
            return str(item.get("stage")), seq - start, count
        start += count
    last = plan[-1]  # 超出计划（理论上不会发生）：归末段
    return str(last.get("stage")), seq - start, int(last.get("count") or 0)


def _needs_experience(*stages: str) -> bool:
    """轮次涉及项目深挖时才注入画像经历（其余阶段注入只增 prefill、不起作用）。"""
    return InterviewStage.PROJECT.value in stages


def _experience_text(db: Session, user_id: int) -> str:
    """账号画像的经历条目渲染文本（未填写返回空串；已按 INTERVIEW_EXPERIENCE_LIMIT 截断）。"""
    raw = db.scalar(select(UserProfile.experiences).where(UserProfile.user_id == user_id))
    return build_experience_digest(raw, limit=INTERVIEW_EXPERIENCE_LIMIT)


def _build_context(
    db: Session,
    session: InterviewSession,
    *,
    include_jd: bool = True,
    include_experience: bool = False,
) -> str:
    """出题 / 点评 / 总结共用的背景：公司、岗位、方向（领域中文名）、强度，按需附 JD 与画像经历。

    总结场景传 `include_jd=False`——报告是回顾整场表现，JD 原文只增 prefill 长度、不起作用；
    画像经历只在项目深挖轮注入（`_needs_experience` 判定）。
    """
    lines = [f"公司：{session.company}", f"岗位：{session.position}"]
    if session.direction == Direction.GENERAL.value:
        lines.append("方向：不限（综合考察基础知识与项目经历）")
    else:
        label = _DIRECTION_LABELS.get(session.direction, session.direction)
        lines.append(f"方向：{label}（题目须落在该方向内）")
    lines.append(interview_intensity_note(session.intensity))
    if include_jd and session.application_id is not None:
        jd = _latest_jd_text(db, session.application_id)
        if jd:
            lines.append(f"岗位 JD（节选，供出题贴合岗位要求）：\n{jd[:INTERVIEW_JD_LIMIT]}")
    if include_experience:
        experience = _experience_text(db, session.user_id)
        if experience:
            lines.append(f"画像经历（项目深挖据此提问，不要问经历里没写过的项目）：\n{experience}")
    return "\n".join(lines)


def _latest_jd_text(db: Session, application_id: int) -> str:
    """该投递的 JD 原文：优先读投递记录已填的岗位 JD，回退最近一次 JD 分析的快照（老数据兼容）。"""
    stored = db.scalar(select(Application.jd_text).where(Application.id == application_id))
    if stored and stored.strip():
        return stored.strip()
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


def _stages_of(session: InterviewSession) -> list[StagePlanItem] | None:
    """阶段计划 → DTO 列表；无计划（老会话）或数据异常返回 null（前端降级为「第 N/M 题」）。"""
    plan = _stage_plan_of(session)
    if not plan:
        return None
    try:
        return [StagePlanItem(stage=str(item["stage"]), count=int(item["count"])) for item in plan]
    except (KeyError, TypeError, ValueError):
        return None


def _session_fields(session: InterviewSession) -> dict:
    """会话 ORM 对象 → DTO 公共字段（三种 DTO 复用）。"""
    return {
        "id": session.id,
        "application_id": session.application_id,
        "company": session.company,
        "position": session.position,
        "direction": session.direction,
        "question_count": session.question_count,
        # 存量会话（强度上线前创建）为 NULL，按 MEDIUM 兜底下发，不返回 null（接口文档 3.7）
        "intensity": session.intensity or InterviewIntensity.MEDIUM.value,
        "stages": _stages_of(session),
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
