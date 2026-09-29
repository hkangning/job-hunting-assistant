"""错题本：入本 / 列表 / 添加 / 删除 / 复习判定（接口文档 3.9；档位规则见数据库设计 3.9）。

复习档位：答对 `review_stage +1`（四档走完置 `mastered_at`）、答错重置回第 1 档且 `wrong_count +1`，
每次复习后 `next_review_at = 现在 + 新档位间隔`（1 / 3 / 7 / 15 天）。
判定按题型分型（系统设计 §5.3）：`CHOICE` 规则比对零 token，`SUBJECTIVE` / `SCENARIO` 走 LLM 非流式 JSON。
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clients.llm_client import LLMClient, resolve_config
from app.exceptions import BizException, ErrorCode
from app.models import Question, WrongQuestion
from app.models.enums import QuestionSource, QuestionType, Stack, WrongSourceType
from app.prompts import build_wrong_question_judge_messages
from app.schemas.common import PageData
from app.schemas.wrong_question import (
    WrongQuestionAddRequest,
    WrongQuestionItem,
    WrongQuestionReviewData,
)
from app.services import practice_service
from app.utils.practice_flow import expand_choice_input, judge_choice, parse_options

REVIEW_STAGE_DAYS = (1, 3, 7, 15)  # 复习档位 1~4 对应的间隔天数（数据库设计 §3.9）
MAX_REVIEW_STAGE = len(REVIEW_STAGE_DAYS)  # 走完四档即掌握
JUDGE_RETRY = 1  # LLM 判定解析失败的重试次数（系统设计 §7：重试 1 次后报 10011）


def upsert_wrong_question(
    db: Session, *, user_id: int, question_id: int, now: datetime
) -> WrongQuestion:
    """陪练未通过则入错题本：已在本则档位重置回第 1 档、答错次数累加、退出「已掌握」。"""
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


def list_wrong_questions(
    db: Session, *, user_id: int, status: str | None, page: int, page_size: int
) -> PageData[WrongQuestionItem]:
    """错题列表。排序 = 未掌握优先、再按到期先后（错题本是复习工具，先看该复习的）。"""
    conditions = [WrongQuestion.user_id == user_id]
    if status == "PENDING":
        conditions.append(WrongQuestion.mastered_at.is_(None))
    elif status == "MASTERED":
        conditions.append(WrongQuestion.mastered_at.is_not(None))

    total = db.execute(
        select(func.count()).select_from(WrongQuestion).where(*conditions)
    ).scalar_one()
    rows = db.execute(
        select(WrongQuestion, Question)
        .join(Question, Question.id == WrongQuestion.question_id)
        .where(*conditions)
        .order_by(
            WrongQuestion.mastered_at.is_not(None),
            WrongQuestion.next_review_at,
            WrongQuestion.id,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PageData(total=total, items=[_to_item(row, question) for row, question in rows])


def add_wrong_question(
    db: Session, *, user_id: int, payload: WrongQuestionAddRequest
) -> WrongQuestionItem:
    """手动添加：题库题形态给 `question_id`，知识点形态自动建题（题干已在题库则复用）。"""
    if payload.question_id is not None:
        question = db.get(Question, payload.question_id)
        if question is None:
            raise BizException(ErrorCode.NOT_FOUND, "题目不存在")
        source_type = WrongSourceType.MANUAL
    else:
        question = _find_or_create_question(db, payload)
        source_type = WrongSourceType(payload.source_type)

    existing = db.execute(
        select(WrongQuestion).where(
            WrongQuestion.user_id == user_id, WrongQuestion.question_id == question.id
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise BizException(ErrorCode.CONFLICT, "该题已在错题本")

    row = WrongQuestion(
        user_id=user_id,
        question_id=question.id,
        source_type=source_type,
        review_stage=1,
        next_review_at=datetime.now() + timedelta(days=REVIEW_STAGE_DAYS[0]),
        wrong_count=0,  # 手动添加与知识点入本都不是"答错"，不计入答错次数
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_item(row, question)


def delete_wrong_question(db: Session, *, user_id: int, wrong_question_id: int) -> None:
    """删除错题条目，并按该题所属领域重算掌握度（系统设计 §5.10）。"""
    row = _get_owned(db, user_id=user_id, wrong_question_id=wrong_question_id)
    question = db.get(Question, row.question_id)
    db.delete(row)
    db.flush()
    if question is not None:
        practice_service.recompute_mastery(db, user_id=user_id, direction=question.direction)
    db.commit()


def review_wrong_question(
    db: Session,
    *,
    user_id: int,
    wrong_question_id: int,
    answer: str,
    client: LLMClient,
) -> WrongQuestionReviewData:
    """复习判定 + 档位推进 + 重算掌握度。已掌握的条目不再受理（30002）。"""
    if not answer.strip():  # 请求模型只拦得住空串，全空白在此拦下（接口文档 §3.9 实现口径 5）
        raise BizException(ErrorCode.PARAM_INVALID, "作答内容不能为空")
    row = _get_owned(db, user_id=user_id, wrong_question_id=wrong_question_id, invalid=True)
    if row.mastered_at is not None:
        raise BizException(ErrorCode.WRONG_QUESTION_INVALID)

    question = db.get(Question, row.question_id)
    if question is None:  # 题目被删而条目残留：同码拒绝，不让外键悬挂暴露出来
        raise BizException(ErrorCode.WRONG_QUESTION_INVALID)
    correct, explain = _judge(db, user_id=user_id, question=question, answer=answer, client=client)

    now = datetime.now()
    if correct:
        row.review_stage += 1
        if row.review_stage > MAX_REVIEW_STAGE:
            row.mastered_at = now  # 四档走完即掌握，此后不再进入复习队列
        else:
            row.next_review_at = now + timedelta(days=REVIEW_STAGE_DAYS[row.review_stage - 1])
    else:
        row.review_stage = 1
        row.wrong_count += 1
        row.next_review_at = now + timedelta(days=REVIEW_STAGE_DAYS[0])
    row.last_review_at = now

    practice_service.recompute_mastery(db, user_id=user_id, direction=question.direction)
    db.commit()
    db.refresh(row)
    return WrongQuestionReviewData(
        correct=correct,
        explain=explain,
        review_stage=row.review_stage,
        next_review_at=row.next_review_at,
        mastered=row.mastered_at is not None,
    )


# ---------- 内部 ----------


def _get_owned(
    db: Session, *, user_id: int, wrong_question_id: int, invalid: bool = False
) -> WrongQuestion:
    """取本账号的错题条目；不存在或跨账号 → 404（复习场景用错题本专用码，其余用通用码）。"""
    row = db.get(WrongQuestion, wrong_question_id)
    if row is None or row.user_id != user_id:
        code = ErrorCode.WRONG_QUESTION_INVALID if invalid else ErrorCode.NOT_FOUND
        raise BizException(code)
    return row


def _find_or_create_question(db: Session, payload: WrongQuestionAddRequest) -> Question:
    """知识点形态：题干已在题库则复用（题库跨账号公共），没有才建 AI_GENERATED 题。"""
    question = (
        db.execute(select(Question).where(Question.content == payload.content)).scalars().first()
    )
    if question is not None:
        return question
    question = Question(
        stack=practice_service.STACK_OF_DIRECTION.get(payload.direction, Stack.COMMON),
        direction=payload.direction,
        content=payload.content,
        answer=payload.answer,
        qtype=QuestionType.SUBJECTIVE,
        source=QuestionSource.AI_GENERATED,
    )
    db.add(question)
    db.flush()
    return question


def _judge(
    db: Session, *, user_id: int, question: Question, answer: str, client: LLMClient
) -> tuple[bool, str]:
    """按题型分派判定：选择题规则比对（零 token），主观题与场景题走 LLM。"""
    if question.qtype == QuestionType.CHOICE:
        options = parse_options(question.options)
        correct = judge_choice(question.answer, answer, options)
        return correct, _choice_explain(question, expand_choice_input(answer, options), correct)
    return _judge_by_llm(db, user_id=user_id, question=question, answer=answer, client=client)


def _choice_explain(question: Question, said: str, correct: bool) -> str:
    """选择题判定解析：对错 + 正确选项 + 解析（不调 LLM，与陪练同口径）。"""
    if correct:
        head = f"选对了，正确答案就是「{question.answer}」。"
    else:
        head = f"这次选的是「{said.strip() or '（未作答）'}」，正确答案是「{question.answer}」。"
    return f"{head}\n\n{question.explanation}" if question.explanation else head


def _judge_by_llm(
    db: Session, *, user_id: int, question: Question, answer: str, client: LLMClient
) -> tuple[bool, str]:
    """主观题 / 场景题：LLM 非流式 JSON 判定；解析不出结果重试 1 次，仍不行报 10011、档位不动。"""
    config = resolve_config(db, user_id)
    messages = build_wrong_question_judge_messages(question, answer)
    for _ in range(JUDGE_RETRY + 1):
        try:
            result = client.chat_json(config, messages)
        except BizException as exc:
            if exc.code != ErrorCode.LLM_OUTPUT_INVALID:  # 未配置 / 鉴权失败等不重试
                raise
            continue
        correct = _coerce_bool(result.get("correct"))
        if correct is not None:
            explain = str(result.get("explain") or "").strip()
            return correct, explain or ("判定为掌握。" if correct else "判定为未掌握。")
    raise BizException(ErrorCode.LLM_OUTPUT_INVALID)


def _coerce_bool(value: object) -> bool | None:
    """判定字段归一化：模型偶尔把布尔写成字符串，认 `true`/`false` 两种写法，其余记无效。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "false"):
            return low == "true"
    return None


def _to_item(row: WrongQuestion, question: Question) -> WrongQuestionItem:
    return WrongQuestionItem(
        id=row.id,
        question_id=row.question_id,
        content=question.content,
        qtype=question.qtype,
        options=parse_options(question.options) or None,  # 仅选择题有值，其余题型下发 null
        direction=question.direction,
        source_type=row.source_type,
        review_stage=row.review_stage,
        next_review_at=row.next_review_at,
        wrong_count=row.wrong_count,
        mastered_at=row.mastered_at,
    )
