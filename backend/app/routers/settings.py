"""设置接口：账号级偏好 + 系统级抓取配置（接口文档 3.12）。

LLM 供应商相关字段已全部迁出至 `/llm-providers`（步骤 6 瘦身）。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.common import ApiResponse
from app.schemas.system import SettingsDTO, SettingsUpdateRequest
from app.services import settings_service

router = APIRouter(prefix="/settings", tags=["画像与设置"])


@router.get("", response_model=ApiResponse[SettingsDTO], summary="获取设置")
def get_settings(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ApiResponse[SettingsDTO]:
    """取当前账号偏好（账号级）与就业网抓取配置（系统级，全局共用）。"""
    return ApiResponse[SettingsDTO](data=settings_service.get_settings(db, current_user.id))


@router.put("", response_model=ApiResponse[SettingsDTO], summary="更新设置")
def update_settings(
    payload: SettingsUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[SettingsDTO]:
    """只更新请求体中显式传入的字段；讯飞凭据传值则加密覆盖、传空串不修改。"""
    return ApiResponse[SettingsDTO](
        data=settings_service.update_settings(db, current_user.id, payload)
    )
