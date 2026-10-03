"""提醒接口：手动触发每日任务、提醒列表与标记已读（FR-013，接口文档 3.14）。

路由层只做协议转换（系统设计 3.1）：数据归属取自登录态，请求参数不接受 user_id；
每日任务的实际生成逻辑全在 `services/reminder_engine`（定时任务与手动触发共用同一入口）。
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clients.llm_client import LLMClient, get_llm_client
from app.database import get_db
from app.deps import get_current_user
from app.exceptions import BizException, ErrorCode
from app.models import Reminder, User
from app.models.enums import ReminderType
from app.schemas.common import ApiResponse, PageData
from app.schemas.system import ReminderDTO, ReminderRunData
from app.services.reminder_engine import run_daily

router = APIRouter(tags=["提醒"])


@router.post("/reminders/run", response_model=ApiResponse[ReminderRunData], summary="立即执行每日提醒任务")
def run_reminders(client: LLMClient = Depends(get_llm_client)) -> ApiResponse[ReminderRunData]:
    """遍历全部账号判定并生成今日提醒（手动触发入口，开发 / 演示用；定时任务同走 `run_daily`）。"""
    generated = run_daily(client_getter=lambda: client)
    return ApiResponse[ReminderRunData](data=ReminderRunData(generated=generated))


@router.get("/reminders", response_model=ApiResponse[PageData[ReminderDTO]], summary="提醒列表")
def list_reminders(
    remind_date: date | None = Query(
        None, alias="date", description="只看 remind_date 恰好该日的提醒（YYYY-MM-DD），不传返回全部日期"
    ),
    checked: bool | None = Query(None, description="按已读状态过滤：false 只看未读 / true 只看已读，不传不过滤"),
    page: int = Query(1, ge=1, description="页码，从 1 起"),
    page_size: int = Query(10, ge=1, le=50, description="每页条数，默认 10，最大 50"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[PageData[ReminderDTO]]:
    """当前账号的提醒分页列表，按提醒日期 / id 倒序。"""
    conditions = [Reminder.user_id == current_user.id]
    if remind_date is not None:
        conditions.append(Reminder.remind_date == remind_date)
    if checked is not None:
        conditions.append(Reminder.checked == int(checked))
    total = db.execute(select(func.count()).select_from(Reminder).where(*conditions)).scalar_one()
    rows = (
        db.execute(
            select(Reminder)
            .where(*conditions)
            .order_by(Reminder.remind_date.desc(), Reminder.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    items = [
        ReminderDTO(
            id=row.id,
            reminder_type=ReminderType(row.reminder_type),
            ref_id=row.ref_id,
            ref_type=row.ref_type,
            content=row.content,
            remind_date=row.remind_date,
            checked=bool(row.checked),
        )
        for row in rows
    ]
    return ApiResponse[PageData[ReminderDTO]](data=PageData[ReminderDTO](total=total, items=items))


@router.put("/reminders/{reminder_id}/check", response_model=ApiResponse[None], summary="标记提醒已读")
def check_reminder(
    reminder_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[None]:
    """把提醒标为已读（重复标记不报错）；不存在或跨账号一律 404 + 10002（不可区分）。"""
    row = db.scalar(
        select(Reminder).where(Reminder.id == reminder_id, Reminder.user_id == current_user.id)
    )
    if row is None:
        raise BizException(ErrorCode.NOT_FOUND)
    if not row.checked:
        row.checked = 1
        db.commit()
    return ApiResponse[None](data=None)
