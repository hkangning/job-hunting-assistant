"""练习模式：题目与练习记录的传输模型（接口文档 3.15）。"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_serializer

from app.models.enums import DrillSource
from app.utils.datetime_utils import format_datetime

# 标题：必填、去首尾空格、1~50 字（接口文档 3.15）
RequiredTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
]

# 题面（创建）：可选、去首尾空格、≤2000 字；空串视为未提供，由 AI 按 title + 来源生成
OptionalQuestion = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]

# 题面（更新）：提供即须非空（drill_topic.question 为非空列）
RequiredQuestion = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]


class DrillListItem(BaseModel):
    """题目列表项（GET /drills）：不含题面（列表精简）。"""

    id: int = Field(description="题目 id")
    title: str = Field(description="标题")
    source: str = Field(description="来源枚举值：INTRO / RESUME / WRONG / EXPERIENCE / JD / CUSTOM")
    ref_id: int | None = Field(description="来源实体 id，手动新建为 null")
    archived: int = Field(description="是否归档（0 未归档 / 1 已归档）")
    attempt_count: int = Field(description="练习遍数")
    last_score: int | None = Field(description="最近一遍的得分（取最后一次非空 score），从未得分为 null")
    best_score: int | None = Field(description="历史最高分，从未得分为 null")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    @field_serializer("created_at", "updated_at")
    def _serialize_datetime(self, value: datetime) -> str | None:
        """时间字段按接口口径输出 `YYYY-MM-DD HH:mm:ss`。"""
        return format_datetime(value)


class DrillAttemptItem(BaseModel):
    """练习记录摘要（详情 `attempts` 元素）：不含点评全文与指标。"""

    id: int = Field(description="练习记录 id")
    seq: int = Field(description="第几遍，从 1 开始")
    is_voice: int = Field(description="是否语音作答（0 文字 / 1 语音）")
    score: int | None = Field(description="得分 0~10")
    duration_ms: int | None = Field(description="作答时长（毫秒）")
    created_at: datetime = Field(description="练习时间")

    @field_serializer("created_at")
    def _serialize_datetime(self, value: datetime) -> str | None:
        """时间字段按接口口径输出 `YYYY-MM-DD HH:mm:ss`。"""
        return format_datetime(value)


class DrillAttemptDTO(BaseModel):
    """单次练习完整 DTO（GET /drills/{topic_id}/attempts/{attempt_id}）。"""

    id: int = Field(description="练习记录 id")
    topic_id: int = Field(description="所属题目 id")
    seq: int = Field(description="第几遍，从 1 开始")
    answer: str | None = Field(description="作答内容")
    is_voice: int = Field(description="是否语音作答（0 文字 / 1 语音）")
    voice_metrics: dict | None = Field(
        default=None,
        description="表达力指标快照（语音作答且 quality=OK 时下发，结构见数据库设计 §3.19）；非语音作答 / 作答过短为 null",
    )
    score: int | None = Field(description="得分 0~10，点评未产出评分为 null")
    review: str | None = Field(description="AI 点评全文")
    duration_ms: int | None = Field(description="作答时长（毫秒）")
    created_at: datetime = Field(description="练习时间")

    @field_serializer("created_at")
    def _serialize_datetime(self, value: datetime) -> str | None:
        """时间字段按接口口径输出 `YYYY-MM-DD HH:mm:ss`。"""
        return format_datetime(value)


class DrillTopicDTO(BaseModel):
    """题目 DTO（创建响应与详情共用）。"""

    id: int = Field(description="题目 id")
    title: str = Field(description="标题")
    question: str = Field(description="完整题面")
    source: str = Field(description="来源枚举值：INTRO / RESUME / WRONG / EXPERIENCE / JD / CUSTOM")
    ref_id: int | None = Field(description="来源实体 id，手动新建为 null")
    archived: int = Field(description="是否归档（0 未归档 / 1 已归档）")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")

    @field_serializer("created_at", "updated_at")
    def _serialize_datetime(self, value: datetime) -> str | None:
        """时间字段按接口口径输出 `YYYY-MM-DD HH:mm:ss`。"""
        return format_datetime(value)


class DrillTopicDetailData(DrillTopicDTO):
    """详情响应：题目 DTO + 练习记录摘要数组。"""

    attempts: list[DrillAttemptItem] = Field(description="练习记录摘要，按 seq 升序")


class DrillCreateRequest(BaseModel):
    """新建题目请求体（POST /drills）。"""

    title: RequiredTitle = Field(description="题目标题，1~50 字")
    question: OptionalQuestion | None = Field(
        default=None,
        description="完整题面，≤2000 字；不传或传空串由 AI 按 `title` + 来源信息生成（生成失败返回 10012 / 10011）",
    )
    source: DrillSource = Field(
        default=DrillSource.CUSTOM,
        description="来源枚举，默认 CUSTOM；INTRO 可免 ref_id，WRONG / EXPERIENCE / JD 须传 ref_id，RESUME 暂不支持（10001）",
    )
    ref_id: int | None = Field(
        default=None, description="来源实体 id；source 非 CUSTOM 时必填（INTRO 除外），后端校验归属，不属于当前账号 → 404+10002"
    )


class DrillUpdateRequest(BaseModel):
    """编辑题目请求体（PUT /drills/{topic_id}）：部分更新，只更新出现过的字段。"""

    title: RequiredTitle | None = Field(default=None, description="标题，1~50 字；不传不改")
    question: RequiredQuestion | None = Field(
        default=None, description="完整题面，1~2000 字（提供即须非空）；不传不改"
    )
    archived: bool | None = Field(
        default=None, description="true 归档 / false 恢复；不传不改。归档后默认列表不展示、不可再提交作答"
    )


class DrillProgressItem(BaseModel):
    """进步对比数据点（progress `items` 元素）：表达指标取自该遍 voice_metrics（非语音 / 过短为 null）。"""

    seq: int = Field(description="第几遍，从 1 开始")
    score: int | None = Field(description="得分 0~10")
    duration_ms: int | None = Field(description="作答时长（毫秒）")
    speech_rate: int | None = Field(description="语速（字/分），无表达指标为 null")
    filler_count: int | None = Field(description="填充词次数，无表达指标为 null")
    pause_count: int | None = Field(description="长停顿处数，无表达指标为 null")
    speech_ratio: float | None = Field(description="有效时长占比，无表达指标为 null")


class DrillProgressDeltas(BaseModel):
    """最近一遍 vs 上一次的差值（`to - from`）：任一为空则该项为 null；不足两遍对比时为 null。"""

    score: int | None = Field(description="得分变化")
    duration_ms: int | None = Field(description="时长变化（毫秒，负数为变快）")
    filler_count: int | None = Field(description="填充词变化（负数为变少，变好）")
    pause_count: int | None = Field(description="停顿变化（负数为变少，变好）")


class DrillProgressDTO(BaseModel):
    """进步对比响应（GET /drills/{topic_id}/progress）。"""

    topic_id: int = Field(description="题目 id")
    attempt_count: int = Field(description="练习总遍数（含无表达指标的遍次）")
    items: list[DrillProgressItem] = Field(
        description="逐遍数据点，按 seq 升序；表达指标口径版本与最新版不一致的遍次不参与列表（跨版本不并列展示）"
    )
    deltas: DrillProgressDeltas | None = Field(
        description="最近一遍 vs 上一次的差值；可比数据不足两条为 null"
    )
