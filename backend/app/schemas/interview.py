"""AI 模拟面试：会话与问答的传输模型（接口文档 3.7）。"""

from datetime import datetime

from pydantic import BaseModel, Field, field_serializer

from app.models.enums import Direction, InterviewIntensity
from app.utils.datetime_utils import format_datetime


class SessionCreateRequest(BaseModel):
    """建会话请求体（POST /interview-sessions）。"""

    application_id: int | None = Field(
        default=None,
        description="关联的投递记录 id，可选；传入时公司 / 岗位从中带入，须属当前账号，否则 404+10002",
    )
    company: str | None = Field(
        default=None, max_length=100, description="公司名；未传 application_id 时必填（与 position 成对）"
    )
    position: str | None = Field(
        default=None, max_length=100, description="岗位名；未传 application_id 时必填（与 company 成对）"
    )
    direction: Direction = Field(
        default=Direction.GENERAL,
        description="面试方向，默认 GENERAL（不限方向）；也可取任一领域枚举值（如 JAVA / REDIS）做专项面试",
    )
    question_count: int = Field(default=8, ge=3, le=15, description="题量 3~15，默认 8")
    intensity: InterviewIntensity = Field(
        default=InterviewIntensity.MEDIUM,
        description="面试强度：LARGE 大厂（深挖原理与系统设计、评分从严）/ MEDIUM 中厂（默认，基础与工程实操并重）/ SMALL 小厂（偏基础与落地、评分宽）；随会话固定，AI 按它校准出题深度与评分严格度",
    )


class StagePlanItem(BaseModel):
    """阶段计划条目（会话 DTO 的 `stages` 元素）：按数组顺序推进，题号落在哪段据此计算。"""

    stage: str = Field(description="阶段枚举值：INTRO 自我介绍 / TECH 技术问答 / PROJECT 项目深挖")
    count: int = Field(description="该阶段题量")


class InterviewSessionDTO(BaseModel):
    """会话 DTO（建会话与详情共用）。"""

    id: int = Field(description="会话 id")
    application_id: int | None = Field(description="关联的投递记录 id，手填发起时为 null")
    company: str = Field(description="公司名（从投递带入或手填）")
    position: str = Field(description="岗位名（从投递带入或手填）")
    direction: str = Field(description="面试方向枚举值（GENERAL 或任一领域值）")
    question_count: int = Field(description="计划题量（3~15）")
    intensity: str = Field(
        description="面试强度：LARGE 大厂 / MEDIUM 中厂 / SMALL 小厂；强度上线前的存量会话按 MEDIUM 兜底，不返回 null"
    )
    stages: list[StagePlanItem] | None = Field(
        description="阶段计划（自我介绍 / 技术问答 / 项目深挖的题量分配；画像未填经历时不含项目深挖段）；阶段化上线前的老会话为 null，前端降级为「第 N/M 题」"
    )
    status: str = Field(description="会话状态：ACTIVE 进行中 / FINISHED 已结束")
    summary: str | None = Field(description="本场总结全文，未生成为 null")
    created_at: datetime = Field(description="创建时间")
    finished_at: datetime | None = Field(description="结束时间，未结束为 null")

    @field_serializer("created_at", "finished_at")
    def _serialize_datetime(self, value: datetime | None) -> str | None:
        """时间字段按接口口径输出 `YYYY-MM-DD HH:mm:ss`。"""
        return format_datetime(value)


class SessionListItem(InterviewSessionDTO):
    """列表条目：会话 DTO + 进度计数。"""

    qa_count: int = Field(description="已落库问答条数（含尚未作答的当前题），供列表显示进度")


class QaItem(BaseModel):
    """单条问答（详情 qa_list 元素，按 seq 升序，含尚未作答的当前题）。"""

    id: int = Field(description="问答 id（流式 done 的 record_id 即此值）")
    seq: int = Field(description="题序，从 1 开始")
    question: str = Field(description="AI 提问原文")
    answer: str | None = Field(description="用户作答，未作答 / 跳题为 null")
    is_voice: int = Field(description="是否语音作答（0 文字 / 1 语音）")
    voice_metrics: dict | None = Field(
        default=None,
        description="表达力指标快照（语音作答且 quality=OK 时下发，结构见数据库设计 §3.19）；非语音作答 / 作答过短为 null",
    )
    score: int | None = Field(description="本题得分 0~10，未作答 / 跳题为 null")
    review: str | None = Field(description="AI 点评全文，未作答 / 跳题为 null")
    skipped: int = Field(description="是否跳过（0 否 / 1 是），跳题不计分")
    created_at: datetime = Field(description="提问时间")

    @field_serializer("created_at")
    def _serialize_datetime(self, value: datetime) -> str | None:
        """时间字段按接口口径输出 `YYYY-MM-DD HH:mm:ss`。"""
        return format_datetime(value)


class SessionDetailData(InterviewSessionDTO):
    """详情响应：会话 DTO + 问答列表。"""

    qa_list: list[QaItem] = Field(description="本场全部问答，按 seq 升序")
