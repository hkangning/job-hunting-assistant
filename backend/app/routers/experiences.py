"""面经整理接口：新增 / 列表 / 详情 / 删除 + 条目检索（接口文档 3.10）。

路由层只做协议转换（系统设计 3.1）：参数校验、调服务层、包统一响应体，不直接访问 ORM。
两族路径（`/experiences` 与 `/experience-items`）共用本 router，故不设 prefix、写全路径。
结构化提取是流式接口，在 routers/stream.py 注册。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.common import ApiResponse, PageData
from app.schemas.experience import (
    ExperienceCreateRequest,
    ExperienceDTO,
    ExperienceItemSearchItem,
    ExperienceListItem,
)
from app.services import experience_service

router = APIRouter(tags=["面经整理"])


@router.post("/experiences", response_model=ApiResponse[ExperienceDTO], summary="新增面经")
def create_experience(
    payload: ExperienceCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[ExperienceDTO]:
    """只存原文、不触发提取；条目由 `/stream/experience-extract` 提取。"""
    return ApiResponse[ExperienceDTO](
        data=experience_service.create_experience(db, user_id=current_user.id, payload=payload)
    )


@router.get("/experiences", response_model=ApiResponse[PageData[ExperienceListItem]], summary="面经列表")
def list_experiences(
    page: int = Query(1, ge=1, description="页码，从 1 起"),
    page_size: int = Query(10, ge=1, le=50, description="每页条数，默认 10，最大 50"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[PageData[ExperienceListItem]]:
    """当前账号的面经列表，创建时间倒序；不含原文（大字段只走详情）。"""
    return ApiResponse[PageData[ExperienceListItem]](
        data=experience_service.list_experiences(
            db, user_id=current_user.id, page=page, page_size=page_size
        )
    )


@router.get("/experiences/{experience_id}", response_model=ApiResponse[ExperienceDTO], summary="面经详情")
def get_experience(
    experience_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[ExperienceDTO]:
    """原文全文 + 结构化条目列表（按提取顺序）；不存在或跨账号 → 10002。"""
    return ApiResponse[ExperienceDTO](
        data=experience_service.get_experience(
            db, user_id=current_user.id, experience_id=experience_id
        )
    )


@router.delete("/experiences/{experience_id}", response_model=ApiResponse[None], summary="删除面经")
def delete_experience(
    experience_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[None]:
    """删除面经并级联删除其结构化条目（同事务）；不存在或跨账号 → 10002。"""
    experience_service.delete_experience(db, user_id=current_user.id, experience_id=experience_id)
    return ApiResponse[None](data=None)


@router.get(
    "/experience-items/search",
    response_model=ApiResponse[PageData[ExperienceItemSearchItem]],
    summary="条目检索",
)
def search_items(
    keyword: str = Query(..., min_length=1, max_length=50, description="检索关键词（1~50 字），按题干模糊匹配；只含空白 → 10001"),
    page: int = Query(1, ge=1, description="页码，从 1 起"),
    page_size: int = Query(10, ge=1, le=50, description="每页条数，默认 10，最大 50"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[PageData[ExperienceItemSearchItem]]:
    """跨面经检索本账号的结构化条目，结果带所属面经的公司（前端据此跳详情并定位条目）。"""
    return ApiResponse[PageData[ExperienceItemSearchItem]](
        data=experience_service.search_items(
            db,
            user_id=current_user.id,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
    )
