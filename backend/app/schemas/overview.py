"""今日概览传输模型：聚合响应及其子项（接口文档 3.4）。"""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import ApplicationStatus


class UpcomingEventItem(BaseModel):
    """待笔试 / 待面试条目（7 日内）。"""

    application_id: int = Field(description="投递记录 id")
    company: str = Field(description="公司名称")
    position: str = Field(description="岗位名称")
    event_at: datetime = Field(description="笔试/面试时间 YYYY-MM-DD HH:mm:ss")
    status: ApplicationStatus = Field(
        description="当前进度状态：APPLIED（已投递）/WRITTEN（待笔试）/INTERVIEW（面试中）/OFFER（已获 offer）"
    )


class ApplicationStats(BaseModel):
    """投递各状态计数：恒返回 5 个键，无该状态记录时为 0。"""

    APPLIED: int = Field(default=0, description="已投递数量")
    WRITTEN: int = Field(default=0, description="待笔试数量")
    INTERVIEW: int = Field(default=0, description="面试中数量")
    OFFER: int = Field(default=0, description="已获 offer 数量")
    CLOSED: int = Field(default=0, description="已结束数量")


class FollowUpItem(BaseModel):
    """3 天无进展的投递（跟进提醒）。"""

    application_id: int = Field(description="投递记录 id")
    company: str = Field(description="公司名称")
    position: str = Field(description="岗位名称")
    applied_at: date = Field(description="投递日期 YYYY-MM-DD")
    days: int = Field(description="距投递日期已过天数（≥3），列表按此降序")


class OverviewStats(BaseModel):
    """个人中心数据概览计数：均按登录账号统计，跨账号互不可见。"""

    application_count: int = Field(description="当前账号投递总数（含已结束）")
    wrong_question_count: int = Field(description="当前账号错题总数（含已掌握），与顶层 wrong_question_count 语义不同")
    interview_count: int = Field(description="当前账号模拟面试会话数（含进行中与已结束）")


class OverviewData(BaseModel):
    """`GET /overview` 响应 data：9 个字段恒返回，无数据时为 `[]` / `0` / `null`。"""

    upcoming_events: list[UpcomingEventItem] = Field(
        default_factory=list, description="待面试/笔试，7 日内按时间升序"
    )
    application_stats: ApplicationStats = Field(description="投递各状态计数")
    follow_ups: list[FollowUpItem] = Field(
        default_factory=list, description="3 天无进展的投递，按 days 降序（拖得越久越靠前）"
    )
    wrong_question_count: int = Field(default=0, description="到期未复习错题数")
    campus_events: list[dict] = Field(
        default_factory=list,
        description="近期宣讲会/双选会，按日期升序取前若干条；子项结构见接口文档 3.4（数据源属校招情报，步骤 21 落地前恒为空列表）",
    )
    last_crawl_at: datetime | None = Field(
        default=None, description="最近一次校招信息采集时间；null=从未采集（步骤 21 落地前恒为 null）"
    )
    top_job_postings: list[dict] = Field(
        default_factory=list,
        description="匹配度最高的若干条岗位，按匹配打分降序；子项结构见接口文档 3.4（数据源属校招情报，步骤 22 落地前恒为空列表）",
    )
    match_reminder_count: int = Field(
        default=0, description="命中订阅的未读提醒数（步骤 22 落地前恒为 0）"
    )
    stats: OverviewStats = Field(description="个人中心数据概览计数")
