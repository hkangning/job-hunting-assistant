"""练习模式题目与练习记录模型（数据库设计文档 3.18 / 3.19）。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import DrillSource


class DrillTopic(Base):
    """练习题目：从错题 / 面经 / 投递 JD 导入或手动新建，归档而非删除（FR-020）。"""

    __tablename__ = "drill_topic"
    __table_args__ = (
        Index("idx_topic_user", "user_id"),
        Index("idx_topic_archived", "archived"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))  # 所属账号（账号私有数据）
    title: Mapped[str] = mapped_column(String(100))  # 标题（接口约束 ≤50 字）
    question: Mapped[str] = mapped_column(Text)  # 完整题面（AI 出题与点评的输入）
    source: Mapped[str] = mapped_column(String(20), default=DrillSource.CUSTOM)  # 来源，枚举 DrillSource
    ref_id: Mapped[int | None] = mapped_column(Integer)  # 来源实体 id（只记来源不复制内容，手建为空）
    archived: Mapped[int] = mapped_column(Integer, default=0)  # 是否归档（0 未归档 / 1 已归档；练习记录是长期资产）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 创建时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )  # 更新时间


class DrillAttempt(Base):
    """练习记录：每练一遍一行，逐次留存可回看（FR-020）；子表不冗余 user_id，经 topic 归属。"""

    __tablename__ = "drill_attempt"
    __table_args__ = (Index("idx_attempt_topic", "topic_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    topic_id: Mapped[int] = mapped_column(ForeignKey("drill_topic.id"))  # 所属题目
    seq: Mapped[int] = mapped_column(Integer)  # 第几遍（max+1，不建唯一约束）
    answer: Mapped[str | None] = mapped_column(Text)  # 作答内容
    is_voice: Mapped[int] = mapped_column(Integer, default=0)  # 是否语音作答（0 文字 / 1 语音）
    voice_metrics: Mapped[str | None] = mapped_column(
        Text
    )  # 表达力指标快照 JSON（语音作答且 quality=OK 时落库；其余为空，数据库设计 §3.19）
    score: Mapped[int | None] = mapped_column(Integer)  # 得分 0~10
    review: Mapped[str | None] = mapped_column(Text)  # AI 点评全文
    duration_ms: Mapped[int | None] = mapped_column(Integer)  # 作答时长（毫秒，前端计时上报）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 练习时间
