"""今日概览接口：首页所需的投递统计与提醒一次聚合返回（接口文档 3.4）。

路由层只做协议转换（系统设计 3.1）：调服务层、包统一响应体，不直接访问 ORM。
数据归属取自登录态（current_user.id），请求参数不接受 user_id。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.common import ApiResponse
from app.schemas.overview import OverviewData
from app.services import overview_service

router = APIRouter(tags=["概览"])


@router.get("/overview", response_model=ApiResponse[OverviewData], summary="今日概览聚合")
def get_overview(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[OverviewData]:
    """当前账号的今日概览：待面试/笔试、投递状态计数、3 天无进展跟进、错题到期数与个人中心计数。"""
    return ApiResponse[OverviewData](data=overview_service.build_overview(db, current_user.id))
