"""八股陪练：元数据 / 抽题调度 / 领域掌握度（接口文档 3.8；算法口径见系统设计 §5.10）。"""

import random
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DomainMastery, PracticeRecord, Question, WrongQuestion
from app.schemas.practice import (
    DomainOption,
    FaceOption,
    MasteryData,
    MasteryDomainItem,
    MasteryGroup,
    ModeOption,
    PositionOption,
    PracticeMetaDTO,
    QtypeOption,
    QuestionItem,
    StackOption,
)
from app.utils.mastery import compute_mastery

# 技术栈中文名与下辖领域（顺序即前端筛选面板的展示顺序）
STACKS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "JAVA_BACKEND",
        "Java 后端",
        (("JAVA", "Java 基础"), ("JVM", "JVM"), ("CONCURRENCY", "并发编程"), ("SPRING", "Spring")),
    ),
    (
        "BACKEND_COMMON",
        "后端通用",
        (("MYSQL", "MySQL"), ("REDIS", "Redis"), ("MQ", "消息队列")),
    ),
    (
        "COMMON",
        "计算机通用基础",
        (("NETWORK", "计算机网络"), ("OS", "操作系统"), ("ALGO", "数据结构与算法"), ("DESIGN", "设计模式与架构")),
    ),
    (
        "PYTHON",
        "Python",
        (("PY_BASIC", "Python 基础"), ("PY_ASYNC", "并发与异步"), ("PY_WEB", "Web 框架")),
    ),
    (
        "AI_AGENT",
        "AI 与大模型应用",
        (("LLM_BASIC", "大模型基础"), ("PROMPT", "提示词工程"), ("RAG", "检索增强生成"), ("AGENT", "Agent 与工具调用")),
    ),
)

# 岗位视角 = 若干技术栈的并集（后端不感知「岗位」概念，前端展开成 stacks 后传给抽题接口）
POSITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("JAVA", "Java 岗位", ("JAVA_BACKEND", "BACKEND_COMMON", "COMMON")),
    ("PYTHON", "Python 岗位", ("PYTHON", "BACKEND_COMMON", "COMMON")),
    ("AI_AGENT", "AI 大模型岗位", ("AI_AGENT", "PYTHON", "BACKEND_COMMON", "COMMON")),
)

QTYPE_LABELS: dict[str, str] = {
    "SUBJECTIVE": "问答型",
    "CHOICE": "选择题",
    "SCENARIO": "场景题",
}

# 五种训练模式：中文名 / 一句话玩法 / 作答轮数上限（与 SRS FR-009 的轮次口径一致）
MODES: tuple[tuple[str, str, str, int], ...] = (
    ("QUICK", "快练", "一题一答一评，没有追问", 1),
    ("INTERVIEWER", "面试官深挖", "追到你答不上来，看你的知识边界在哪", 5),
    ("COACH", "教练引导", "答不上时先给提示，带到你能自己说出来", 5),
    ("DEBUG", "挑错纠错", "给你一段听着顺但有雷的答案，你来挑错", 2),
    ("FEYNMAN", "费曼复述", "不看答案用自己的话讲一遍，AI 挑漏洞", 3),
)

# 四层追问链：层号与攻击面一一对应（hint 与 prompts.ATTACK_FACE_HINTS 同源口径）
FACES: tuple[tuple[str, str, int, str], ...] = (
    ("BASIS", "依据", 1, "为什么这么做、原理是什么"),
    ("BOUNDARY", "边界", 2, "什么情况下会失效、挂了怎么办"),
    ("TRADEOFF", "取舍", 3, "为什么不用另一种方案、代价分别是什么"),
    ("LANDING", "落地", 4, "具体到你的项目怎么配、量级多少、怎么验证"),
)

TIME_LIMITS: tuple[int, ...] = (30, 60, 90, 120)  # 每轮限时档位（秒），不传即不限时

STACK_OF_DIRECTION: dict[str, str] = {d: stack for stack, _, domains in STACKS for d, _ in domains}


def get_meta(db: Session) -> PracticeMetaDTO:
    """模式清单（含人话描述）、限时档位、技术栈与下辖领域、岗位视角、题型。"""
    return PracticeMetaDTO(
        stacks=[
            StackOption(
                value=stack,
                label=label,
                domains=[DomainOption(value=d, label=dl) for d, dl in domains],
            )
            for stack, label, domains in STACKS
        ],
        positions=[
            PositionOption(value=value, label=label, stacks=list(stacks))
            for value, label, stacks in POSITIONS
        ],
        qtypes=[
            QtypeOption(value=value, label=label)
            for value, label in QTYPE_LABELS.items()
        ],
        modes=[
            ModeOption(value=value, label=label, description=description, max_rounds=max_rounds)
            for value, label, description, max_rounds in MODES
        ],
        faces=[
            FaceOption(value=value, label=label, layer=layer, hint=hint)
            for value, label, layer, hint in FACES
        ],
        time_limits=list(TIME_LIMITS),
    )


def _weight(*, mastery: int, practiced: bool) -> float:
    """选题权重 = 薄弱系数 × 练习历史系数（纯逻辑，可单测）。

    薄弱系数 `(100 - 掌握度) / 50`：掌握度越低越容易被抽到；
    练习历史系数「练过的题 0.3 / 未练过的题 1.0」：练过的题权重下调但不清零、未练过的题有保底。
    """
    return (100 - mastery) / 50 * (0.3 if practiced else 1.0)


def _weighted_sample(pool: list[Question], weights: list[float], count: int) -> list[Question]:
    """按权重不放回抽样（避免同一轮抽到重复题）。"""
    items = list(zip(pool, weights, strict=True))
    picked: list[Question] = []
    for _ in range(min(count, len(items))):
        total = sum(weight for _, weight in items)
        if total <= 0:
            picked.append(items.pop()[0])
            continue
        point = random.uniform(0, total)
        acc = 0.0
        for index, (question, weight) in enumerate(items):
            acc += weight
            if acc >= point:
                picked.append(question)
                items.pop(index)
                break
        else:
            picked.append(items.pop()[0])
    return picked


def pick_questions(
    db: Session,
    *,
    user_id: int,
    stacks: list[str] | None = None,
    directions: list[str] | None = None,
    qtypes: list[str] | None = None,
    count: int = 1,
    strategy: str = "SMART",
) -> list[QuestionItem]:
    """抽题。`SMART` 按 (100 - 掌握度) 加权随机；`RANDOM` 纯随机。

    三个筛选条件为与关系；命中不足 count 时按实际数量返回（不报错）。
    """
    stmt = select(Question)
    if stacks:
        stmt = stmt.where(Question.stack.in_(stacks))
    if directions:
        stmt = stmt.where(Question.direction.in_(directions))
    if qtypes:
        stmt = stmt.where(Question.qtype.in_(qtypes))
    pool = list(db.execute(stmt).scalars())
    if not pool:
        return []

    mastery_map = _mastery_map(db, user_id=user_id)
    if strategy == "RANDOM":
        picked = random.sample(pool, min(count, len(pool)))
    else:
        practiced = set(
            db.execute(
                select(PracticeRecord.question_id).where(PracticeRecord.user_id == user_id).distinct()
            ).scalars()
        )
        weights = [
            _weight(mastery=mastery_map.get(q.direction, 0), practiced=q.id in practiced) for q in pool
        ]
        picked = _weighted_sample(pool, weights, count)

    return [
        QuestionItem(
            id=q.id,
            stack=q.stack,
            direction=q.direction,
            content=q.content,
            qtype=q.qtype,
            mastery=mastery_map.get(q.direction, 0),
        )
        for q in picked
    ]


def _mastery_map(db: Session, *, user_id: int) -> dict[str, int]:
    """账号在各领域的掌握度（只含有账本行的领域）。"""
    rows = db.execute(select(DomainMastery).where(DomainMastery.user_id == user_id)).scalars()
    return {row.direction: row.mastery for row in rows}


def mastery_of(db: Session, *, user_id: int, direction: str) -> int:
    """单个领域的当前掌握度（无记录为 0）。"""
    value = db.execute(
        select(DomainMastery.mastery).where(
            DomainMastery.user_id == user_id, DomainMastery.direction == direction
        )
    ).scalar_one_or_none()
    return value or 0


def list_mastery(db: Session, *, user_id: int, stack: str | None = None) -> MasteryData:
    """读 domain_mastery，按技术栈分组；只返回有练习记录的领域行。"""
    stmt = select(DomainMastery).where(DomainMastery.user_id == user_id)
    if stack:
        stmt = stmt.where(DomainMastery.stack == stack)
    rows = list(db.execute(stmt).scalars())
    by_stack: dict[str, list[DomainMastery]] = {}
    for row in rows:
        by_stack.setdefault(row.stack, []).append(row)

    groups: list[MasteryGroup] = []
    for stack_value, stack_label, domains in STACKS:  # 按固定顺序输出，不按字典序
        if stack_value not in by_stack:
            continue
        items = by_stack[stack_value]
        index = {d: label for d, label in domains}
        groups.append(
            MasteryGroup(
                stack=stack_value,
                label=stack_label,
                average=round(sum(row.mastery for row in items) / len(items)),
                domains=[
                    MasteryDomainItem(
                        direction=row.direction,
                        label=index.get(row.direction, row.direction),
                        mastery=row.mastery,
                        answered_count=row.answered_count,
                        covered_count=row.covered_count,
                        last_practiced_at=row.last_practiced_at,
                    )
                    for row in sorted(items, key=lambda r: [d for d, _ in domains].index(r.direction))
                ],
            )
        )
    return MasteryData(groups=groups)


def recompute_mastery(db: Session, *, user_id: int, direction: str) -> tuple[int, int]:
    """重算单个领域掌握度并 upsert（训练结算 / 错题复习判定 / 错题删除后调用）。

    返回 `(before, after)`，供结算响应的 `mastery_delta` 直接使用。
    """
    stack = STACK_OF_DIRECTION.get(direction, "")
    row = db.execute(
        select(DomainMastery).where(
            DomainMastery.user_id == user_id,
            DomainMastery.stack == stack,
            DomainMastery.direction == direction,
        )
    ).scalar_one_or_none()
    before = row.mastery if row else 0

    now = datetime.now()
    scores = list(
        db.execute(
            select(PracticeRecord.score)
            .join(Question, Question.id == PracticeRecord.question_id)
            .where(
                PracticeRecord.user_id == user_id,
                Question.direction == direction,
                PracticeRecord.score.is_not(None),
            )
            .order_by(PracticeRecord.created_at, PracticeRecord.id)
        ).scalars()
    )
    answered_count = len(scores)
    covered_count = (
        db.execute(
            select(func.count(func.distinct(PracticeRecord.question_id)))
            .join(Question, Question.id == PracticeRecord.question_id)
            .where(PracticeRecord.user_id == user_id, Question.direction == direction)
        ).scalar()
        or 0
    )
    domain_total = (
        db.execute(
            select(func.count()).select_from(Question).where(Question.direction == direction)
        ).scalar()
        or 0
    )
    last_practiced_at = db.execute(
        select(func.max(PracticeRecord.created_at))
        .join(Question, Question.id == PracticeRecord.question_id)
        .where(PracticeRecord.user_id == user_id, Question.direction == direction)
    ).scalar()
    ever_wrong_count = (
        db.execute(
            select(func.count())
            .select_from(WrongQuestion)
            .join(Question, Question.id == WrongQuestion.question_id)
            .where(WrongQuestion.user_id == user_id, Question.direction == direction)
        ).scalar()
        or 0
    )
    mastered_count = (
        db.execute(
            select(func.count())
            .select_from(WrongQuestion)
            .join(Question, Question.id == WrongQuestion.question_id)
            .where(
                WrongQuestion.user_id == user_id,
                Question.direction == direction,
                WrongQuestion.mastered_at.is_not(None),
            )
        ).scalar()
        or 0
    )

    after = compute_mastery(
        scores=scores,
        covered_count=covered_count,
        domain_total=domain_total,
        mastered_count=mastered_count,
        ever_wrong_count=ever_wrong_count,
        last_practiced_at=last_practiced_at,
        now=now,
    )

    if row is None:
        row = DomainMastery(user_id=user_id, stack=stack, direction=direction)
        db.add(row)
    row.mastery = after
    row.answered_count = answered_count
    row.covered_count = covered_count
    row.last_practiced_at = last_practiced_at
    db.flush()
    return before, after


