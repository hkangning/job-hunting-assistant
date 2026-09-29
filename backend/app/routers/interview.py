"""AI 模拟面试接口：会话建 / 列表 / 详情（接口文档 3.7）。

流式作答端点在流式路由组（`POST /stream/interview-chat`）。
路由层只做协议转换（系统设计 3.1）：参数校验、调服务层、包统一响应体，不直接访问 ORM。
数据归属一律取自登录态（current_user.id）。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models.enums import SessionStatus
from app.schemas.common import ApiResponse, PageData
from app.schemas.interview import (
    InterviewSessionDTO,
    SessionCreateRequest,
    SessionDetailData,
    SessionListItem,
)
from app.services import interview_service

router = APIRouter(prefix="/interview-sessions", tags=["模拟面试"])


@router.post("", response_model=ApiResponse[InterviewSessionDTO], status_code=201, summary="创建面试会话")
def create_session(
    payload: SessionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[InterviewSessionDTO]:
    """创建会话：关联投递带入公司 / 岗位，或手填（缺一 400 + 10001）。"""
    return ApiResponse[InterviewSessionDTO](
        data=interview_service.create_session(db, user_id=current_user.id, payload=payload)
    )


@router.get("", response_model=ApiResponse[PageData[SessionListItem]], summary="面试会话列表")
def list_sessions(
    status: SessionStatus | None = Query(
        None, description="按状态过滤：ACTIVE 进行中 / FINISHED 已结束；不传 = 全部"
    ),
    page: int = Query(1, ge=1, description="页码，从 1 起"),
    page_size: int = Query(10, ge=1, le=50, description="每页条数，默认 10，最大 50"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[PageData[SessionListItem]]:
    """当前账号的会话列表，按创建时间倒序（同秒按 id 倒序）。"""
    return ApiResponse[PageData[SessionListItem]](
        data=interview_service.list_sessions(
            db, user_id=current_user.id, status=status, page=page, page_size=page_size
        )
    )


@router.get("/{session_id}", response_model=ApiResponse[SessionDetailData], summary="面试会话详情")
def get_session_detail(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[SessionDetailData]:
    """会话详情：会话字段 + 全部问答（按 seq 升序，含尚未作答的当前题）。"""
    return ApiResponse[SessionDetailData](
        data=interview_service.get_session_detail(db, user_id=current_user.id, session_id=session_id)
    )
