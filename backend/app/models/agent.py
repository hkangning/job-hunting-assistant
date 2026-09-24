"""Agent 会话与消息模型（数据库设计文档 3.10 / 3.11）。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgentConversation(Base):
    """Agent 会话（FR-011）。"""

    __tablename__ = "agent_conversation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    title: Mapped[str] = mapped_column(String(100), default="新对话")  # 会话标题（首条输入截取）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 创建时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )  # 更新时间


class AgentMessage(Base):
    """Agent 消息：含工具调用与执行结果（FR-011）。"""

    __tablename__ = "agent_message"
    __table_args__ = (Index("idx_agent_msg_conv", "conversation_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # 主键
    conversation_id: Mapped[int] = mapped_column(ForeignKey("agent_conversation.id"))  # 所属会话
    role: Mapped[str] = mapped_column(String(10))  # 角色，枚举 MessageRole（USER/ASSISTANT/TOOL）
    content: Mapped[str] = mapped_column(Text)  # 文本内容（TOOL 为执行结果文本）
    tool_name: Mapped[str | None] = mapped_column(String(50))  # 工具名（TOOL/含工具调用的 ASSISTANT）
    tool_args: Mapped[str | None] = mapped_column(Text)  # 工具参数 JSON 字符串（应用层序列化）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)  # 消息时间
