"""全局 Agent 传输模型（接口文档 3.11）：对话请求体 + 会话 / 消息查询 DTO。

工具调用与结果回显走 SSE 事件（{tool_name, args} / result 段）；确认卡片执行端点
（POST /agent/tools/{tool}/execute）的请求体为工具参数字典、由路由层宽收，无请求模型。
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

AgentMessage = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class AgentChatRequest(BaseModel):
    """Agent 对话请求体（POST /stream/agent-chat）。"""

    conversation_id: int | None = Field(
        default=None,
        description="会话 id，可选；不传则新建会话（done 事件回新 id），传入但不属当前账号 → 404+10002",
    )
    message: AgentMessage = Field(description="用户输入（1~2000 字），空白 → 400+10001")


class ConversationItem(BaseModel):
    """会话列表项（GET /agent/conversations）。"""

    id: int = Field(description="会话 id")
    title: str = Field(description="会话标题（取首条用户输入截断 ≤30 字，默认「新对话」）")
    updated_at: datetime = Field(description="最近活动时间（每轮对话刷新，列表按其倒序）")


class ConversationMessageItem(BaseModel):
    """会话消息项（GET /agent/conversations/{id}/messages）。"""

    id: int = Field(description="消息 id")
    role: str = Field(description="消息角色：USER 用户 / ASSISTANT 助手回复 / TOOL 工具执行结果")
    content: str = Field(description="消息正文（TOOL 行为执行结果 JSON 文本）")
    tool_name: str | None = Field(description="关联工具名（仅 TOOL 消息或含工具调用的助手消息有值，其余为 null）")
    created_at: datetime = Field(description="创建时间")
