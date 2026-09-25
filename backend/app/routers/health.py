"""健康检查接口（接口文档 3.1）。"""

from fastapi import APIRouter

from app.schemas.common import ApiResponse, HealthData

router = APIRouter(tags=["通用"])


@router.get("/health", response_model=ApiResponse[HealthData], summary="健康检查（免鉴权）")
def health() -> ApiResponse[HealthData]:
    """服务状态；**免鉴权且不含任何账号信息**——"是否已配置 AI"由 `GET /auth/me` 返回（接口文档 3.1）。"""
    return ApiResponse[HealthData](data=HealthData(status="ok"))
