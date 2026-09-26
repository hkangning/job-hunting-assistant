"""流式接口传输模型（接口文档 1.4 事件协议）。

各业务链路的请求体（JD 分析 / 面试作答 / 陪练点评等）自步骤 12 起陆续加入本文件。
"""

from pydantic import BaseModel, Field


class DemoChatRequest(BaseModel):
    """流式协议自检请求体（POST /stream/demo，步骤 11）。"""

    message: str = Field(min_length=1, max_length=500, description="用户输入文本（1~500 字），原样交给当前账号的 AI 配置流式回答")
