"""校招情报模型：抓取源配置（数据库设计文档 3.20）。

本文件自步骤 21（多源采集层）启用；`job_posting`（3.21）与 `subscription`（3.22）属步骤 22，届时一并落此文件。
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CrawlSource(Base):
    """抓取源配置：一行 = 一所学校的一个就业网站系统，公共表全站共享（FR-021、数据库设计 3.20）。"""

    __tablename__ = "crawl_source"
    __table_args__ = (
        UniqueConstraint("system_type", "domain", name="uq_crawl_source_type_domain"),
        Index("idx_crawl_source_enabled", "enabled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    school_name: Mapped[str] = mapped_column(String(100))  # 学校名称（下发信息时映射为来源站点名）
    system_type: Mapped[str] = mapped_column(String(20))  # 就业网站系统类型，枚举 CrawlSystemType
    domain: Mapped[str] = mapped_column(String(200))  # 站点域名（抓取前缀，同时是同域限频分组键）
    params: Mapped[str | None] = mapped_column(Text)  # 系统参数 JSON（xxdm / panel_id 等，按系统类型取值）
    enabled: Mapped[int] = mapped_column(Integer, default=1)  # 启用开关（0 停用 / 1 启用）
    last_crawl_at: Mapped[datetime | None] = mapped_column(DateTime)  # 上次抓取时间
    last_status: Mapped[str | None] = mapped_column(String(20))  # 上次抓取结果，枚举 CrawlStatus
    last_error: Mapped[str | None] = mapped_column(String(300))  # 失败原因摘要（供源管理展示）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 创建时间
