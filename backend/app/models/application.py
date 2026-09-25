"""投递记录与 JD 分析报告模型（数据库设计文档 3.1 / 3.2）。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import ApplicationStatus


class Application(Base):
    """投递记录：中心实体，JD 分析/模拟面试/跟进提醒均围绕它（FR-002~005、FR-013）。"""

    __tablename__ = "application"
    __table_args__ = (
        Index("idx_application_user", "user_id"),
        Index("idx_application_status", "status"),
        Index("idx_application_applied_at", "applied_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))  # 所属账号（账号私有数据）
    company: Mapped[str] = mapped_column(String(100))  # 公司名称
    position: Mapped[str] = mapped_column(String(100))  # 岗位名称
    city: Mapped[str | None] = mapped_column(String(50))  # 工作城市
    expected_salary: Mapped[str | None] = mapped_column(String(50))  # 期望/沟通薪资（自由文本）
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 投递日期（跟进提醒判定依据）
    channel: Mapped[str | None] = mapped_column(String(50))  # 投递渠道（官网/BOSS/内推等）
    status: Mapped[str] = mapped_column(
        String(20), default=ApplicationStatus.APPLIED
    )  # 进度状态，枚举 ApplicationStatus
    close_reason: Mapped[str | None] = mapped_column(String(20))  # 结束原因，仅 status=CLOSED 时有值（枚举 CloseReason）
    next_event_at: Mapped[datetime | None] = mapped_column(DateTime)  # 下次笔试/面试时间（概览置顶依据）
    remark: Mapped[str | None] = mapped_column(Text)  # 备注
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 创建时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )  # 更新时间（应用层维护）


class JdAnalysisReport(Base):
    """JD 匹配分析报告：一条投递可多次分析（FR-006）。"""

    __tablename__ = "jd_analysis_report"
    __table_args__ = (
        Index("idx_jd_user", "user_id"),
        Index("idx_jd_app_id", "application_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))  # 所属账号（账号私有数据）
    application_id: Mapped[int | None] = mapped_column(ForeignKey("application.id"))  # 关联投递（未选则空）
    jd_text: Mapped[str] = mapped_column(Text)  # JD 原文快照
    report_text: Mapped[str] = mapped_column(Text)  # 报告全文（五段结构）
    score: Mapped[int | None] = mapped_column(Integer)  # 综合匹配度 0~100（LLM 可解析时提取）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 生成时间
