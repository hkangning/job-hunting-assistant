"""投递管理接口：CRUD/状态流转/批量导入/模板下载/趋势统计（接口文档 3.3）。

路由层只做协议转换（系统设计 3.1）：参数校验、调服务层、包统一响应体，不直接访问 ORM。
"""

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import ApplicationStatus, CloseReason
from app.schemas.application import (
    ApplicationCreate,
    ApplicationDTO,
    ApplicationListItem,
    ApplicationStatusUpdate,
    ImportResult,
    TrendData,
)
from app.schemas.common import ApiResponse, PageData
from app.services import application_service

router = APIRouter(prefix="/applications", tags=["投递"])

TEMPLATE_FILENAME = "application_import_template.xlsx"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# 固定路径端点必须注册在 /{application_id} 之前，否则会被路径参数匹配
@router.get("/template", summary="下载导入模板")
def download_template() -> Response:
    """返回 xlsx 模板文件流（文件下载不走统一响应体）。"""
    return Response(
        content=application_service.build_import_template(),
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{TEMPLATE_FILENAME}"'},
    )


@router.get("/trend", response_model=ApiResponse[TrendData], summary="投递趋势统计")
def trend(
    days: int = Query(30, ge=1, le=90, description="统计最近 N 天，默认 30，最大 90"),
    db: Session = Depends(get_db),
) -> ApiResponse[TrendData]:
    """按投递日期统计每日投递数量（含无投递的 0 值日期）。"""
    return ApiResponse[TrendData](data=application_service.trend(db, days))


@router.post("/import", response_model=ApiResponse[ImportResult], summary="批量导入（Excel/CSV）")
async def import_applications(
    file: UploadFile = File(..., description=".xlsx 或 .csv 文件，≤2MB，表头见模板接口"),
    db: Session = Depends(get_db),
) -> ApiResponse[ImportResult]:
    """解析上传清单入库：行级校验互不影响；全部行非法返回错误码 20002 并携带行级清单。"""
    content = await file.read()
    result = application_service.import_from_file(db, file.filename or "", content)
    return ApiResponse[ImportResult](data=result)


@router.get("", response_model=ApiResponse[PageData[ApplicationListItem]], summary="投递列表（筛选+分页）")
def list_applications(
    status: ApplicationStatus | None = Query(None, description="状态过滤（枚举值）"),
    close_reason: CloseReason | None = Query(None, description="结束原因过滤（枚举值，仅对已结束的记录有意义）"),
    city: str | None = Query(None, description="城市（精确匹配）"),
    company: str | None = Query(None, description="公司关键字（模糊匹配）"),
    page: int = Query(1, ge=1, description="页码，从 1 起"),
    page_size: int = Query(10, ge=1, le=50, description="每页条数，默认 10，最大 50"),
    db: Session = Depends(get_db),
) -> ApiResponse[PageData[ApplicationListItem]]:
    """投递列表：按投递日期倒序，列表项不含备注（接口文档 3.3）。"""
    data = application_service.list_applications(
        db,
        status=status,
        close_reason=close_reason,
        city=city,
        company=company,
        page=page,
        page_size=page_size,
    )
    return ApiResponse[PageData[ApplicationListItem]](data=data)


@router.post("", response_model=ApiResponse[ApplicationDTO], summary="新增投递")
def create_application(
    payload: ApplicationCreate,
    db: Session = Depends(get_db),
) -> ApiResponse[ApplicationDTO]:
    """新增投递记录，返回含 id 的完整 DTO。"""
    return ApiResponse[ApplicationDTO](data=application_service.create_application(db, payload))


@router.get("/{application_id}", response_model=ApiResponse[ApplicationDTO], summary="投递详情")
def get_application(
    application_id: int,
    db: Session = Depends(get_db),
) -> ApiResponse[ApplicationDTO]:
    """投递详情（含备注全文）；不存在返回 10002。"""
    return ApiResponse[ApplicationDTO](data=application_service.get_application(db, application_id))


@router.put("/{application_id}", response_model=ApiResponse[ApplicationDTO], summary="编辑投递")
def update_application(
    application_id: int,
    payload: ApplicationCreate,
    db: Session = Depends(get_db),
) -> ApiResponse[ApplicationDTO]:
    """全量更新投递记录（请求体同新增）；状态变更走状态流转接口。"""
    return ApiResponse[ApplicationDTO](
        data=application_service.update_application(db, application_id, payload)
    )


@router.delete("/{application_id}", response_model=ApiResponse[None], summary="删除投递")
def delete_application(application_id: int, db: Session = Depends(get_db)) -> ApiResponse[None]:
    """物理删除投递记录；不存在返回 10002。"""
    application_service.delete_application(db, application_id)
    return ApiResponse[None]()


@router.patch("/{application_id}/status", response_model=ApiResponse[ApplicationDTO], summary="状态流转")
def change_status(
    application_id: int,
    payload: ApplicationStatusUpdate,
    db: Session = Depends(get_db),
) -> ApiResponse[ApplicationDTO]:
    """按状态机流转进度状态，非法流转返回 10001。"""
    return ApiResponse[ApplicationDTO](
        data=application_service.change_status(db, application_id, payload)
    )
