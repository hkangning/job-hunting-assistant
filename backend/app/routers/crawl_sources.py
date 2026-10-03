"""校招信息源接口：源清单 CRUD 与手动触发采集（FR-021，接口文档 3.16）。

信息源为公共数据（全站共享、不按账号隔离）；执行逻辑全在 `services/campus_service`。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.campus import (
    CrawlRunData,
    CrawlRunRequest,
    CrawlSourceCreateRequest,
    CrawlSourceDTO,
    CrawlSourceUpdateRequest,
)
from app.schemas.common import ApiResponse, PageData
from app.services import campus_service

router = APIRouter(tags=["校招情报"])


@router.get("/crawl-sources", response_model=ApiResponse[PageData[CrawlSourceDTO]], summary="源清单")
def list_crawl_sources(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[PageData[CrawlSourceDTO]]:
    """全部信息源（含上次抓取状态）；条目少不分页，`total` 与 `items` 长度一致。"""
    items = campus_service.list_sources(db)
    return ApiResponse[PageData[CrawlSourceDTO]](data=PageData[CrawlSourceDTO](total=len(items), items=items))


@router.post("/crawl-sources", response_model=ApiResponse[CrawlSourceDTO], summary="新增源")
def create_crawl_source(
    payload: CrawlSourceCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[CrawlSourceDTO]:
    """新增一所学校的一个就业网站系统配置；同一系统 + 同一域名重复登记 → 10003。"""
    return ApiResponse[CrawlSourceDTO](data=campus_service.create_source(db, payload))


@router.put("/crawl-sources/{source_id}", response_model=ApiResponse[CrawlSourceDTO], summary="修改源")
def update_crawl_source(
    source_id: int,
    payload: CrawlSourceUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[CrawlSourceDTO]:
    """部分更新学校名 / 域名 / 参数 / 启用开关；改系统类型不支持 → 10001（需删除后重建）。"""
    return ApiResponse[CrawlSourceDTO](data=campus_service.update_source(db, source_id, payload))


@router.delete("/crawl-sources/{source_id}", response_model=ApiResponse[None], summary="删除源")
def delete_crawl_source(
    source_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[None]:
    """删除源配置；**已抓到的条目保留**（不连带删除）。不存在 → 404 + 10002。"""
    campus_service.delete_source(db, source_id)
    return ApiResponse[None](data=None)


@router.post("/crawl-sources/run", response_model=ApiResponse[CrawlRunData], summary="手动触发采集")
def run_crawl_sources(
    payload: CrawlRunRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[CrawlRunData]:
    """手动触发采集（演示 / 调试用）：逐源独立隔离，单源失败不整体报错（200 + 逐源 details）；
    指定 source_id 且该源失败 → 502 + 70002；任务执行中再次触发 → 10001。"""
    source_id = payload.source_id if payload is not None else None
    return ApiResponse[CrawlRunData](data=campus_service.run_crawl(db, source_id=source_id))
