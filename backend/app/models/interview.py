"""模拟面试会话与问答条目模型（数据库设计文档 3.3 / 3.4）。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import Direction, SessionStatus


class InterviewSession(Base):
    """模拟面试会话：可由投递记录发起，也可手填公司岗位（FR-007）。"""

    __tablename__ = "interview_session"
    __table_args__ = (Index("idx_session_status", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    application_id: Mapped[int | None] = mapped_column(ForeignKey("application.id"))  # 关联投递（手填发起则空）
    company: Mapped[str] = mapped_column(String(100))  # 公司（从投递带入或手填）
    position: Mapped[str] = mapped_column(String(100))  # 岗位
    direction: Mapped[str] = mapped_column(
        String(20), default=Direction.GENERAL
    )  # 面试方向，枚举 Direction
    question_count: Mapped[int] = mapped_column(Integer, default=8)  # 计划题量（3~15）
    status: Mapped[str] = mapped_column(
        String(20), default=SessionStatus.ACTIVE
    )  # 会话状态，枚举 SessionStatus
    summary: Mapped[str | None] = mapped_column(Text)  # 总结报告全文（结束后生成）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 创建时间
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)  # 结束时间


class InterviewQa(Base):
    """面试问答条目：一题一行，跳过与语音作答均在此留痕（FR-007、FR-014）。"""

    __tablename__ = "interview_qa"
    __table_args__ = (Index("idx_qa_session", "session_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_session.id"))  # 所属会话
    seq: Mapped[int] = mapped_column(Integer)  # 题序（从 1 开始）
    question: Mapped[str] = mapped_column(Text)  # AI 提问原文
    answer: Mapped[str | None] = mapped_column(Text)  # 用户作答（跳题为空）
    is_voice: Mapped[int] = mapped_column(Integer, default=0)  # 是否语音作答（0 文字 / 1 语音，P2）
    score: Mapped[int | None] = mapped_column(Integer)  # 得分 0~10（跳题为空）
    review: Mapped[str | None] = mapped_column(Text)  # AI 点评（亮点/不足/参考要点）
    skipped: Mapped[int] = mapped_column(Integer, default=0)  # 是否跳过（0 否 / 1 是）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 提问时间
