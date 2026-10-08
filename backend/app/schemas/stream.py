"""流式接口传输模型（接口文档 1.4 事件协议）。

各业务链路的请求体（JD 分析 / 面试作答 / 陪练点评等）自步骤 12 起陆续加入本文件。
"""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator


class DemoChatRequest(BaseModel):
    """流式协议自检请求体（POST /stream/demo，步骤 11）。"""

    message: str = Field(min_length=1, max_length=500, description="用户输入文本（1~500 字），原样交给当前账号的 AI 配置流式回答")


class JdAnalysisRequest(BaseModel):
    """JD 匹配分析请求体（POST /stream/jd-analysis，接口文档 3.6）。"""

    jd_text: str | None = Field(
        default=None,
        max_length=10000,
        description="JD 原文（≤10000 字），可选；传 application_id 时省略则取该投递已填的岗位 JD，显式传入则覆盖；两者都取不到返回 10001",
    )
    application_id: int | None = Field(default=None, description="关联的投递记录 id，可选；传入时须属当前账号，否则 10002")


class SegmentItem(BaseModel):
    """语音作答的分句时间轴片段（VAD 在前端执行，接口文档 3.13）。"""

    seq: int = Field(ge=1, description="句序，从 1 开始")
    start_ms: int = Field(ge=0, description="该句开始时间（毫秒）")
    end_ms: int = Field(ge=0, description="该句结束时间（毫秒）")
    text: str = Field(description="该句原始转写文本")

    @model_validator(mode="after")
    def _check_order(self):
        """起止颠倒 / 零长片段视为非法（IS-65）：参数校验层拦截，先于流式建立返回 400+10001。"""
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms 必须大于 start_ms")
        return self


class InterviewChatRequest(BaseModel):
    """模拟面试作答请求体（POST /stream/interview-chat，接口文档 3.7）。"""

    session_id: int = Field(description="会话 id，须属当前账号，否则 404+10002")
    answer: str | None = Field(
        default=None,
        description="本题作答；**空串 = 请出当前该出的题**（首题开场 / 续出下一题 / 重发未答题，见接口文档 3.7 实现口径 3）",
    )
    skip: bool = Field(default=False, description="true = 跳过当前未作答的题（不计分，直接下一题）")
    segments: list[SegmentItem] | None = Field(
        default=None,
        description="语音作答时必传：VAD 分句时间轴 `[{seq, start_ms, end_ms, text}]`（见接口文档 3.13），供计算表达力指标；文字作答不传",
    )


class InterviewSummaryRequest(BaseModel):
    """面试总结请求体（POST /stream/interview-summary，接口文档 3.7）。"""

    session_id: int = Field(
        description="会话 id，须属当前账号，否则 404+10002；0 条已完成问答亦可（落固定说明文案、不调 LLM，见接口文档 3.7 实现口径 7）"
    )


class ExperienceExtractRequest(BaseModel):
    """面经结构化提取请求体（POST /stream/experience-extract，接口文档 3.10）。"""

    experience_id: int = Field(description="面经 id，须属当前账号，否则 404+10002；原文为空或提取失败时原文保留，可重试")


class DrillReviewRequest(BaseModel):
    """练习模式点评请求体（POST /stream/drill-review，接口文档 3.15）。"""

    topic_id: int = Field(description="题目 id，须属当前账号，否则 404+10002；已归档 → 409+40003")
    answer: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)
    ] = Field(description="本次作答，必填 1~5000 字（自动去首尾空格），留空提交返回 10001")
    is_voice: bool = Field(default=False, description="是否语音作答（前端按本次是否录过音判断）")
    segments: list[SegmentItem] | None = Field(
        default=None,
        description="语音作答时传：VAD 分句时间轴 `[{seq, start_ms, end_ms, text}]`（见接口文档 3.13），供计算表达力指标；文字作答不传",
    )
    duration_ms: int | None = Field(
        default=None, ge=0, description="本次作答时长（毫秒，前端计时上报）；不传为 null"
    )
