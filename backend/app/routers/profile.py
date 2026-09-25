"""画像接口：按账号隔离的读取与更新（接口文档 3.12）。

设置（/settings）与供应商配置（/llm-providers）分别属步骤 6，不在本文件。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.common import ApiResponse
from app.schemas.system import ProfileDTO, ProfileUpdateRequest
from app.services import profile_service

router = APIRouter(prefix="/profile", tags=["画像与设置"])


@router.get("", response_model=ApiResponse[ProfileDTO], summary="获取画像")
def get_profile(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ApiResponse[ProfileDTO]:
    """取当前登录账号的画像（每账号一份，请求体/查询参数不接受 user_id）。"""
    return ApiResponse[ProfileDTO](data=profile_service.get_profile(db, current_user.id))


@router.put("", response_model=ApiResponse[ProfileDTO], summary="更新画像")
def update_profile(
    payload: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[ProfileDTO]:
    """更新当前账号画像：只更新提交的字段，未提交的保持原值，显式传 null 即清空。"""
    values = payload.model_dump(exclude_unset=True)
    return ApiResponse[ProfileDTO](data=profile_service.update_profile(db, current_user.id, values))
