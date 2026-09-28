"""陪练每轮驱动：一次请求推进一轮（点评 / 追问 / 提示 / 找错 / 复述），接口文档 §3.8。

编排顺序固定：入参校验 → 取内容（LLM 流式或规则判定）→ 落库 → **由状态机决定下一步**。
「该不该继续追问」不交给 LLM（系统设计 §5.10）——模型只负责产出内容与评分，层号与攻击面
一律由 `utils/practice_flow.next_turn` 给出，避免硬凑层数。

三条约定：
- **哪些内容落轮**：用户作答轮（`OPENING` / `FOLLOW_UP` / `REBUTTAL` / `RETELL`）与 AI 单方产出的
  提示轮、材料轮（`HINT`）各落一条；**追问本身只有一句话，不单独落轮**——「追问轮」在接口文档
  §3.8 中指用户被追问后作答的那一轮（`answered_count` 含追问轮、`round_count` 含提示轮与材料轮）；
- **内部段（`_` 前缀）与埋雷段不下发**，但落库存模型原始全文——内部段是结算时重抠判定依据的来源；
- 断连时 `GeneratorExit` 沿 `yield from` 传播，落库语句不会执行——**本轮没产出完的内容不落库**，
  已经落库的既往轮次不受影响，会话仍是 `RUNNING`，下次请求接着推（接口文档 §3.8 实现口径 5）。
"""

import json
import re
from collections.abc import Iterator

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clients.llm_client import LLMClient, LLMConfig, resolve_config
from app.models import PracticeRecord, PracticeSession, Question
from app.models.enums import PracticeMode, QuestionType, RoundKind
from app.prompts import (
    PRACTICE_TURN_SECTION_RULES,
    build_debug_material_messages,
    build_debug_review_messages,
    build_feynman_messages,
    build_hint_messages,
    build_practice_followup_messages,
    build_practice_review_messages,
    build_practice_summary_messages,
)
from app.schemas.practice import PracticeTurnRequest
from app.services import practice_session_service
from app.utils.practice_flow import ATTACK_FACE_ORDER, MAX_LAYERS, is_stuck, next_turn
from app.utils.section_splitter import SectionSplitter, drop_sections, public_text
from app.utils.sse import SSE

# 场景题四维（接口文档 §3.8：一次性 JSON，缺项按 0 计）
DIMENSION_KEYS = ("framework", "quantification", "tradeoff", "fallback")
# 埋雷清单：模型的思考步骤，既不下发也不落库（系统设计 §5.10）
DROPPED_SECTIONS = {"traps"}
EXHAUSTED_SCORE = 9  # 本轮评分到这就算「已挖到底」，状态机不再硬追
ANSWER_KINDS = (RoundKind.OPENING, RoundKind.FOLLOW_UP, RoundKind.REBUTTAL, RoundKind.RETELL)

_SCORE_RE = re.compile(r"评分[^\d]{0,6}(\d{1,2})")
_DIM_RES = {key: re.compile(rf"{key}\D{{0,8}}(\d{{1,2}})") for key in DIMENSION_KEYS}
_PUNCT_RE = re.compile(r"[\s，。、；：？！,.;:?!（）()\[\]【】\"'“”‘’]+")


def ensure_playable(db: Session, *, user_id: int, payload: PracticeTurnRequest) -> PracticeSession:
    """校验这一轮能否受理：会话不存在或跨账号 → 404 + 10002，终态会话再提交 → 400 + 10001。

    由**路由层在 `sse_response` 之前**调用——接口文档 §3.8 要求这三处校验按普通响应体返回、
    不产生 SSE 事件（`run_turn` 是生成器，异常会落到 `error` 事件，故校验不能只在它内部做）。
    """
    session = practice_session_service.get_session(
        db, user_id=user_id, session_id=payload.session_id
    )
    practice_session_service.assert_running(session)
    return session


def run_turn(
    db: Session, *, user_id: int, payload: PracticeTurnRequest, client: LLMClient
) -> Iterator[str]:
    """推进一轮；返回值为 `done` 载荷（`sse_response` 取用）。

    自己再校验一次（`ensure_playable`）：兜住「流式建立后、真正执行前会话被结算」的竞态，
    也让本函数脱离路由层单独调用时同样安全。
    """
    session = ensure_playable(db, user_id=user_id, payload=payload)
    question = db.get(Question, session.question_id)
    records = practice_session_service.load_rounds(db, session_id=session.id)

    if payload.action == "END":
        # 主动结束：本轮不产出内容，只告诉前端「可以结算了」（结算走 finish 接口）
        return _done(None, should_finish=True)
    if payload.action == "HINT":
        return (
            yield from _hint_turn(
                db,
                session=session,
                question=question,
                records=records,
                history=_history(records),
                client=client,
            )
        )
    return (
        yield from _submit_turn(
            db,
            session=session,
            question=question,
            records=records,
            payload=payload,
            client=client,
        )
    )


def _submit_turn(
    db: Session,
    *,
    session: PracticeSession,
    question: Question,
    records: list[PracticeRecord],
    payload: PracticeTurnRequest,
    client: LLMClient,
) -> Iterator[str]:
    """提交作答：按模式与时机分派到「给材料 / 找错 / 复述 / 作答点评 / 客观题规则判定」。"""
    mode = PracticeMode(session.mode)
    history = _history(records)
    material = _material_of(records)

    if mode is PracticeMode.DEBUG and material is None:
        # 挑错模式第 1 轮：给一段「听着顺但有雷」的候选人答案（无作答、无评分）
        raw = yield from _stream(client, _config(db, session), build_debug_material_messages(question))
        record = _save_round(db, session=session, kind=RoundKind.HINT, review=_stored(raw))
        return _done(record.id, should_finish=False)

    if mode is PracticeMode.DEBUG:
        return (
            yield from _scored_turn(
                db,
                session=session,
                question=question,
                records=records,
                payload=payload,
                client=client,
                kind=RoundKind.REBUTTAL,
                messages=build_debug_review_messages(
                    question, material=material, user_report=payload.user_input or ""
                ),
            )
        )

    if mode is PracticeMode.FEYNMAN and not any(
        r.round_kind == RoundKind.RETELL for r in records
    ):
        # 复述轮：不看答案先讲一遍，AI 挑四类漏洞（漏洞条数落内部段，结算时判通过与否）
        return (
            yield from _scored_turn(
                db,
                session=session,
                question=question,
                records=records,
                payload=payload,
                client=client,
                kind=RoundKind.RETELL,
                messages=build_feynman_messages(question, payload.user_input or "", history=history),
            )
        )

    if question.qtype == QuestionType.CHOICE:
        # 客观题：服务端规则比对，零 token 即时返回
        return (
            yield from _choice_turn(
                db, session=session, question=question, records=records, payload=payload, client=client
            )
        )

    return (
        yield from _scored_turn(
            db,
            session=session,
            question=question,
            records=records,
            payload=payload,
            client=client,
            kind=_next_kind(records),
            messages=build_practice_review_messages(
                question, payload.user_input or "", history=history
            ),
        )
    )


def _scored_turn(
    db: Session,
    *,
    session: PracticeSession,
    question: Question,
    records: list[PracticeRecord],
    payload: PracticeTurnRequest,
    client: LLMClient,
    kind: RoundKind,
    messages: list[dict],
) -> Iterator[str]:
    """有评分的作答轮：流式点评 → 抽分落库 → 交状态机决定下一步。"""
    raw = yield from _stream(client, _config(db, session), messages)
    record = _save_round(
        db,
        session=session,
        kind=kind,
        answer=_answer_of(payload),
        score=_extract_score(raw),
        review=_stored(raw),
        elapsed_ms=payload.elapsed_ms,
    )
    return (
        yield from _proceed(
            db,
            session=session,
            question=question,
            records=records,
            record=record,
            payload=payload,
            client=client,
        )
    )


def _choice_turn(
    db: Session,
    *,
    session: PracticeSession,
    question: Question,
    records: list[PracticeRecord],
    payload: PracticeTurnRequest,
    client: LLMClient,
) -> Iterator[str]:
    """客观题：归一化比对判对错，评分与点评由服务端拼（产出结构与作答轮一致）。"""
    correct = _judge_choice(question.answer, payload.user_input or "")
    score = 10 if correct else 0
    score_text = f"## 本轮评分\n评分 {score}/10，{'答对了' if correct else '答错了'}。\n"
    review_text = f"\n## 点评\n{_choice_review(question, payload.user_input or '', correct)}"
    yield SSE.delta(score_text, "round_score")
    yield SSE.delta(review_text, "review")
    record = _save_round(
        db,
        session=session,
        kind=_next_kind(records),
        answer=_answer_of(payload),
        score=score,
        review=_stored(score_text + review_text),
        elapsed_ms=payload.elapsed_ms,
    )
    return (
        yield from _proceed(
            db,
            session=session,
            question=question,
            records=records,
            record=record,
            payload=payload,
            client=client,
        )
    )


def _proceed(
    db: Session,
    *,
    session: PracticeSession,
    question: Question,
    records: list[PracticeRecord],
    record: PracticeRecord,
    payload: PracticeTurnRequest,
    client: LLMClient,
) -> Iterator[str]:
    """本轮落库之后：由状态机决定追问 / 提示 / 收尾（模型不参与这个判断）。"""
    mode = PracticeMode(session.mode)
    decision = next_turn(
        mode=mode,
        round_index=record.round_index,
        # 「已发生的追问轮数」含本轮——本轮就是一次追问作答（`record` 刚落库，不在旧快照里）
        follow_up_count=_follow_up_count([*records, record]),
        last_result=_last_result(records, payload.user_input),
        exhausted=record.score is not None and record.score >= EXHAUSTED_SCORE,
    )
    history = _history([*records, record])

    if decision.action == "FOLLOW_UP":
        if mode is PracticeMode.DEBUG:
            # 挑错模式的「追问」= 再来一段材料：材料轮是 AI 单方产出，落 `HINT` 轮（同首轮）
            raw = yield from _stream(
                client, _config(db, session), build_debug_material_messages(question)
            )
            material = _save_round(db, session=session, kind=RoundKind.HINT, review=_stored(raw))
            return _done(material.id, should_finish=False)
        # 其余模式的追问只有一句话，**不单独落轮**——「追问轮」在本系统指用户被追问后作答的那一轮
        yield from _stream(
            client,
            _config(db, session),
            build_practice_followup_messages(question, history=history, face=decision.face),
        )
        return _done(
            record.id,
            should_finish=False,
            layer=decision.layer,
            face=decision.face.value if decision.face else None,
        )

    if decision.action == "HINT":
        # 教练模式：答不上来时先给一条方向性提示，随后仍在同一层继续
        return (
            yield from _hint_turn(
                db,
                session=session,
                question=question,
                records=records,
                history=history,
                client=client,
            )
        )

    return (
        yield from _settle(
            db, session=session, question=question, record=record, history=history, client=client
        )
    )


def _hint_turn(
    db: Session,
    *,
    session: PracticeSession,
    question: Question,
    records: list[PracticeRecord],
    history: list[dict],
    client: LLMClient,
) -> Iterator[str]:
    """提示轮（用户求提示 / 教练模式答不上自动降级）：只给方向不给答案，且不推进追问层。"""
    raw = yield from _stream(client, _config(db, session), build_hint_messages(question, history=history))
    record = _save_round(db, session=session, kind=RoundKind.HINT, review=_stored(raw))
    session.hint_count += 1
    db.commit()
    layer, face = _current_face(records)
    return _done(record.id, should_finish=False, layer=layer, face=face)


def _settle(
    db: Session,
    *,
    session: PracticeSession,
    question: Question,
    record: PracticeRecord,
    history: list[dict],
    client: LLMClient,
) -> Iterator[str]:
    """本场收尾：`QUICK` 直接给参考答案（零 token），其余模式补一段跨轮总结并进本轮记录。"""
    if PracticeMode(session.mode) is PracticeMode.QUICK:
        yield SSE.delta(f"## 参考答案\n{question.answer}\n", "reference_answer")
        return _done(record.id, should_finish=True)
    raw = yield from _stream(
        client, _config(db, session), build_practice_summary_messages(question, history=history)
    )
    _append_to_round(db, record, raw)
    return _done(record.id, should_finish=True)


# ---------- 流式产出 ----------


def _stream(client: LLMClient, config: LLMConfig, messages: list[dict]) -> Iterator[str]:
    """流式产出并按段过滤，返回模型原始全文（含内部段，供落库与结算重抠）。

    `dimensions` 段攒完一次性发一条 JSON——四维得分是「分项 + 总分」的呈现结构，
    逐字增量对前端没有意义（接口文档 §3.8）。
    """
    splitter = SectionSplitter(PRACTICE_TURN_SECTION_RULES)
    pieces: list[str] = []
    dimensions = ""
    for chunk in client.stream_chat(config, messages):
        pieces.append(chunk)
        for text, section in splitter.feed(chunk):
            if section == "dimensions":
                dimensions += text
            elif _is_downstream(section):
                yield SSE.delta(text, section)
    for text, section in splitter.flush():
        if section == "dimensions":
            dimensions += text
        elif _is_downstream(section):
            yield SSE.delta(text, section)
    if dimensions.strip():
        yield SSE.delta(_dimensions_json(dimensions), "dimensions")
    return "".join(pieces)


def _is_downstream(section: str | None) -> bool:
    """该段是否可下发：内部段与埋雷段只给服务端看；未识别出标题则按纯文本降级透传。"""
    if section is None:
        return True
    return not section.startswith("_") and section not in DROPPED_SECTIONS


def _dimensions_json(text: str) -> str:
    """四维得分段（自由文本）→ `{"framework":8,...}`，抠不出的维度按 0 计。"""
    return json.dumps({key: _dimension_score(text, key) for key in DIMENSION_KEYS}, ensure_ascii=False)


def _dimension_score(text: str, key: str) -> int:
    match = _DIM_RES[key].search(text)
    if not match:
        return 0
    value = int(match.group(1))
    return value if 0 <= value <= 10 else 0


# ---------- 落库 ----------


def _save_round(
    db: Session,
    *,
    session: PracticeSession,
    kind: RoundKind,
    answer: str | None = None,
    score: int | None = None,
    review: str | None = None,
    elapsed_ms: int | None = None,
) -> PracticeRecord:
    """落库一轮。轮次号取库里最大值 +1——一次请求可能连落两轮（作答 + 提示），内存快照会重号。"""
    record = PracticeRecord(
        user_id=session.user_id,
        question_id=session.question_id,
        session_id=session.id,
        round_index=_next_index(db, session_id=session.id),
        round_kind=kind,
        user_answer=answer,
        score=score,
        review=review,
        elapsed_ms=elapsed_ms,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _append_to_round(db: Session, record: PracticeRecord, text: str) -> None:
    """把收尾总结并进本轮记录（不新增轮次）——落库文本与本次下发的 delta 拼接保持一致。"""
    extra = _stored(text).strip()
    if extra:
        record.review = f"{record.review or ''}\n{extra}"
        db.commit()


def _stored(raw: str) -> str:
    """落库文本：丢掉埋雷清单，保留内部判定段（结算要重抠命中率与漏洞条数）。"""
    return drop_sections(raw, PRACTICE_TURN_SECTION_RULES, DROPPED_SECTIONS)


# ---------- 状态推导 ----------


def _config(db: Session, session: PracticeSession) -> LLMConfig:
    return resolve_config(db, session.user_id)


def _next_index(db: Session, *, session_id: int) -> int:
    current = db.execute(
        select(func.max(PracticeRecord.round_index)).where(PracticeRecord.session_id == session_id)
    ).scalar()
    return (current or 0) + 1


def _next_kind(records: list[PracticeRecord]) -> RoundKind:
    """作答轮类型：本场第一次作答是 `OPENING`，之后都是 `FOLLOW_UP`。"""
    return RoundKind.OPENING if not records else RoundKind.FOLLOW_UP


def _answer_of(payload: PracticeTurnRequest) -> str:
    """作答轮的作答原文：**空值落空串而非 null**——null 是「AI 单方产出的轮次」的标记，
    超时一字未写要能与它区分开（前者计断点，后者不计，接口文档 §3.8 实现口径 6）。"""
    return payload.user_input or ""


def _follow_up_count(records: list[PracticeRecord]) -> int:
    """已发生的追问轮数——即用户**被追问后作答**的轮数（`FOLLOW_UP` 轮的口径见 §3.8）。

    提示轮与材料轮是 AI 单方产出，不计数，故提示之后仍停在同一层。
    """
    return sum(1 for r in records if r.round_kind == RoundKind.FOLLOW_UP)


def _current_face(records: list[PracticeRecord]) -> tuple[int, str]:
    """当前作答所处的层与攻击面——下一轮的落点，提示帮的就是这一层。"""
    layer = min(_follow_up_count(records) + 1, MAX_LAYERS)
    return layer, ATTACK_FACE_ORDER[layer - 1].value


def _last_result(records: list[PracticeRecord], user_input: str | None) -> str:
    """本轮结果：答不上 → `STUCK`；上一轮刚给过提示仍答不上 → `HINT_USED`（教练模式据此记断点）。"""
    if not is_stuck(user_input):
        return "OK"
    if records and records[-1].round_kind == RoundKind.HINT:
        return "HINT_USED"
    return "STUCK"


def _material_of(records: list[PracticeRecord]) -> str | None:
    """挑错模式最新一段材料全文；没给过材料返回 None（首轮据此分流）。"""
    for record in reversed(records):
        if record.round_kind == RoundKind.HINT:
            return public_text(record.review or "", PRACTICE_TURN_SECTION_RULES)
    return None


def _history(records: list[PracticeRecord]) -> list[dict]:
    """喂给 prompt 的历史轮次——内部段剥掉，判定 JSON 是服务端的依据，不该回灌给模型。"""
    return [
        {
            "round_index": r.round_index,
            "user_input": r.user_answer,
            "review": public_text(r.review or "", PRACTICE_TURN_SECTION_RULES),
        }
        for r in records
    ]


def _done(
    record_id: int | None, *, should_finish: bool, layer: int | None = None, face: str | None = None
) -> dict:
    """`done` 载荷（接口文档 §3.8）：`extra` 告诉前端是否收尾、下一轮在第几层。"""
    return {
        "record_id": record_id,
        "extra": {"should_finish": should_finish, "layer": layer, "face": face},
    }


# ---------- 客观题规则判定 ----------


def _judge_choice(answer: str, user_input: str) -> bool:
    """客观题规则比对：归一化（去空白标点、转小写）后互相包含即判对。

    题库的客观题只有标准答案、没有选项数组，故不做选项匹配。
    """
    expected, got = _normalize(answer), _normalize(user_input)
    return bool(expected) and bool(got) and (expected in got or got in expected)


def _normalize(text: str) -> str:
    return _PUNCT_RE.sub("", text).lower()


def _choice_review(question: Question, user_input: str, correct: bool) -> str:
    """客观题点评：直接给标准答案 + 一句差在哪（规则判定，不调 LLM）。"""
    if correct:
        return f"答对了。标准答案是「{question.answer}」。"
    said = user_input.strip() or "（未作答）"
    return f"你答的是「{said}」，标准答案是「{question.answer}」。对着标准答案再核一遍。"


def _extract_score(text: str) -> int | None:
    """从「本轮评分」段抠 0~10 的分数；抠不到记 null（该轮不计入综合分均值）。"""
    match = _SCORE_RE.search(text)
    if not match:
        return None
    value = int(match.group(1))
    return value if 0 <= value <= 10 else None
