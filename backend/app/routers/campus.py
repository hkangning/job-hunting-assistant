"""校招情报接口：宣讲会 / 双选会列表（FR-021，接口文档 3.16）。"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.campus import CampusEventItem
from app.schemas.common import ApiResponse, PageData
from app.services import campus_service

router = APIRouter(tags=["校招情报"])


@router.get("/campus-events", response_model=ApiResponse[PageData[CampusEventItem]], summary="宣讲会/双选会列表")
def list_campus_events(
    info_type: str | None = Query(None, description="TALK 宣讲会 / FAIR 双选会；不传 = 全部"),
    city: str | None = Query(None, description="按地点文本模糊匹配（宣讲会地点多为校区，无独立城市字段）"),
    keyword: str | None = Query(None, description="标题 / 公司名模糊匹配"),
    date_from: date | None = Query(None, description="活动日期下界（含）YYYY-MM-DD"),
    date_to: date | None = Query(None, description="活动日期上界（含）YYYY-MM-DD"),
    include_expired: bool = Query(False, description="默认 false 只返回未过期；true = 含 EXPIRED"),
    sort: str = Query("time", description="time 按活动时间升序（默认）/ match 按画像匹配度降序"),
    page: int = Query(1, ge=1, description="页码，从 1 起"),
    page_size: int = Query(10, ge=1, le=50, description="每页条数，默认 10，最大 50"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[PageData[CampusEventItem]]:
    """宣讲会 / 双选会分页列表：过滤 → 画像匹配打分 → 排序 → 分页；
    `source_site` 下发来源学校名（映射不到时回退站点标识）；type / sort 非法值 → 10001。"""
    data = campus_service.list_campus_events(
        db,
        current_user.id,
        info_type=info_type,
        city=city,
        keyword=keyword,
        date_from=date_from,
        date_to=date_to,
        include_expired=include_expired,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    return ApiResponse[PageData[CampusEventItem]](data=data)
