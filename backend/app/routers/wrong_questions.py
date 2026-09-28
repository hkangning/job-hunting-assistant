"""错题本接口：列表 / 添加 / 删除 / 复习判定（接口文档 3.9）。

路由层只做协议转换（系统设计 3.1）：参数校验、调服务层、包统一响应体，不直接访问 ORM。
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.clients.llm_client import LLMClient, get_llm_client
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.common import ApiResponse, PageData
from app.schemas.wrong_question import (
    WrongQuestionAddRequest,
    WrongQuestionItem,
    WrongQuestionReviewData,
    WrongQuestionReviewRequest,
)
from app.services import wrong_question_service

router = APIRouter(prefix="/wrong-questions", tags=["错题本"])


@router.get("", response_model=ApiResponse[PageData[WrongQuestionItem]], summary="错题列表")
def list_wrong_questions(
    status: Literal["PENDING", "MASTERED"] | None = Query(
        None, description="按状态过滤：PENDING 待复习 / MASTERED 已掌握；不传 = 全部"
    ),
    page: int = Query(1, ge=1, description="页码，从 1 起"),
    page_size: int = Query(10, ge=1, le=50, description="每页条数，默认 10，最大 50"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[PageData[WrongQuestionItem]]:
    """当前账号的错题列表：未掌握优先、再按到期先后（先看该复习的）。"""
    return ApiResponse[PageData[WrongQuestionItem]](
        data=wrong_question_service.list_wrong_questions(
            db, user_id=current_user.id, status=status, page=page, page_size=page_size
        )
    )


@router.post("", response_model=ApiResponse[WrongQuestionItem], summary="添加错题")
def add_wrong_question(
    payload: WrongQuestionAddRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[WrongQuestionItem]:
    """两种请求形态（接口文档 §3.9）：题库题给 `question_id`；面试 / 练习知识点给 `content` 等四字段，后端自动建题。"""
    return ApiResponse[WrongQuestionItem](
        data=wrong_question_service.add_wrong_question(db, user_id=current_user.id, payload=payload)
    )


@router.delete("/{wrong_question_id}", response_model=ApiResponse[None], summary="删除错题")
def delete_wrong_question(
    wrong_question_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[None]:
    """删除错题条目（删后按该题所属领域重算掌握度）。"""
    wrong_question_service.delete_wrong_question(
        db, user_id=current_user.id, wrong_question_id=wrong_question_id
    )
    return ApiResponse[None](data=None)


@router.post(
    "/{wrong_question_id}/review",
    response_model=ApiResponse[WrongQuestionReviewData],
    summary="复习判定",
)
def review_wrong_question(
    wrong_question_id: int,
    payload: WrongQuestionReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    client: LLMClient = Depends(get_llm_client),
) -> ApiResponse[WrongQuestionReviewData]:
    """提交复习作答：客观题规则比对（零 token），主观题与场景题走 LLM 判定；随后推进复习档位。"""
    return ApiResponse[WrongQuestionReviewData](
        data=wrong_question_service.review_wrong_question(
            db,
            user_id=current_user.id,
            wrong_question_id=wrong_question_id,
            answer=payload.answer,
            client=client,
        )
    )
