"""健康检查接口（接口文档 3.1）。"""

from fastapi import APIRouter

from app.config import settings
from app.schemas.common import ApiResponse, HealthData

router = APIRouter(tags=["通用"])


@router.get("/health", response_model=ApiResponse[HealthData], summary="健康检查")
def health() -> ApiResponse[HealthData]:
    """服务状态 + AI 密钥是否已配置；当前仅看环境变量，设置页配置在步骤 7 接入。"""
    return ApiResponse[HealthData](
        data=HealthData(status="ok", llm_configured=bool(settings.llm_api_key))
    )
