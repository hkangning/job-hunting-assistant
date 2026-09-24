"""面经主记录与结构化条目模型（数据库设计文档 3.5 / 3.6）。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import ExperienceItemSource


class Experience(Base):
    """面经主记录：保留原文全文，条目由 LLM 提取或手补（FR-008）。"""

    __tablename__ = "experience"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    company: Mapped[str | None] = mapped_column(String(100))  # 公司
    position: Mapped[str | None] = mapped_column(String(100))  # 岗位
    source: Mapped[str | None] = mapped_column(String(100))  # 来源（牛客/公众号/同学分享）
    original_text: Mapped[str] = mapped_column(Text)  # 原文全文
    item_count: Mapped[int] = mapped_column(Integer, default=0)  # 结构化条目数（冗余计数，列表展示用）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 创建时间


class ExperienceItem(Base):
    """面经结构化条目：question 参与 LIKE 检索（FR-008）。"""

    __tablename__ = "experience_item"
    __table_args__ = (Index("idx_exp_item_exp", "experience_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    experience_id: Mapped[int] = mapped_column(ForeignKey("experience.id"))  # 所属面经
    question: Mapped[str] = mapped_column(Text)  # 面试问题
    answer_points: Mapped[str | None] = mapped_column(Text)  # 答案要点（LLM 提取或手补）
    source_type: Mapped[str] = mapped_column(
        String(20), default=ExperienceItemSource.LLM_EXTRACT
    )  # 条目来源，枚举 ExperienceItemSource
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 创建时间
