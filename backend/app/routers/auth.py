"""账号与鉴权接口：注册/登录/账号信息/改资料/改密码/头像（接口文档 3.2）。

路由层只做协议转换（系统设计 3.1）：参数校验、调服务层、包统一响应体，不直接访问 ORM。
"""

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas.auth import (
    AuthData,
    AvatarData,
    LoginRequest,
    PasswordUpdateRequest,
    ProfileUpdateRequest,
    RegisterRequest,
    UserInfo,
)
from app.schemas.common import ApiResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["账号与鉴权"])


@router.post("/register", response_model=ApiResponse[AuthData], summary="注册（免鉴权）")
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> ApiResponse[AuthData]:
    """注册并自动登录，返回 Token（有效期 1 天）；用户名重复 80003、密码不足 6 位 80006。"""
    return ApiResponse[AuthData](data=auth_service.register(db, payload))


@router.post("/login", response_model=ApiResponse[AuthData], summary="登录（免鉴权）")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> ApiResponse[AuthData]:
    """登录返回 Token（勾选免登录 30 天、未勾选 1 天）；密码错误 80004、锁定中 80005。"""
    return ApiResponse[AuthData](data=auth_service.login(db, payload))


@router.get("/me", response_model=ApiResponse[UserInfo], summary="当前账号信息")
def me(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ApiResponse[UserInfo]:
    """前端启动校验 Token 是否仍有效的入口（401 → 80001/80002 → 清本地 Token 跳登录页）。"""
    return ApiResponse[UserInfo](data=auth_service.get_account(db, current_user))


@router.put("/profile", response_model=ApiResponse[UserInfo], summary="修改账号资料")
def update_profile(
    payload: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[UserInfo]:
    """修改昵称/邮箱（用户名不可改）；邮箱重复返回 10003。"""
    return ApiResponse[UserInfo](data=auth_service.update_account(db, current_user, payload))


@router.put("/password", response_model=ApiResponse[None], summary="修改密码")
def change_password(
    payload: PasswordUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[None]:
    """修改密码：原密码错误 80007；成功后当前 Token 立即失效（含 30 天免登录的旧 Token）。"""
    auth_service.change_password(db, current_user, payload)
    return ApiResponse[None]()


@router.post("/avatar", response_model=ApiResponse[AvatarData], summary="上传头像")
async def upload_avatar(
    file: UploadFile = File(..., description="头像图片：jpg / jpeg / png / webp，≤2MB"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiResponse[AvatarData]:
    """上传并替换头像，返回新的相对路径；类型或体积不符返回 10001，成功后删除旧文件。"""
    content = await file.read()
    data = auth_service.upload_avatar(
        db, current_user, filename=file.filename or "", content=content
    )
    return ApiResponse[AvatarData](data=data)


@router.delete("/avatar", response_model=ApiResponse[AvatarData], summary="恢复默认头像")
def reset_avatar(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ApiResponse[AvatarData]:
    """删除自定义头像文件并把 avatar 置空（默认头像由前端按用户名生成，不占存储）。"""
    return ApiResponse[AvatarData](data=auth_service.reset_avatar(db, current_user))
