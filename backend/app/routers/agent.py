"""全局 Agent 会话查询接口（接口文档 3.11）。

- `GET /agent/conversations`：会话列表（最近活动倒序）；
- `GET /agent/conversations/{id}/messages`：会话消息（时间正序，含工具调用与结果）。

对话本体是 SSE 端点（`/stream/agent-chat`，见 routers/stream.py）；工具执行端点
`POST /agent/tools/{tool}/execute` 属步骤 19，本步已交付服务层执行函数 `execute_tool`。
路由层只做协议转换：取登录态、调服务层、包统一响应体，不直接访问 ORM。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.agent import ConversationItem, ConversationMessageItem
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
