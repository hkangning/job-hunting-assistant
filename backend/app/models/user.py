"""账号与 AI 供应商配置模型（数据库设计文档 3.16 / 3.17）。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import UserPlan, UserRole


class User(Base):
    """账号：登录凭据与个人中心信息，全部业务数据的归属根（FR-016、FR-017）。"""

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    username: Mapped[str] = mapped_column(String(50), unique=True)  # 登录名（全站唯一，注册后不可改）
    password_hash: Mapped[str] = mapped_column(String(100))  # bcrypt 哈希（永不存明文、接口不回显）
    nickname: Mapped[str | None] = mapped_column(String(50))  # 昵称（默认取用户名，个人中心可改）
    email: Mapped[str | None] = mapped_column(String(100))  # 邮箱（可选，全站唯一）
    avatar: Mapped[str | None] = mapped_column(String(200))  # 头像相对路径（空=用默认头像）
    role: Mapped[str] = mapped_column(String(20), default=UserRole.USER)  # 角色，枚举 UserRole
    plan: Mapped[str] = mapped_column(String(20), default=UserPlan.FREE)  # 套餐，枚举 UserPlan（预留）
    login_fail_count: Mapped[int] = mapped_column(Integer, default=0)  # 连续登录失败次数（达 5 次锁定）
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)  # 锁定截止时间（晚于当前时间则拒绝登录）
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)  # 最近登录时间（个人中心展示）
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime)  # 改密时间（旧 Token 作废依据）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 注册时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )  # 更新时间


class LlmProviderConfig(Base):
    """AI 供应商配置：每账号 × 每供应商一行，Key 以 Fernet 密文存储（FR-018，步骤 6 使用）。"""

    __tablename__ = "llm_provider_config"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_llm_user_provider"),
        Index("idx_llm_cfg_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="CASCADE")
    )  # 所属账号（删账号级联删配置）
    provider: Mapped[str] = mapped_column(String(30))  # 供应商标识（注册表 12 项之一）
    base_url: Mapped[str | None] = mapped_column(String(200))  # API 端点（空=用注册表默认值）
    api_key: Mapped[str | None] = mapped_column(Text)  # 密钥（Fernet 密文；ollama 本地无需 Key）
    model: Mapped[str | None] = mapped_column(String(100))  # 该供应商下所选模型（空=注册表默认）
    models_cache: Mapped[str | None] = mapped_column(Text)  # 模型列表缓存 JSON（含 fetched_at，24h 过期）
    is_active: Mapped[int] = mapped_column(Integer, default=0)  # 是否当前激活（每账号至多一行 =1）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 创建时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )  # 更新时间
