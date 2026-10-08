"""练习模式：题目管理与逐遍点评业务逻辑（接口文档 3.15；FR-020）。

- REST：题目列表 / 新建（题面可 AI 生成）/ 详情 / 编辑与归档、单次练习详情、进步对比；
- SSE：`POST /stream/drill-review` 一次作答流式点评（`score` → `review` 两段），表达力指标由
  纯函数在流式开始前算出（零 token），随 `done.extra.voice_metrics` 先于点评一次性下发；
- 落库时机：整遍内容生成完且流正常结束才写库，断连或中途失败不落任何记录（重试 = 整遍重发）；
- **只记来源不复制内容**：`drill_topic.ref_id` 只用于回跳与标注，归属校验走各来源表。
"""

import json
import re
from collections.abc import Iterator

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clients.llm_client import LLMClient, LLMConfig, resolve_config
from app.exceptions import BizException, ErrorCode
from app.models import (
    Application,
    DrillAttempt,
    DrillTopic,
    Experience,
    ExperienceItem,
    Question,
    WrongQuestion,
)
from app.models.enums import DrillSource, VoiceQuality
from app.prompts import (
    DRILL_REVIEW_SECTION_RULES,
    build_drill_question_messages,
    build_drill_review_messages,
)
from app.schemas.common import PageData
from app.schemas.drill import (
    DrillAttemptDTO,
    DrillAttemptItem,
    DrillCreateRequest,
    DrillListItem,
    DrillProgressDTO,
    DrillProgressDeltas,
    DrillProgressItem,
    DrillTopicDTO,
    DrillTopicDetailData,
    DrillUpdateRequest,
)
from app.utils.section_splitter import SectionSplitter
from app.utils.speech_metrics import compute_voice_metrics
from app.utils.sse import SSE

# 来源 → 归属校验模型（ref_id 指向该来源表主键；CUSTOM 手动写题、INTRO 免来源实体）
_REF_MODELS: dict[str, type] = {
    DrillSource.WRONG.value: WrongQuestion,
    DrillSource.EXPERIENCE.value: Experience,
    DrillSource.JD.value: Application,
}

# AI 生成题面时的来源摘要上限（只送够出题的素材，不送整篇）
_WRONG_NOTE_LIMIT = 500  # 错题题干摘要
_EXPERIENCE_ITEM_LIMIT = 3  # 面经条目取前几条
_JD_NOTE_LIMIT = 800  # 岗位 JD 节选

# 题面生成解析失败的重试次数（与错题判定同口径：解析不出重试 1 次，仍不行报 10011）
_GENERATE_RETRY = 1

# 点评评分段的提取（prompt 约束输出「数字/10」；容忍「8 分」与「评分：」前缀的宽松匹配）
_SCORE_RE = re.compile(r"(?<![\d.])(\d{1,2})\s*(?:/\s*10|分)")


def list_topics(
    db: Session,
    *,
    user_id: int,
    archived: bool | None,
    source: DrillSource | None,
    page: int,
    page_size: int,
) -> PageData[DrillListItem]:
    """题目列表：默认只返回未归档（`archived=true` 查已归档）；`attempt_count` /
    `last_score` / `best_score` 为聚合字段（查完当前页题目后按 topic 归并，避免逐条查库）。"""
    conditions = [DrillTopic.user_id == user_id, DrillTopic.archived == (1 if archived else 0)]
    if source is not None:
        conditions.append(DrillTopic.source == source.value)

    total = db.execute(select(func.count()).select_from(DrillTopic).where(*conditions)).scalar_one()
    topics = list(
        db.execute(
            select(DrillTopic)
            .where(*conditions)
            .order_by(DrillTopic.created_at.desc(), DrillTopic.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).scalars()
    )
    stats = _attempt_stats(db, [topic.id for topic in topics])
    items = []
    for topic in topics:
        count, last_score, best_score = stats.get(topic.id, (0, None, None))
        items.append(
            DrillListItem(
                **_topic_fields(topic),
                attempt_count=count,
                last_score=last_score,
                best_score=best_score,
            )
        )
    return PageData(total=total, items=items)


def _attempt_stats(
    db: Session, topic_ids: list[int]
) -> dict[int, tuple[int, int | None, int | None]]:
    """批量聚合练习情况：`{topic_id: (练习遍数, 最近非空得分, 历史最高得分)}`。"""
    if not topic_ids:
        return {}
    rows = db.execute(
        select(DrillAttempt.topic_id, DrillAttempt.score)
        .where(DrillAttempt.topic_id.in_(topic_ids))
        .order_by(DrillAttempt.seq)
    ).all()
    counts: dict[int, int] = {}
    scores: dict[int, list[int]] = {}
    for topic_id, score in rows:
        counts[topic_id] = counts.get(topic_id, 0) + 1
        if score is not None:
            scores.setdefault(topic_id, []).append(score)
    result: dict[int, tuple[int, int | None, int | None]] = {}
    for topic_id in topic_ids:
        topic_scores = scores.get(topic_id, [])
        result[topic_id] = (
            counts.get(topic_id, 0),
            topic_scores[-1] if topic_scores else None,
            max(topic_scores) if topic_scores else None,
        )
    return result


def create_topic(
    db: Session, *, user_id: int, payload: DrillCreateRequest, client: LLMClient
) -> DrillTopicDTO:
    """新建题目：题面不传（或空串）时由 AI 按 title + 来源生成（未配 Key → 10012、生成失败 → 10011）。

    `ref_id` 规则（接口文档 3.15）：CUSTOM / INTRO 无来源实体（传了 → 10001）；WRONG /
    EXPERIENCE / JD 必填并校验归属（不存在或跨账号 → 404+10002）；RESUME 的 ref_id 语义未定
    （画像经历存在 JSON 数组里、条目没有独立 id），暂不支持导入。
    """
    source = payload.source.value
    if source == DrillSource.RESUME.value:
        raise BizException(ErrorCode.PARAM_INVALID, "暂不支持从画像经历导入，请改用手动写题")
    if source in _REF_MODELS:
        if payload.ref_id is None:
            raise BizException(ErrorCode.PARAM_INVALID, "该来源必须提供 ref_id")
        _verify_ref(db, user_id, source, payload.ref_id)
    elif payload.ref_id is not None:
        raise BizException(ErrorCode.PARAM_INVALID, "该来源无需 ref_id")

    question = (payload.question or "").strip()
    if not question:
        question = _generate_question(db, user_id, payload, client=client)
    topic = DrillTopic(
        user_id=user_id,
        title=payload.title,
        question=question,
        source=source,
        ref_id=payload.ref_id,
    )
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return DrillTopicDTO(**_topic_fields(topic))


def _verify_ref(db: Session, user_id: int, source: str, ref_id: int) -> None:
    """来源实体归属校验：不存在或不属于当前账号一律 404 + 10002（与「不存在」不可区分）。"""
    model = _REF_MODELS[source]
    row = db.get(model, ref_id)
    if row is None or row.user_id != user_id:
        raise BizException(ErrorCode.NOT_FOUND, "来源条目不存在")


def _generate_question(
    db: Session, user_id: int, payload: DrillCreateRequest, *, client: LLMClient
) -> str:
    """AI 生成题面：来源摘要 + 标题交给模型（chat_json）；解析不出重试 1 次，仍不行报 10011。

    配置解析放在此处而非入口：手填题面不需要配 Key，只有真的要走 AI 生成时才校验账号配置。
    """
    config = resolve_config(db, user_id)
    messages = build_drill_question_messages(
        title=payload.title,
        source=payload.source.value,
        source_note=_source_note(db, payload.source.value, payload.ref_id),
    )
    for _ in range(_GENERATE_RETRY + 1):
        try:
            result = client.chat_json(config, messages)
        except BizException as exc:
            if exc.code != ErrorCode.LLM_OUTPUT_INVALID:  # 未配置 / 鉴权失败等不重试
                raise
            continue
        question = result.get("question")
        if isinstance(question, str) and question.strip():
            return question.strip()
    raise BizException(ErrorCode.LLM_OUTPUT_INVALID, "模型未产出题面，请重试")


def _source_note(db: Session, source: str, ref_id: int | None) -> str:
    """题面生成的来源摘要：错题题干 / 面经公司与题目列表 / 岗位 JD 节选；CUSTOM / INTRO 为空串。"""
    if ref_id is None or source not in _REF_MODELS:
        return ""
    if source == DrillSource.WRONG.value:
        content = db.scalar(
            select(Question.content)
            .join(WrongQuestion, WrongQuestion.question_id == Question.id)
            .where(WrongQuestion.id == ref_id)
        )
        return (content or "")[:_WRONG_NOTE_LIMIT]
    if source == DrillSource.EXPERIENCE.value:
        experience = db.get(Experience, ref_id)
        return _experience_note(db, experience)
    application = db.get(Application, ref_id)
    return _jd_note(application)


def _experience_note(db: Session, experience: Experience | None) -> str:
    """面经摘要：公司 · 岗位 + 前几条面试问题。"""
    head = " · ".join(v for v in (experience.company, experience.position) if v) if experience else ""
    questions = (
        db.execute(
            select(ExperienceItem.question)
            .where(ExperienceItem.experience_id == experience.id)
            .order_by(ExperienceItem.id)
            .limit(_EXPERIENCE_ITEM_LIMIT)
        )
        .scalars()
        .all()
        if experience
        else []
    )
    lines = [f"面经：{head}"] if head else ["面经"]
    if questions:
        lines.append("其中的题目：")
        lines.extend(f"- {item}" for item in questions)
    return "\n".join(lines)


def _jd_note(application: Application | None) -> str:
    """投递岗位摘要：公司 · 岗位 + 岗位 JD 节选。"""
    head = " · ".join(v for v in (application.company, application.position) if v) if application else ""
    lines = [f"投递岗位：{head}"] if head else ["投递岗位"]
    jd_text = (application.jd_text or "").strip() if application else ""
    if jd_text:
        lines.append("岗位 JD（节选）：")
        lines.append(jd_text[:_JD_NOTE_LIMIT])
    return "\n".join(lines)


def get_topic_detail(db: Session, *, user_id: int, topic_id: int) -> DrillTopicDetailData:
    """题目详情：题目字段 + 练习记录摘要（按 seq 升序；摘要不含点评全文与表达指标）。"""
    topic = _get_topic(db, user_id, topic_id)
    attempts = db.execute(
        select(DrillAttempt).where(DrillAttempt.topic_id == topic.id).order_by(DrillAttempt.seq)
    ).scalars()
    return DrillTopicDetailData(
        **_topic_fields(topic), attempts=[_to_attempt_item(attempt) for attempt in attempts]
    )


def update_topic(
    db: Session, *, user_id: int, topic_id: int, payload: DrillUpdateRequest
) -> DrillTopicDTO:
    """部分更新：只改请求体里出现过的字段；归档与恢复共用 `archived`（归档不删历史记录）。"""
    topic = _get_topic(db, user_id, topic_id)
    if payload.title is not None:
        topic.title = payload.title
    if payload.question is not None:
        topic.question = payload.question
    if payload.archived is not None:
        topic.archived = 1 if payload.archived else 0
    db.commit()
    db.refresh(topic)
    return DrillTopicDTO(**_topic_fields(topic))


def get_attempt(db: Session, *, user_id: int, topic_id: int, attempt_id: int) -> DrillAttemptDTO:
    """单次练习详情：先校验题目归属，再校验记录属于该题；任一不匹配一律 404 + 10002。"""
    _get_topic(db, user_id, topic_id)
    attempt = db.get(DrillAttempt, attempt_id)
    if attempt is None or attempt.topic_id != topic_id:
        raise BizException(ErrorCode.NOT_FOUND, "练习记录不存在")
    return _to_attempt_dto(attempt)


def get_progress(db: Session, *, user_id: int, topic_id: int) -> DrillProgressDTO:
    """跨次进步对比：逐遍数据点按 seq 升序；`deltas` 为最近两条可比记录的差值（`to - from`）。

    可比口径（接口文档 3.15）：与**最新一条有指标记录**的 `voice_metrics.version` 不一致的
    遍次不进列表（宁可少展示一次对比，也不给失真曲线）；无指标的遍次保留（其表达字段为
    null，前端跳过该点不画）；指标 JSON 解析失败按无指标处理。
    """
    _get_topic(db, user_id, topic_id)
    attempts = list(
        db.execute(
            select(DrillAttempt)
            .where(DrillAttempt.topic_id == topic_id)
            .order_by(DrillAttempt.seq)
        ).scalars()
    )
    latest_version = None
    for attempt in reversed(attempts):
        if attempt.voice_metrics:
            metrics = _load_metrics(attempt.voice_metrics)
            latest_version = (metrics or {}).get("version")
            break

    items: list[DrillProgressItem] = []
    for attempt in attempts:
        metrics = _load_metrics(attempt.voice_metrics)
        if (
            metrics is not None
            and latest_version is not None
            and metrics.get("version") != latest_version
        ):
            continue
        items.append(_to_progress_item(attempt, metrics))

    deltas = None
    if len(items) >= 2:
        from_item, to_item = items[-2], items[-1]
        deltas = DrillProgressDeltas(
            score=_diff(from_item.score, to_item.score),
            duration_ms=_diff(from_item.duration_ms, to_item.duration_ms),
            filler_count=_diff(from_item.filler_count, to_item.filler_count),
            pause_count=_diff(from_item.pause_count, to_item.pause_count),
        )
    return DrillProgressDTO(
        topic_id=topic_id, attempt_count=len(attempts), items=items, deltas=deltas
    )


def ensure_answerable(db: Session, *, user_id: int, topic_id: int) -> DrillTopic:
    """作答前校验（在流式建立之前执行）：不存在 / 跨账号 → 404+10002；已归档 → 409+40003。"""
    topic = _get_topic(db, user_id, topic_id)
    if topic.archived:
        raise BizException(ErrorCode.DRILL_TOPIC_ARCHIVED)
    return topic


def run_review(
    db: Session,
    *,
    user_id: int,
    topic_id: int,
    answer: str,
    is_voice: bool,
    segments: list[dict] | None,
    duration_ms: int | None,
    client: LLMClient,
) -> Iterator[str]:
    """一次练习点评（业务生成器）：`yield` SSE 事件、`return` done 载荷（接口文档 3.15）。

    delta 的 section 依次 `score` / `review`（标题行随段下发，落库全文恒等于 delta 拼接）。
    表达力指标先于点评算出（纯函数、零 token）：quality=OK 时注入点评 prompt、随整遍落库并
    `done.extra.voice_metrics` 下发；作答过短（TOO_SHORT）或纯文字（TEXT_ONLY）时不下发、
    不落库，只记 `is_voice`。点评段缺失报 10011（评分段取不到记 null，不拦）。
    """
    topic = ensure_answerable(db, user_id=user_id, topic_id=topic_id)
    metrics = compute_voice_metrics(segments)
    voice_metrics = metrics if metrics["quality"] == VoiceQuality.OK.value else None
    config = resolve_config(db, user_id)
    messages = build_drill_review_messages(
        title=topic.title, question=topic.question, answer=answer, voice_metrics=voice_metrics
    )
    buckets = yield from _stream(client, config, messages)
    review = buckets["review"]
    if not review:
        raise BizException(ErrorCode.LLM_OUTPUT_INVALID, "模型未产出点评内容，请重试")

    record = DrillAttempt(
        topic_id=topic.id,
        seq=_next_seq(db, topic.id),
        answer=answer,
        is_voice=1 if is_voice else 0,
        voice_metrics=json.dumps(voice_metrics, ensure_ascii=False) if voice_metrics else None,
        score=_extract_score(buckets["score"]),
        review=review,
        duration_ms=duration_ms,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _done(record.id, seq=record.seq, voice_metrics=voice_metrics)


def _stream(
    client: LLMClient, config: LLMConfig, messages: list[dict]
) -> Iterator[str]:
    """流式下发 delta，返回 `{"score": ..., "review": ...}`（段内文本恒等于 delta 拼接）。

    段落归属只看标题行：**首个标题出现前的内容整段丢弃**（模型寒暄或没按格式输出），既不下发
    也不落库；是否落库由调用方按「review 段是否为空」判定。
    """
    buckets: dict[str, list[str]] = {"score": [], "review": []}
    for text, section in _iter_pieces(client, config, messages):
        if section is None:
            continue
        buckets[section].append(text)
        yield SSE.delta(text, section)
    return {name: "".join(parts).strip() for name, parts in buckets.items()}


def _iter_pieces(
    client: LLMClient, config: LLMConfig, messages: list[dict]
) -> Iterator[tuple[str, str | None]]:
    """逐块喂切分器产出 `(文本, 段名)`，收尾冲刷残留（段名 None = 尚未出现标题的前导文本）。"""
    splitter = SectionSplitter(DRILL_REVIEW_SECTION_RULES)
    for chunk in client.stream_chat(config, messages):
        yield from splitter.feed(chunk)
    yield from splitter.flush()


def _next_seq(db: Session, topic_id: int) -> int:
    """下一遍次 = 该题现有最大 seq + 1（单账号串行作答，不建唯一约束）。"""
    current = db.execute(
        select(func.max(DrillAttempt.seq)).where(DrillAttempt.topic_id == topic_id)
    ).scalar()
    return (current or 0) + 1


def _extract_score(score_text: str) -> int | None:
    """从评分段抠 0~10 的整数分；取不到或越界记 null（前端从点评正文兜底解析，不阻断落库）。"""
    matched = _SCORE_RE.search(score_text)
    if matched is None:
        return None
    score = int(matched.group(1))
    return score if 0 <= score <= 10 else None


def _diff(from_value: int | None, to_value: int | None) -> int | None:
    """差值 = `to - from`；任一为空记 null（不把缺失当 0）。"""
    if from_value is None or to_value is None:
        return None
    return to_value - from_value


def _get_topic(db: Session, user_id: int, topic_id: int) -> DrillTopic:
    """按 id 取题并校验归属；不存在或不属于当前账号一律 404 + 10002。"""
    topic = db.get(DrillTopic, topic_id)
    if topic is None or topic.user_id != user_id:
        raise BizException(ErrorCode.NOT_FOUND, "题目不存在或不属于当前账号")
    return topic


def _topic_fields(topic: DrillTopic) -> dict:
    """题目公共字段（DTO 与详情响应共用）。"""
    return {
        "id": topic.id,
        "title": topic.title,
        "question": topic.question,
        "source": topic.source,
        "ref_id": topic.ref_id,
        "archived": topic.archived,
        "created_at": topic.created_at,
        "updated_at": topic.updated_at,
    }


def _to_attempt_item(attempt: DrillAttempt) -> DrillAttemptItem:
    """练习记录摘要（不含点评全文与表达指标）。"""
    return DrillAttemptItem(
        id=attempt.id,
        seq=attempt.seq,
        is_voice=attempt.is_voice,
        score=attempt.score,
        duration_ms=attempt.duration_ms,
        created_at=attempt.created_at,
    )


def _to_attempt_dto(attempt: DrillAttempt) -> DrillAttemptDTO:
    """单次练习完整 DTO（含点评全文与表达指标）。"""
    return DrillAttemptDTO(
        id=attempt.id,
        topic_id=attempt.topic_id,
        seq=attempt.seq,
        answer=attempt.answer,
        is_voice=attempt.is_voice,
        voice_metrics=_load_metrics(attempt.voice_metrics),
        score=attempt.score,
        review=attempt.review,
        duration_ms=attempt.duration_ms,
        created_at=attempt.created_at,
    )


def _to_progress_item(attempt: DrillAttempt, metrics: dict | None) -> DrillProgressItem:
    """单遍数据点：表达字段取自 voice_metrics（无指标或字段缺失记 null）。"""
    pauses = metrics.get("pauses") if metrics else None
    return DrillProgressItem(
        seq=attempt.seq,
        score=attempt.score,
        duration_ms=attempt.duration_ms,
        speech_rate=_int_of(metrics.get("speech_rate") if metrics else None),
        filler_count=_int_of(metrics.get("filler_count") if metrics else None),
        pause_count=len(pauses) if isinstance(pauses, list) else None,
        speech_ratio=_float_of(metrics.get("speech_ratio") if metrics else None),
    )


def _load_metrics(raw: str | None) -> dict | None:
    """voice_metrics 文本列 → 字典；空值或解析失败返回 None（历史脏数据不阻断查询）。"""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _int_of(value: object) -> int | None:
    """转 int；非数字（含布尔）返回 None。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _float_of(value: object) -> float | None:
    """转 float；非数字（含布尔）返回 None。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _done(record_id: int, *, seq: int, voice_metrics: dict | None = None) -> dict:
    """done 载荷（协议层组装事件）：`seq` 为本遍练次；语音作答且指标算出时附 `voice_metrics`。"""
    extra: dict = {}
    if voice_metrics is not None:
        extra["voice_metrics"] = voice_metrics
    return {"record_id": record_id, "seq": seq, "extra": extra or None}
