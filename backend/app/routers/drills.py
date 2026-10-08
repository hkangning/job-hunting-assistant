"""练习模式接口：题目管理与进步对比（接口文档 3.15）。

逐遍点评端点在流式路由组（`POST /stream/drill-review`）。
路由层只做协议转换（系统设计 3.1）：参数校验、调服务层、包统一响应体，不直接访问 ORM。
数据归属一律取自登录态（current_user.id）。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.clients.llm_client import LLMClient, get_llm_client
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models.enums import DrillSource
from app.schemas.common import ApiResponse, PageData
from app.schemas.drill import (
    DrillAttemptDTO,
    DrillCreateRequest,
    DrillListItem,
    DrillProgressDTO,
    DrillTopicDTO,
    DrillTopicDetailData,
    DrillUpdateRequest,
)
from app.services import drill_service

router = APIRouter(prefix="/drills", tags=["练习模式"])


@router.get("", response_model=ApiResponse[PageData[DrillListItem]], summary="题目列表")
def list_topics(
    archived: bool | None = Query(None, description="归档筛选：不传 = 未归档；true = 已归档"),
    source: DrillSource | None = Query(None, description="按来源过滤，不传 = 全部"),
    page: int = Query(1, ge=1, description="页码，从 1 起"),
    page_size: int = Query(10, ge=1, le=50, description="每页条数，默认 10，最大 50"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[PageData[DrillListItem]]:
    """当前账号的题目列表，按创建时间倒序；`attempt_count` / `last_score` / `best_score` 为聚合。"""
    return ApiResponse[PageData[DrillListItem]](
        data=drill_service.list_topics(
            db,
            user_id=current_user.id,
            archived=archived,
            source=source,
            page=page,
            page_size=page_size,
        )
    )


@router.post("", response_model=ApiResponse[DrillTopicDTO], status_code=201, summary="新建题目")
def create_topic(
    payload: DrillCreateRequest,
    current_user: User = Depends(get_current_user),
    client: LLMClient = Depends(get_llm_client),
    db: Session = Depends(get_db),
) -> ApiResponse[DrillTopicDTO]:
    """题面不传或传空串时由 AI 按标题 + 来源生成（未配 Key → 10012，生成失败 → 10011）。"""
    return ApiResponse[DrillTopicDTO](
        data=drill_service.create_topic(db, user_id=current_user.id, payload=payload, client=client)
    )


@router.get("/{topic_id}", response_model=ApiResponse[DrillTopicDetailData], summary="题目详情")
def get_topic_detail(
    topic_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[DrillTopicDetailData]:
    """题目字段 + 练习记录摘要（按 seq 升序，不含点评全文与表达指标）。"""
    return ApiResponse[DrillTopicDetailData](
        data=drill_service.get_topic_detail(db, user_id=current_user.id, topic_id=topic_id)
    )


@router.put("/{topic_id}", response_model=ApiResponse[DrillTopicDTO], summary="编辑题目")
def update_topic(
    topic_id: int,
    payload: DrillUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[DrillTopicDTO]:
    """部分更新 title / question / archived；归档后默认列表不展示、不可再提交作答（409+40003）。"""
    return ApiResponse[DrillTopicDTO](
        data=drill_service.update_topic(
            db, user_id=current_user.id, topic_id=topic_id, payload=payload
        )
    )


@router.get(
    "/{topic_id}/attempts/{attempt_id}",
    response_model=ApiResponse[DrillAttemptDTO],
    summary="单次练习详情",
)
def get_attempt(
    topic_id: int,
    attempt_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[DrillAttemptDTO]:
    """完整练习记录：作答、得分、点评全文与表达力指标。"""
    return ApiResponse[DrillAttemptDTO](
        data=drill_service.get_attempt(
            db, user_id=current_user.id, topic_id=topic_id, attempt_id=attempt_id
        )
    )


@router.get("/{topic_id}/progress", response_model=ApiResponse[DrillProgressDTO], summary="进步对比")
def get_progress(
    topic_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[DrillProgressDTO]:
    """逐遍数据点 + 最近两条可比记录的差值（跨指标版本不并列对比）。"""
    return ApiResponse[DrillProgressDTO](
        data=drill_service.get_progress(db, user_id=current_user.id, topic_id=topic_id)
    )
