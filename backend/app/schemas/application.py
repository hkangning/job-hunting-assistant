"""投递模块传输模型：请求 DTO、响应 DTO、导入结果与趋势（接口文档 3.3；表结构见数据库设计 3.1）。"""

from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_serializer

from app.models.enums import ApplicationStatus, CloseReason
from app.utils.datetime_utils import format_datetime

# TrendItem 的字段名 date 与类型名 datetime.date 同名，会触发 Pydantic 注解解析冲突，故用别名
DateOnly = date

# 公司/岗位名：必填、去首尾空格、1~100 字（数据库设计 3.1：VARCHAR(100) 非空）
RequiredName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class ApplicationCreate(BaseModel):
    """新增/编辑投递请求体（POST /applications、PUT /applications/{id}）。"""

    company: RequiredName = Field(description="公司名称，必填，≤100 字")
    position: RequiredName = Field(description="岗位名称，必填，≤100 字")
    city: str | None = Field(default=None, max_length=50, description="工作城市，≤50 字")
    expected_salary: str | None = Field(
        default=None, max_length=50, description="期望/沟通薪资，自由文本（如 13k*14），≤50 字"
    )
    applied_at: date | None = Field(default=None, description="投递日期 YYYY-MM-DD，不传默认当天")
    channel: str | None = Field(default=None, max_length=50, description="投递渠道（官网/BOSS/内推等），≤50 字")
    status: ApplicationStatus | None = Field(
        default=None,
        description="进度状态，不传默认 APPLIED；取值 APPLIED（已投递）/WRITTEN（待笔试）/INTERVIEW（面试中）/OFFER（已获 offer）/CLOSED（已结束）",
    )
    close_reason: CloseReason | None = Field(
        default=None,
        description="结束原因，取值 FAILED（未通过）/DECLINED（主动放弃）/EXPIRED（无消息）；仅记录处于 CLOSED 时可改，其余状态下传该字段返回 10001",
    )
    next_event_at: datetime | None = Field(default=None, description="下次笔试/面试时间 YYYY-MM-DD HH:mm:ss")
    remark: str | None = Field(default=None, description="备注，不限长度")


class ApplicationStatusUpdate(BaseModel):
    """状态流转请求体（PATCH /applications/{id}/status）。"""

    status: ApplicationStatus = Field(
        description="目标状态；合法流转见 SRS FR-004 状态机：已投递→待笔试→面试中→已获 offer，除已结束外任意状态均可流转至已结束（不可回退）"
    )
    close_reason: CloseReason | None = Field(
        default=None,
        description="结束原因，取值 FAILED（未通过）/DECLINED（主动放弃）/EXPIRED（无消息）；status=CLOSED 时必填（缺失返回 10001），转其他状态时忽略并清空",
    )
    event_at: datetime | None = Field(
        default=None, description="转为 WRITTEN/INTERVIEW 时可同时更新下次笔试/面试时间 YYYY-MM-DD HH:mm:ss"
    )
    remark: str | None = Field(default=None, description="流转备注，追加到投递备注中")


class ApplicationDTO(BaseModel):
    """投递记录 DTO（创建/详情/编辑/状态流转响应通用）。"""

    id: int = Field(description="投递记录 id")
    company: str = Field(description="公司名称")
    position: str = Field(description="岗位名称")
    city: str | None = Field(description="工作城市，未填为 null")
    expected_salary: str | None = Field(description="期望/沟通薪资，未填为 null")
    applied_at: date = Field(description="投递日期 YYYY-MM-DD")
    channel: str | None = Field(description="投递渠道，未填为 null")
    status: ApplicationStatus = Field(
        description="进度状态：APPLIED（已投递）/WRITTEN（待笔试）/INTERVIEW（面试中）/OFFER（已获 offer）/CLOSED（已结束）"
    )
    close_reason: CloseReason | None = Field(description="结束原因，仅 status=CLOSED 时有值，其余状态恒为 null")
    next_event_at: datetime | None = Field(description="下次笔试/面试时间，未填为 null")
    remark: str | None = Field(description="备注，未填为 null")
    created_at: datetime = Field(description="创建时间 YYYY-MM-DD HH:mm:ss")
    updated_at: datetime = Field(description="更新时间 YYYY-MM-DD HH:mm:ss")

    @field_serializer("next_event_at", "created_at", "updated_at")
    def _serialize_datetime(self, value: datetime | None) -> str | None:
        """时间字段按接口口径输出 `YYYY-MM-DD HH:mm:ss`（Pydantic 默认 ISO 带 T，不符合约定）。"""
        return format_datetime(value)


class ApplicationListItem(ApplicationDTO):
    """投递列表项 DTO：字段与详情一致但不含 remark（接口文档 3.3：列表精简）。"""

    remark: str | None = Field(default=None, exclude=True, description="列表接口不返回备注，恒为 null")


class ImportErrorItem(BaseModel):
    """批量导入的非法行条目（响应 errors 数组元素）。"""

    row: int = Field(description="文件中的行号（第 1 行为表头，首条数据为第 2 行）")
    reason: str = Field(description="该行非法原因")


class ImportResult(BaseModel):
    """批量导入结果（POST /applications/import 响应 data）。"""

    success_count: int = Field(description="成功导入条数")
    errors: list[ImportErrorItem] = Field(
        default_factory=list, description="非法行清单；行级校验相互独立，非法行不阻塞其余行入库"
    )


class TrendItem(BaseModel):
    """投递趋势的单日计数。"""

    date: DateOnly = Field(description="日期 YYYY-MM-DD")
    count: int = Field(description="该日投递数量")


class TrendData(BaseModel):
    """投递趋势响应数据（GET /applications/trend 响应 data）。"""

    items: list[TrendItem] = Field(default_factory=list, description="按日期升序的计数序列，无投递的日期 count=0")
