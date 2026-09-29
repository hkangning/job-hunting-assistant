"""题库、陪练记录与错题本模型（数据库设计文档 3.7 / 3.8 / 3.9 / 3.23 / 3.24）。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import (
    AttackFace,
    PracticeMode,
    PracticeSessionStatus,
    QuestionSource,
    QuestionType,
    RoundKind,
    Stack,
    WrongSourceType,
)


class Question(Base):
    """八股题库：被陪练与错题本复用（FR-009、FR-010）。"""

    __tablename__ = "question"
    __table_args__ = (
        Index("idx_question_direction", "direction"),
        Index("idx_question_stack", "stack"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    stack: Mapped[str] = mapped_column(
        String(20), default=Stack.COMMON
    )  # 技术栈，枚举 Stack（决定服务哪些岗位）
    direction: Mapped[str] = mapped_column(String(20))  # 知识领域，枚举 Direction
    content: Mapped[str] = mapped_column(Text)  # 题干（种子导入按此去重）
    answer: Mapped[str] = mapped_column(Text)  # 标准答案（点评/判定依据；场景题为分层框架）
    rubric: Mapped[str | None] = mapped_column(Text)  # 四维度评分标尺（JSON 字符串，仅场景题有值）
    qtype: Mapped[str] = mapped_column(
        String(20), default=QuestionType.SUBJECTIVE
    )  # 题型，枚举 QuestionType（CHOICE 走规则判定）
    options: Mapped[str | None] = mapped_column(
        Text
    )  # 选择题选项数组（JSON 字符串，不含正确标记，可安全下发；仅 CHOICE 有值）
    explanation: Mapped[str | None] = mapped_column(Text)  # 选择题解析（答完展示；仅 CHOICE 有值）
    source: Mapped[str] = mapped_column(
        String(20), default=QuestionSource.BUILTIN
    )  # 题目来源，枚举 QuestionSource
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 创建时间


class PracticeSession(Base):
    """训练会话：一场训练的容器，包含若干轮 practice_record（FR-009）。"""

    __tablename__ = "practice_session"
    __table_args__ = (
        Index("idx_ps_user", "user_id"),
        Index("idx_ps_question", "question_id"),
        Index("idx_ps_time", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))  # 所属账号（账号私有数据）
    question_id: Mapped[int] = mapped_column(ForeignKey("question.id"))  # 题目
    mode: Mapped[str] = mapped_column(String(20))  # 训练模式，枚举 PracticeMode
    status: Mapped[str] = mapped_column(
        String(20), default=PracticeSessionStatus.RUNNING
    )  # 会话状态，枚举 PracticeSessionStatus
    time_limit: Mapped[int | None] = mapped_column(Integer)  # 每轮限时秒数（NULL=不限时）
    overall_score: Mapped[int | None] = mapped_column(Integer)  # 整场综合分 0~10
    break_face: Mapped[str | None] = mapped_column(
        String(20)
    )  # 首个断点所在层级与攻击面，枚举 AttackFace（层级由它唯一确定）
    hint_count: Mapped[int] = mapped_column(Integer, default=0)  # 求提示次数
    passed: Mapped[int | None] = mapped_column(Integer)  # 是否通过（NULL=未结算）
    wrong_question_id: Mapped[int | None] = mapped_column(
        ForeignKey("wrong_question.id", ondelete="SET NULL")
    )  # 入错题本产生的条目（NULL=未入本；错题被删时置空、保留训练历史）
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 开始时间
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)  # 结算时间


class PracticeRecord(Base):
    """陪练记录：一轮作答一行，含 AI 评分与点评（FR-009）。"""

    __tablename__ = "practice_record"
    __table_args__ = (
        Index("idx_practice_user", "user_id"),
        Index("idx_practice_q", "question_id"),
        Index("idx_practice_time", "created_at"),
        Index("idx_practice_session", "session_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))  # 所属账号（账号私有数据）
    question_id: Mapped[int] = mapped_column(ForeignKey("question.id"))  # 题目
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("practice_session.id", name="fk_practice_record_session")
    )  # 所属训练会话（历史单轮记录为 NULL）
    round_index: Mapped[int] = mapped_column(Integer, default=1)  # 第几轮（1 = 初始作答）
    round_kind: Mapped[str] = mapped_column(
        String(20), default=RoundKind.OPENING
    )  # 轮次类型，枚举 RoundKind
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)  # 本轮耗时毫秒（限时模式用）
    user_answer: Mapped[str | None] = mapped_column(Text)  # 用户作答（提示轮没有作答，可空）
    score: Mapped[int | None] = mapped_column(Integer)  # AI 评分 0~10
    review: Mapped[str | None] = mapped_column(Text)  # AI 点评全文
    is_correct: Mapped[int | None] = mapped_column(Integer)  # 判定对错（NULL=未判定；客观题规则判定）
    next_choices: Mapped[str | None] = mapped_column(
        Text
    )  # 本轮追问下发的选项 JSON（含 answer/explain，服务端判定用；下发时剥离正确项）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 作答时间


class DomainMastery(Base):
    """领域掌握度账本：每账号 × 每领域一行，驱动薄弱优先选题（FR-009）。"""

    __tablename__ = "domain_mastery"
    __table_args__ = (
        UniqueConstraint("user_id", "stack", "direction", name="uq_dm_user_stack_direction"),
        Index("idx_dm_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))  # 所属账号（账号私有数据）
    stack: Mapped[str] = mapped_column(String(20))  # 技术栈，枚举 Stack
    direction: Mapped[str] = mapped_column(String(20))  # 领域，枚举 Direction
    mastery: Mapped[int] = mapped_column(Integer, default=0)  # 掌握度 0~100
    answered_count: Mapped[int] = mapped_column(Integer, default=0)  # 累计作答轮次
    covered_count: Mapped[int] = mapped_column(Integer, default=0)  # 练过的不同题目数
    last_practiced_at: Mapped[datetime | None] = mapped_column(DateTime)  # 最近练习时间（衰减依据）


class WrongQuestion(Base):
    """错题本：同账号内一题至多一条，复习档位 1~4 间隔 1/3/7/15 天（FR-010、FR-013）。"""

    __tablename__ = "wrong_question"
    __table_args__ = (
        UniqueConstraint("user_id", "question_id", name="uq_wq_user_question"),
        Index("idx_wq_user", "user_id"),
        Index("idx_wq_review", "next_review_at"),
        Index("idx_wq_stage", "review_stage"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))  # 所属账号（账号私有数据）
    question_id: Mapped[int] = mapped_column(ForeignKey("question.id"))  # 题目（同账号内唯一）
    source_type: Mapped[str] = mapped_column(String(20))  # 入本来源，枚举 WrongSourceType
    review_stage: Mapped[int] = mapped_column(Integer, default=1)  # 复习档位 1~4
    next_review_at: Mapped[datetime] = mapped_column(DateTime)  # 下次复习时间（到期判定依据）
    wrong_count: Mapped[int] = mapped_column(Integer, default=0)  # 累计答错次数
    last_review_at: Mapped[datetime | None] = mapped_column(DateTime)  # 最近一次复习时间
    mastered_at: Mapped[datetime | None] = mapped_column(DateTime)  # 掌握时间（非空=已掌握）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 入本时间
