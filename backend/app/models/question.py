"""题库、陪练记录与错题本模型（数据库设计文档 3.7 / 3.8 / 3.9）。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import QuestionSource, QuestionType, WrongSourceType


class Question(Base):
    """八股题库：被陪练与错题本复用（FR-009、FR-010）。"""

    __tablename__ = "question"
    __table_args__ = (Index("idx_question_direction", "direction"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    direction: Mapped[str] = mapped_column(String(20))  # 题目方向，枚举 Direction
    content: Mapped[str] = mapped_column(Text)  # 题干（种子导入按此去重）
    answer: Mapped[str] = mapped_column(Text)  # 标准答案（点评/判定依据）
    qtype: Mapped[str] = mapped_column(
        String(20), default=QuestionType.SUBJECTIVE
    )  # 题型，枚举 QuestionType（CHOICE 走规则判定）
    source: Mapped[str] = mapped_column(
        String(20), default=QuestionSource.BUILTIN
    )  # 题目来源，枚举 QuestionSource
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 创建时间


class PracticeRecord(Base):
    """陪练记录：一次作答一行，含 AI 评分与点评（FR-009）。"""

    __tablename__ = "practice_record"
    __table_args__ = (
        Index("idx_practice_user", "user_id"),
        Index("idx_practice_q", "question_id"),
        Index("idx_practice_time", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))  # 所属账号（账号私有数据）
    question_id: Mapped[int] = mapped_column(ForeignKey("question.id"))  # 题目
    user_answer: Mapped[str] = mapped_column(Text)  # 用户作答
    score: Mapped[int | None] = mapped_column(Integer)  # AI 评分 0~10
    review: Mapped[str | None] = mapped_column(Text)  # AI 点评全文
    is_correct: Mapped[int | None] = mapped_column(Integer)  # 判定对错（NULL=未判定；客观题规则判定）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 作答时间


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
