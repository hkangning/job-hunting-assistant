"""全局 Agent 接口（接口文档 3.11）。

- `GET /agent/conversations`：会话列表（最近活动倒序）；
- `GET /agent/conversations/{id}/messages`：会话消息（时间正序，含工具调用与结果）；
- `POST /agent/tools/{tool}/execute`：确认卡片执行入口（写操作类工具入库）。

对话本体是 SSE 端点（`/stream/agent-chat`，见 routers/stream.py）。
路由层只做协议转换：取登录态、调服务层、包统一响应体，不直接访问 ORM。
"""

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.agent import ConversationItem, ConversationMessageItem
from app.schemas.application import ApplicationDTO
from app.schemas.common import ApiResponse, PageData
from app.services import agent_service

router = APIRouter(tags=["Agent"])


@router.get("/agent/conversations", response_model=ApiResponse[PageData[ConversationItem]], summary="Agent 会话列表")
def list_conversations(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=50, description="每页数量"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[PageData[ConversationItem]]:
    """当前账号的 Agent 会话列表，按最近活动时间倒序（同秒按 id 倒序）。"""
    data = agent_service.list_conversations(db, user_id=current_user.id, page=page, page_size=page_size)
    return ApiResponse[PageData[ConversationItem]](data=data)


@router.get(
    "/agent/conversations/{conversation_id}/messages",
    response_model=ApiResponse[list[ConversationMessageItem]],
    summary="Agent 会话消息",
)
def list_messages(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[list[ConversationMessageItem]]:
    """会话内全部消息按时间正序（同秒按 id 正序）；跨账号与不存在一律 404 + 10002。"""
    data = agent_service.list_messages(db, user_id=current_user.id, conversation_id=conversation_id)
    return ApiResponse[list[ConversationMessageItem]](data=data)


@router.post(
    "/agent/tools/{tool}/execute",
    response_model=ApiResponse[ApplicationDTO],
    summary="执行确认卡片动作",
)
def execute_tool(
    tool: str,
    payload: dict | None = Body(default=None, description="工具参数：键集随工具而异，前端将卡片下发的 args 原样回传"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[ApplicationDTO]:
    """确认卡片执行入口：仅写操作类工具（新增投递 / 状态流转），返回投递 DTO。

    请求体宽收为字典（不用强类型 DTO）：两个工具参数集不同，参数缺失 / 非法统一由
    服务层宽转后报 400 + 50001（强类型校验会在路由前拦成 10001，与契约不符）。
    执行动作与对话流解耦，不落会话消息。
    """
    data = agent_service.execute_tool(db, user_id=current_user.id, tool_name=tool, args=payload or {})
    return ApiResponse[ApplicationDTO](data=data)
