"""校招情报接口：宣讲会 / 双选会、岗位、投喂、日历（FR-021，接口文档 3.16）。"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.clients.llm_client import LLMClient, get_llm_client
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.campus import (
    CalendarEventItem,
    CampusEventItem,
    JobPostingCreateRequest,
    JobPostingIngestData,
    JobPostingIngestRequest,
    JobPostingItem,
)
from app.schemas.common import ApiResponse, PageData
from app.services import campus_service

router = APIRouter(tags=["校招情报"])


@router.get("/campus-events", response_model=ApiResponse[PageData[CampusEventItem]], summary="宣讲会/双选会列表")
def list_campus_events(
    info_type: str | None = Query(None, description="TALK 宣讲会 / FAIR 双选会；不传 = 全部"),
    city: str | None = Query(None, description="按地点文本模糊匹配（宣讲会地点多为校区，无独立城市字段）"),
    keyword: str | None = Query(None, description="标题 / 公司名模糊匹配"),
    source_site: str | None = Query(
        None, description="按来源学校名筛选（值同 `source_site` 下发口径，如「南京理工大学」）；含该校任一来源的条目命中，不传 = 全部"
    ),
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
        source_site=source_site,
        date_from=date_from,
        date_to=date_to,
        include_expired=include_expired,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    return ApiResponse[PageData[CampusEventItem]](data=data)


@router.get("/job-postings", response_model=ApiResponse[PageData[JobPostingItem]], summary="岗位列表")
def list_job_postings(
    city: str | None = Query(None, description="工作城市等值匹配"),
    company: str | None = Query(None, description="公司名模糊匹配"),
    job_type: str | None = Query(None, description="CAMPUS 校招 / INTERN 实习 / SOCIAL 社招；不传 = 全部"),
    keyword: str | None = Query(None, description="岗位名 / 公司名模糊匹配"),
    source_site: str | None = Query(
        None, description="按来源学校名筛选（值同 `source_site` 下发口径）；投喂岗位无来源不会被命中，不传 = 全部"
    ),
    status: str | None = Query(None, description="不传或 ACTIVE = 有效 + 已变更；CHANGED / EXPIRED 精确过滤"),
    sort: str = Query("time", description="time 按入库时间降序（默认）/ match 按画像匹配度降序"),
    page: int = Query(1, ge=1, description="页码，从 1 起"),
    page_size: int = Query(10, ge=1, le=50, description="每页条数，默认 10，最大 50"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[PageData[JobPostingItem]]:
    """岗位分页列表：结果 = 公共岗位（自动抓取）+ 本账号投喂；`is_applied` 按公司 + 岗位名比对投递记录；
    job_type / status / sort 非法值 → 10001。"""
    data = campus_service.list_job_postings(
        db,
        current_user.id,
        city=city,
        company=company,
        job_type=job_type,
        keyword=keyword,
        source_site=source_site,
        status=status,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    return ApiResponse[PageData[JobPostingItem]](data=data)


@router.post("/job-postings/ingest", response_model=ApiResponse[JobPostingIngestData], summary="投喂抽取预览")
def ingest_job_posting(
    payload: JobPostingIngestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    client: LLMClient = Depends(get_llm_client),
) -> ApiResponse[JobPostingIngestData]:
    """投喂一条招聘信息（JD 原文或链接）→ AI 抽取岗位字段 → 返回预览（**不入库**）。

    text 与 url 二选一（同传 / 均缺 → 10001）；链接抓取失败（登录墙 / 被拒 / 内网地址）与
    抽取不可解析 → 70003（message 区分两类原因），前端降级为手动填表；确认后调 POST /job-postings 入库。
    """
    data = campus_service.ingest_job_posting(db, current_user.id, payload, client=client)
    return ApiResponse[JobPostingIngestData](data=data)


@router.post("/job-postings", response_model=ApiResponse[JobPostingItem], summary="确认入库（投喂岗位）")
def create_job_posting(
    payload: JobPostingCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[JobPostingItem]:
    """确认入库：title / company 必填（服务端去空白后校验）；同账号同指纹重复投喂 → 覆盖更新不报错；
    入库归属当前账号（ingest_source=FEED），其他账号不可见。"""
    data = campus_service.create_job_posting(db, current_user.id, payload)
    return ApiResponse[JobPostingItem](data=data)


@router.delete("/job-postings/{posting_id}", response_model=ApiResponse[None], summary="删除投喂岗位")
def delete_job_posting(
    posting_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[None]:
    """删除本账号投喂的岗位；自动抓取的公共岗位不可删除（10001）；不存在或非本账号 → 10002。"""
    campus_service.delete_job_posting(db, current_user.id, posting_id)
    return ApiResponse[None]()


@router.get("/calendar", response_model=ApiResponse[list[CalendarEventItem]], summary="日历事件聚合")
def list_calendar(
    start: date = Query(..., description="区间开始日期 YYYY-MM-DD"),
    end: date = Query(..., description="区间结束日期 YYYY-MM-DD（含当日）"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[list[CalendarEventItem]]:
    """日历四类事件聚合：宣讲会 / 双选会（区间内活动）+ 笔试 / 面试（投递记录安排的考试时间）；
    end 早于 start → 10001；区间内无事件返回空数组。"""
    data = campus_service.list_calendar(db, current_user.id, start=start, end=end)
    return ApiResponse[list[CalendarEventItem]](data=data)
