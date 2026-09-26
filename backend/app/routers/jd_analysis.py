"""JD 匹配分析接口：报告列表与详情（接口文档 3.6）。

流式生成端点不在此处——它属 SSE 链路，统一收在 `routers/stream.py`（`POST /stream/jd-analysis`）。

路由层只做协议转换（系统设计 3.1）：参数校验、调服务层、包统一响应体，不直接访问 ORM。
数据归属一律取自登录态（current_user.id），请求参数中的 user_id 不接受、传入亦忽略。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.application import JdReportDTO, JdReportListItem
from app.schemas.common import ApiResponse, PageData
from app.services import jd_service

router = APIRouter(prefix="/jd-reports", tags=["JD 分析"])


@router.get("", response_model=ApiResponse[PageData[JdReportListItem]], summary="JD 分析报告列表")
def list_reports(
    application_id: int | None = Query(None, description="按关联的投递记录筛选"),
    page: int = Query(1, ge=1, description="页码，从 1 起"),
    page_size: int = Query(10, ge=1, le=50, description="每页条数，默认 10，最大 50"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[PageData[JdReportListItem]]:
    """当前账号的报告列表：按生成时间倒序，含关联投递的公司名（联表）。"""
    data = jd_service.list_reports(
        db, user_id=current_user.id, application_id=application_id, page=page, page_size=page_size
    )
    return ApiResponse[PageData[JdReportListItem]](data=data)


@router.get("/{report_id}", response_model=ApiResponse[JdReportDTO], summary="JD 分析报告详情")
def get_report(
    report_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[JdReportDTO]:
    """报告详情（JD 原文 + 报告全文）：不存在或不属于当前账号返回 10002。"""
    return ApiResponse[JdReportDTO](data=jd_service.get_report(db, current_user.id, report_id))
