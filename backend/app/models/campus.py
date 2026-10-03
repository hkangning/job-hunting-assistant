"""校招情报模型：抓取源配置、岗位与订阅规则（数据库设计文档 3.20~3.22）。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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


class JobPosting(Base):
    """岗位：混合归属表——`user_id=0` 自动抓取（公共）/ 账号 id 投喂（私有），查询限 `IN (0, 当前账号)`（FR-021、数据库设计 3.21）。"""

    __tablename__ = "job_posting"
    __table_args__ = (
        UniqueConstraint("user_id", "dedup_key", name="uq_job_posting_user_dedup"),
        Index("idx_job_user", "user_id"),
        Index("idx_job_status", "status", "deadline"),
        Index("idx_job_city", "city"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    user_id: Mapped[int] = mapped_column(Integer, default=0)  # 归属：0=自动抓取（公共）/ 账号 id=投喂（私有）；无外键（0 非有效账号）
    title: Mapped[str] = mapped_column(String(200))  # 岗位名称
    company: Mapped[str] = mapped_column(String(100))  # 公司名称
    city: Mapped[str | None] = mapped_column(String(50))  # 工作城市（匹配打分用）
    edu_req: Mapped[str | None] = mapped_column(String(50))  # 学历要求（原文）
    major_req: Mapped[str | None] = mapped_column(String(300))  # 专业要求（原文，匹配打分用）
    salary_text: Mapped[str | None] = mapped_column(String(100))  # 薪资原文，不做结构化解析
    job_type: Mapped[str | None] = mapped_column(String(20))  # 岗位类型，枚举 JobType
    deadline: Mapped[datetime | None] = mapped_column(DateTime)  # 投递截止时间（过期归档判定依据之一）
    source_site: Mapped[str | None] = mapped_column(String(50))  # 来源站点标识（主机名；投喂为空）
    source_url: Mapped[str | None] = mapped_column(String(500))  # 原文链接
    ingest_source: Mapped[str] = mapped_column(String(20), default="AUTO")  # 入库通道，枚举 IngestSource
    raw_excerpt: Mapped[str | None] = mapped_column(Text)  # 原文摘录（仅投喂通道有值；自动抓取不存正文 NFR-016）
    dedup_key: Mapped[str] = mapped_column(String(64))  # 去重指纹（同归属内去重）
    content_hash: Mapped[str | None] = mapped_column(String(64))  # 内容指纹（审计字段）
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # 状态，枚举 InfoStatus
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 首次入库时间（不另设 created_at）
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 最近一次仍抓到的更新时间
    changed_at: Mapped[datetime | None] = mapped_column(DateTime)  # 最近一次内容变更时间


class Subscription(Base):
    """订阅规则：账号私有，命中公共信息后写 INFO_MATCH 提醒（FR-022、数据库设计 3.22）。"""

    __tablename__ = "subscription"
    __table_args__ = (Index("idx_subscription_user", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))  # 所属账号（账号私有）
    name: Mapped[str] = mapped_column(String(50))  # 规则名称
    keywords: Mapped[str | None] = mapped_column(Text)  # 关键词 JSON 数组（命中标题 / 公司名）
    companies: Mapped[str | None] = mapped_column(Text)  # 公司名 JSON 数组
    cities: Mapped[str | None] = mapped_column(Text)  # 城市 JSON 数组
    info_types: Mapped[str | None] = mapped_column(Text)  # 信息类型 JSON 数组（TALK / FAIR / JOB），空 = 不限
    enabled: Mapped[int] = mapped_column(Integer, default=1)  # 启用开关（0 停用 / 1 启用）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 创建时间
