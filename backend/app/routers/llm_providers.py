"""AI 供应商配置接口：列表 / 保存 / 删除 / 激活 / 模型列表 / 连通性测试（接口文档 3.3）。

全部按登录账号隔离；Key 只以密文落库，接口仅回 `key_set` 布尔。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.common import ApiResponse
from app.schemas.llm_provider import (
    ActiveProviderDTO,
    ModelListDTO,
    ProviderItemDTO,
    ProviderListDTO,
    ProviderSaveRequest,
    ProviderTestDTO,
    ProviderTestRequest,
)
from app.services import llm_provider_service

router = APIRouter(prefix="/llm-providers", tags=["AI 供应商配置"])


@router.get("", response_model=ApiResponse[ProviderListDTO], summary="供应商列表")
def list_providers(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ApiResponse[ProviderListDTO]:
    """返回注册表全部 12 项（未配置的也在列表中）与当前账号的配置状态。"""
    return ApiResponse[ProviderListDTO](data=llm_provider_service.list_providers(db, current_user.id))


@router.put("/{provider}", response_model=ApiResponse[ProviderItemDTO], summary="保存供应商配置")
def save_provider(
    provider: str,
    payload: ProviderSaveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[ProviderItemDTO]:
    """保存（重复保存走更新）；保存**不改变**当前激活项，但账号尚无激活项时本次保存的自动生效。"""
    return ApiResponse[ProviderItemDTO](
        data=llm_provider_service.save_provider(db, current_user.id, provider, payload)
    )


@router.delete("/{provider}", response_model=ApiResponse[None], summary="删除供应商配置")
def delete_provider(
    provider: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[None]:
    """删除该供应商的全部配置（Key / 端点 / 模型 / 模型缓存）；删除当前激活项后 AI 进入未配置态。"""
    llm_provider_service.delete_provider(db, current_user.id, provider)
    return ApiResponse[None]()


@router.post("/{provider}/activate", response_model=ApiResponse[ActiveProviderDTO], summary="设为当前使用")
def activate_provider(
    provider: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[ActiveProviderDTO]:
    """把该供应商置为当前生效（同一事务内取消其他行激活位），切换后立即生效、无需重填 Key。"""
    return ApiResponse[ActiveProviderDTO](
        data=llm_provider_service.activate_provider(db, current_user.id, provider)
    )


@router.get("/{provider}/models", response_model=ApiResponse[ModelListDTO], summary="模型列表")
def list_models(
    provider: str,
    refresh: bool = Query(default=False, description="true = 强制重拉（默认走 24h 缓存）"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[ModelListDTO]:
    """实时拉取供应商可用模型；拉取失败回退内置模型表（`source=builtin`，不报错）。"""
    return ApiResponse[ModelListDTO](
        data=llm_provider_service.get_models(db, current_user.id, provider, refresh)
    )


@router.post("/test", response_model=ApiResponse[ProviderTestDTO], summary="连通性测试")
def test_provider(
    payload: ProviderTestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[ProviderTestDTO]:
    """向供应商发一条最小消息验证连通性；**不落库、不保存配置**；失败返回 10013 + 具体原因。"""
    return ApiResponse[ProviderTestDTO](data=llm_provider_service.test_provider(db, current_user.id, payload))
