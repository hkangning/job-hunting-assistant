"""订阅规则接口：校招情报订阅的增删改查（FR-022，接口文档 3.16）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.campus import SubscriptionCreateRequest, SubscriptionDTO, SubscriptionUpdateRequest
from app.schemas.common import ApiResponse
from app.services import campus_service

router = APIRouter(tags=["校招情报"])


@router.get("/subscriptions", response_model=ApiResponse[list[SubscriptionDTO]], summary="订阅规则列表")
def list_subscriptions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[list[SubscriptionDTO]]:
    """本账号订阅规则清单（按创建顺序）；数组类字段直接返回数组。"""
    data = campus_service.list_subscriptions(db, current_user.id)
    return ApiResponse[list[SubscriptionDTO]](data=data)


@router.post("/subscriptions", response_model=ApiResponse[SubscriptionDTO], summary="新增订阅规则")
def create_subscription(
    payload: SubscriptionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[SubscriptionDTO]:
    """新增订阅规则：name 必填；四个维度均可留空（留空 = 该维度不限）；
    匹配语义 = 维度间 AND、维度内 OR，命中公共信息后写 INFO_MATCH 提醒。"""
    data = campus_service.create_subscription(db, current_user.id, payload)
    return ApiResponse[SubscriptionDTO](data=data)


@router.put("/subscriptions/{subscription_id}", response_model=ApiResponse[SubscriptionDTO], summary="更新订阅规则")
def update_subscription(
    subscription_id: int,
    payload: SubscriptionUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[SubscriptionDTO]:
    """部分更新订阅规则：未传字段保持原值，传空数组 = 清空该维度；不存在或非本账号 → 10002。"""
    data = campus_service.update_subscription(db, current_user.id, subscription_id, payload)
    return ApiResponse[SubscriptionDTO](data=data)


@router.delete("/subscriptions/{subscription_id}", response_model=ApiResponse[None], summary="删除订阅规则")
def delete_subscription(
    subscription_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[None]:
    """删除订阅规则（已生成的提醒保留）；不存在或非本账号 → 10002。"""
    campus_service.delete_subscription(db, current_user.id, subscription_id)
    return ApiResponse[None]()
