"""画像接口：按账号隔离的读取与更新 + 简历文件解析（接口文档 3.12）。

设置（/settings）与供应商配置（/llm-providers）都在步骤 6 独立成文件，不在本文件。
"""

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.clients.llm_client import LLMClient, get_llm_client
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.common import ApiResponse
from app.schemas.system import ProfileDTO, ProfileUpdateRequest, ResumeParseData
from app.services import profile_service, resume_service

router = APIRouter(prefix="/profile", tags=["画像与设置"])


@router.get("", response_model=ApiResponse[ProfileDTO], summary="获取画像")
def get_profile(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ApiResponse[ProfileDTO]:
    """取当前登录账号的画像（每账号一份，请求体/查询参数不接受 user_id）。"""
    return ApiResponse[ProfileDTO](data=profile_service.get_profile(db, current_user.id))


@router.put("", response_model=ApiResponse[ProfileDTO], summary="更新画像")
def update_profile(
    payload: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[ProfileDTO]:
    """更新当前账号画像：只更新提交的字段，未提交的保持原值，显式传 null 即清空。"""
    values = payload.model_dump(exclude_unset=True)
    return ApiResponse[ProfileDTO](data=profile_service.update_profile(db, current_user.id, values))


@router.post("/resume", response_model=ApiResponse[ResumeParseData], summary="上传简历解析")
async def parse_resume(
    file: UploadFile = File(..., description="简历文件：.pdf / .docx，≤10MB"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    client: LLMClient = Depends(get_llm_client),
) -> ApiResponse[ResumeParseData]:
    """解析简历并抽取画像字段（**纯解析不落库**）：格式 / 体积 / 可解析性不符返回 10001。

    返回 `{extracted}`（含结构化经历条目）——用户核对修改后经 PUT /profile 保存；AI 未配 Key
    或抽取失败时 `extracted` 为 null（不报错，前端提示手填画像）。
    """
    content = await file.read()
    return ApiResponse[ResumeParseData](
        data=resume_service.parse_resume(
            db,
            user_id=current_user.id,
            filename=file.filename or "",
            content=content,
            client=client,
        )
    )
