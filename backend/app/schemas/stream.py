"""流式接口传输模型（接口文档 1.4 事件协议）。

各业务链路的请求体（JD 分析 / 面试作答 / 陪练点评等）自步骤 12 起陆续加入本文件。
"""

from pydantic import BaseModel, Field


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


class InterviewChatRequest(BaseModel):
    """模拟面试作答请求体（POST /stream/interview-chat，接口文档 3.7）。"""

    session_id: int = Field(description="会话 id，须属当前账号，否则 404+10002")
    answer: str | None = Field(
        default=None,
        description="本题作答；**空串 = 请出当前该出的题**（首题开场 / 续出下一题 / 重发未答题，见接口文档 3.7 实现口径 3）",
    )
    skip: bool = Field(default=False, description="true = 跳过当前未作答的题（不计分，直接下一题）")
    segments: list[dict] | None = Field(
        default=None, description="语音作答的 VAD 分句时间轴（步骤 24 语音落地后启用，本版忽略该字段）"
    )


class InterviewSummaryRequest(BaseModel):
    """面试总结请求体（POST /stream/interview-summary，接口文档 3.7）。"""

    session_id: int = Field(description="会话 id，须属当前账号且含 ≥1 条已完成问答，否则 404+10002 / 400+10001")
