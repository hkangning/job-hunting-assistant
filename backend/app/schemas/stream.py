"""流式接口传输模型（接口文档 1.4 事件协议）。

各业务链路的请求体（JD 分析 / 面试作答 / 陪练点评等）自步骤 12 起陆续加入本文件。
"""

from pydantic import BaseModel, Field


class DemoChatRequest(BaseModel):
    """流式协议自检请求体（POST /stream/demo，步骤 11）。"""

    message: str = Field(min_length=1, max_length=500, description="用户输入文本（1~500 字），原样交给当前账号的 AI 配置流式回答")


class JdAnalysisRequest(BaseModel):
    """JD 匹配分析请求体（POST /stream/jd-analysis，接口文档 3.6）。"""

    jd_text: str = Field(min_length=1, max_length=10000, description="JD 原文（1~10000 字），分析后作为快照随报告落库")
    application_id: int | None = Field(default=None, description="关联的投递记录 id，可选；传入时须属当前账号，否则 10002")
