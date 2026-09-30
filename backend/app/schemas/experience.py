"""面经整理：面经与结构化条目的传输模型（接口文档 3.10）。"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_serializer

from app.utils.datetime_utils import format_datetime

# 面经原文：必填、去首尾空格、1~10000 字（接口文档 3.10，超长提示分段）
RequiredOriginalText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)
]


class ExperienceCreateRequest(BaseModel):
    """新增面经请求体（POST /experiences）：**只存原文，不触发提取**（提取走 /stream/experience-extract）。"""

    company: str | None = Field(default=None, max_length=100, description="公司，≤100 字，未填为 null")
    position: str | None = Field(default=None, max_length=100, description="岗位，≤100 字，未填为 null")
    source: str | None = Field(
        default=None, max_length=100, description="来源（牛客 / 公众号 / 同学分享），≤100 字，未填为 null"
    )
    original_text: RequiredOriginalText = Field(description="面经原文全文，必填，1~10000 字")


class ExperienceItemDTO(BaseModel):
    """面经结构化条目（详情 `items` 元素，按 id 升序即提取顺序）。"""

    id: int = Field(description="条目 id")
    question: str = Field(description="面试问题")
    answer_points: str | None = Field(description="回答要点，原文未提答案时为 null")
    source_type: str = Field(description="条目来源：LLM_EXTRACT AI 提取 / MANUAL 手动补充")


class ExperienceListItem(BaseModel):
    """面经列表项：不含原文（列表精简，接口文档 3.10）。"""

    id: int = Field(description="面经 id")
    company: str | None = Field(description="公司，未填为 null")
    position: str | None = Field(description="岗位，未填为 null")
    source: str | None = Field(description="来源，未填为 null")
    item_count: int = Field(description="结构化条目数（冗余计数）")
    created_at: datetime = Field(description="创建时间")

    @field_serializer("created_at")
    def _serialize_datetime(self, value: datetime) -> str | None:
        """时间字段按接口口径输出 `YYYY-MM-DD HH:mm:ss`。"""
        return format_datetime(value)


class ExperienceDTO(BaseModel):
    """面经 DTO（创建响应与详情共用）：原文全文 + 结构化条目列表。"""

    id: int = Field(description="面经 id")
    company: str | None = Field(description="公司，未填为 null")
    position: str | None = Field(description="岗位，未填为 null")
    source: str | None = Field(description="来源，未填为 null")
    original_text: str = Field(description="面经原文全文")
    item_count: int = Field(description="结构化条目数（冗余计数，与 items 长度一致）")
    created_at: datetime = Field(description="创建时间")
    items: list[ExperienceItemDTO] = Field(description="结构化条目列表，按 id 升序；未提取时为空数组")

    @field_serializer("created_at")
    def _serialize_datetime(self, value: datetime) -> str | None:
        """时间字段按接口口径输出 `YYYY-MM-DD HH:mm:ss`。"""
        return format_datetime(value)


class ExperienceItemSearchItem(BaseModel):
    """条目检索结果项（跨面经，`company` 联表 experience）。"""

    id: int = Field(description="条目 id")
    experience_id: int = Field(description="所属面经 id（前端据此跳详情页并定位条目）")
    company: str | None = Field(description="所属面经的公司，未填为 null")
    question: str = Field(description="面试问题")
    answer_points: str | None = Field(description="回答要点，未提答案时为 null")
