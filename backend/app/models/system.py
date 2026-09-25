"""系统级模型：提醒、宣讲会、配置与用户画像（数据库设计文档 3.12~3.15）。"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Reminder(Base):
    """提醒记录：同一类型+对象+日期唯一，防同日重复生成（FR-001、FR-013）。"""

    __tablename__ = "reminder"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "reminder_type", "ref_id", "remind_date", name="uq_reminder_user_type_ref_date"
        ),
        Index("idx_reminder_user", "user_id"),
        Index("idx_reminder_date", "remind_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))  # 所属账号（提醒按账号分别生成）
    reminder_type: Mapped[str] = mapped_column(String(20))  # 类型，枚举 ReminderType
    ref_id: Mapped[int | None] = mapped_column(Integer)  # 关联业务 id（跟进/面试=application.id，错题=wrong_question.id）
    content: Mapped[str] = mapped_column(Text)  # 提醒文案（LLM 或模板生成）
    remind_date: Mapped[date] = mapped_column(Date)  # 提醒日期
    checked: Mapped[int] = mapped_column(Integer, default=0)  # 是否已读（0 未读 / 1 已读）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 生成时间


class CampusEvent(Base):
    """宣讲会/招聘会：标题+时间唯一，防重复抓取（FR-001、FR-013）。"""

    __tablename__ = "campus_event"
    __table_args__ = (
        UniqueConstraint("title", "event_date"),
        Index("idx_event_date", "event_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    title: Mapped[str] = mapped_column(String(200))  # 活动标题
    company: Mapped[str | None] = mapped_column(String(100))  # 企业名称
    event_date: Mapped[datetime] = mapped_column(DateTime)  # 活动时间
    location: Mapped[str | None] = mapped_column(String(200))  # 地点
    source_url: Mapped[str | None] = mapped_column(String(500))  # 来源链接
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 抓取时间


class Config(Base):
    """系统配置：key-value；`user_id=0` 为系统级（不建外键），其余为账号级；密钥只存本机库、不回显明文（FR-015）。"""

    __tablename__ = "config"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)  # 所属账号；0=系统级配置
    key: Mapped[str] = mapped_column(String(50), primary_key=True)  # 配置键
    value: Mapped[str | None] = mapped_column(Text)  # 配置值（开关/URL/模型名/Key 覆盖值）
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )  # 更新时间


class UserProfile(Base):
    """用户画像：每账号一条，JD 分析与 Agent 记忆的输入（FR-012）。"""

    __tablename__ = "user_profile"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_profile_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE")
    )  # 所属账号（每账号有且仅有一条画像，随账号级联删除）
    name: Mapped[str | None] = mapped_column(String(50))  # 姓名
    school: Mapped[str | None] = mapped_column(String(100))  # 学校
    major: Mapped[str | None] = mapped_column(String(100))  # 专业
    degree: Mapped[str | None] = mapped_column(String(20))  # 学历（本科/硕士）
    gpa: Mapped[str | None] = mapped_column(String(20))  # GPA 文本
    english_level: Mapped[str | None] = mapped_column(String(50))  # 英语水平（如 CET-6 441）
    resume_text: Mapped[str | None] = mapped_column(Text)  # 简历全文（JD 分析核心输入）
    target_position: Mapped[str | None] = mapped_column(String(100))  # 目标岗位
    target_city: Mapped[str | None] = mapped_column(String(50))  # 目标城市
    skills: Mapped[str | None] = mapped_column(Text)  # 技能栈标签（逗号分隔）
    weaknesses: Mapped[str | None] = mapped_column(Text)  # 弱项标签（逗号分隔）
    note: Mapped[str | None] = mapped_column(Text)  # 备注
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )  # 更新时间
