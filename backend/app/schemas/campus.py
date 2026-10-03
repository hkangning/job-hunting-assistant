"""校招情报传输模型：信息源配置与宣讲会/双选会（接口文档 3.16）。"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import CrawlSystemType


# ---------- 信息源（/crawl-sources） ----------


class CrawlSourceDTO(BaseModel):
    """源清单条目（列表 / 新增 / 修改共用）。"""

    id: int = Field(description="源 id")
    school_name: str = Field(description="学校名称（下发信息时映射为来源站点名）")
    system_type: str = Field(description="就业网站系统类型：91JOB / BYSJY（云就业）/ JYSD（才立方）")
    domain: str = Field(description="站点域名（抓取前缀，含 http:// 或 https://）")
    params: dict | None = Field(default=None, description="系统参数 JSON 对象（按 system_type 取值），未配置为 null")
    enabled: bool = Field(description="启用开关")
    last_crawl_at: datetime | None = Field(description="上次抓取时间，从未抓取为 null")
    last_status: str | None = Field(description="上次抓取结果：OK / FAILED / BLOCKED，从未抓取为 null")
    last_error: str | None = Field(description="失败原因摘要，最近一次成功则为 null")


class CrawlSourceCreateRequest(BaseModel):
    """新增源的请求体（POST /crawl-sources）。"""

    school_name: str = Field(min_length=1, max_length=100, description="学校名称")
    system_type: CrawlSystemType = Field(description="就业网站系统类型：91JOB / BYSJY / JYSD")
    domain: str = Field(min_length=1, max_length=200, description="站点域名，仅 http/https")
    params: dict | None = Field(default=None, description="系统参数 JSON 对象，按 system_type 取值")

    @field_validator("domain")
    @classmethod
    def _check_domain(cls, value: str) -> str:
        """域名规范化与协议校验：去尾斜杠，必须以 http:// 或 https:// 开头。"""
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("域名须以 http:// 或 https:// 开头")
        return value


class CrawlSourceUpdateRequest(BaseModel):
    """部分更新源的请求体（PUT /crawl-sources/{id}）：未传字段保持原值。"""

    school_name: str | None = Field(default=None, min_length=1, max_length=100, description="学校名称")
    system_type: CrawlSystemType | None = Field(
        default=None, description="系统类型；不支持修改，传入且与原值不一致 → 10001"
    )
    domain: str | None = Field(default=None, min_length=1, max_length=200, description="站点域名，仅 http/https")
    params: dict | None = Field(default=None, description="系统参数 JSON 对象；传 null 表示清空")
    enabled: bool | None = Field(default=None, description="启用开关")

    @field_validator("domain")
    @classmethod
    def _check_domain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("域名须以 http:// 或 https:// 开头")
        return value


# ---------- 手动采集（POST /crawl-sources/run） ----------


class CrawlRunRequest(BaseModel):
    """手动触发采集的请求体。"""

    source_id: int | None = Field(default=None, description="指定单个源；不传 = 执行全部启用中的源")


class CrawlRunCounts(BaseModel):
    """单源采集的条目计数。"""

    new: int = Field(default=0, description="新入库条数")
    updated: int = Field(default=0, description="重复出现、仅刷新最近可见时间的条数")
    changed: int = Field(default=0, description="内容发生变更（改期等）并覆盖的条数")


class CrawlRunDetail(BaseModel):
    """逐源采集结果。"""

    source_id: int = Field(description="源 id")
    school_name: str = Field(description="学校名称")
    status: str = Field(description="本次结果：OK / FAILED / BLOCKED（robots 禁止或 403）")
    error: str | None = Field(description="失败原因摘要，成功为 null")
    counts: CrawlRunCounts = Field(description="条目计数，失败源全为 0")


class CrawlRunData(BaseModel):
    """手动采集的整体结果（单源失败不整体报错，逐源结果见 details）。"""

    total: int = Field(description="本次实际执行的源数")
    ok: int = Field(description="成功源数")
    failed: int = Field(description="失败源数")
    blocked: int = Field(description="被拒源数（robots 禁止 / 403）")
    items_new: int = Field(description="新入库条数合计")
    items_updated: int = Field(description="重复出现的条数合计")
    items_changed: int = Field(description="内容变更的条数合计")
    expired: int = Field(description="本次归档（标记过期）的条数")
    details: list[CrawlRunDetail] = Field(default_factory=list, description="逐源结果")


# ---------- 宣讲会 / 双选会（/campus-events 与概览） ----------


class CampusEventItem(BaseModel):
    """宣讲会/双选会列表条目（GET /campus-events）。"""

    id: int = Field(description="条目 id")
    title: str = Field(description="活动标题")
    company: str | None = Field(description="企业名称，站点未提供为 null")
    event_date: datetime = Field(description="活动开始时间（解析不到具体时刻为当日 00:00）")
    location: str | None = Field(description="举办地点")
    major_req: str | None = Field(description="需求专业（原文摘录）")
    source_url: str | None = Field(description="详情页链接")
    source_site: str | None = Field(description="来源学校名（多来源逗号分隔；映射不到时回退站点标识）")
    info_type: str = Field(description="信息类型：TALK 宣讲会 / FAIR 双选会")
    status: str = Field(description="状态：ACTIVE 有效 / CHANGED 内容已变更（前端打「已变更」角标）/ EXPIRED 已过期")
    changed_at: datetime | None = Field(description="最近一次内容变更时间，仅 CHANGED 时有值")
    match_score: int = Field(description="画像匹配打分（0~100，城市 +30 / 方向 +40 / 专业 +30）")


class CampusEventBrief(BaseModel):
    """概览「校招情报」区块的宣讲会/双选会条目（GET /overview 的 campus_events）。"""

    id: int = Field(description="条目 id")
    title: str = Field(description="活动标题")
    company: str | None = Field(description="企业名称，站点未提供为 null")
    event_date: datetime = Field(description="活动开始时间")
    location: str | None = Field(description="举办地点")
    source_url: str | None = Field(description="详情页链接")
    source_site: str | None = Field(description="来源学校名（多来源逗号分隔）")
    info_type: str = Field(description="信息类型：TALK 宣讲会 / FAIR 双选会")
    status: str = Field(description="状态：ACTIVE / CHANGED（前端打「已变更」角标）")
