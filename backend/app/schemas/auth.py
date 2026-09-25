"""账号与鉴权传输模型：注册/登录/账号信息/改资料/改密/头像（接口文档 3.2）。"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_serializer

from app.utils.datetime_utils import format_datetime

# 登录名：3~20 位字母/数字/下划线（接口文档 3.2）
Username = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=20, pattern=r"^[A-Za-z0-9_]+$")
]


class RegisterRequest(BaseModel):
    """注册请求体（POST /auth/register）。"""

    username: Username = Field(description="登录名，3~20 位字母/数字/下划线，全站唯一（不区分大小写）")
    password: str = Field(description="密码，≥6 位（不强制字符类型，不足返回 80006）")
    nickname: str | None = Field(default=None, max_length=50, description="昵称，默认取用户名，个人中心可改")
    email: str | None = Field(default=None, max_length=100, description="邮箱，填写时校验格式且全站唯一")


class LoginRequest(BaseModel):
    """登录请求体（POST /auth/login）。"""

    username: str = Field(description="登录名")
    password: str = Field(description="密码")
    remember_me: bool = Field(default=False, description="勾选「30 天免登录」传 true；默认 false，有效期 1 天")


class ProfileUpdateRequest(BaseModel):
    """账号资料修改请求体（PUT /auth/profile）；用户名不可修改。"""

    nickname: str | None = Field(default=None, max_length=50, description="昵称，不传保持原值，传空回退用户名")
    email: str | None = Field(
        default=None, max_length=100, description="邮箱，不传保持原值，传空串清空；格式非法返回 10001，重复返回 10003"
    )


class PasswordUpdateRequest(BaseModel):
    """修改密码请求体（PUT /auth/password）。"""

    old_password: str = Field(description="原密码，错误返回 80007")
    new_password: str = Field(description="新密码，≥6 位（不足返回 80006）")


class UserBrief(BaseModel):
    """账号简要信息（注册/登录响应中的 user 字段）。"""

    id: int = Field(description="账号 id")
    username: str = Field(description="登录名（只读，不可修改）")
    nickname: str | None = Field(description="昵称，未设置为 null")
    avatar: str | None = Field(description="头像相对路径，null = 使用默认头像")
    role: str = Field(description="角色：USER（普通）/ADMIN（管理员，首个注册账号自动获得）")
    plan: str = Field(description="套餐：FREE/PRO（预留字段，本期恒为 FREE）")
    created_at: datetime = Field(description="注册时间 YYYY-MM-DD HH:mm:ss")

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> str | None:
        """时间字段按接口口径输出 `YYYY-MM-DD HH:mm:ss`（接口文档 1.1）。"""
        return format_datetime(value)


class UserInfo(UserBrief):
    """当前账号完整信息（GET /auth/me、PUT /auth/profile 响应 data）。"""

    email: str | None = Field(description="邮箱，未设置为 null")
    last_login_at: datetime | None = Field(description="上次登录时间，注册后未再登录为 null")
    llm_configured: bool = Field(description="是否已有生效的 AI 供应商配置（false 时概览提示未配置 AI）")

    @field_serializer("last_login_at")
    def _serialize_last_login_at(self, value: datetime | None) -> str | None:
        return format_datetime(value)


class AuthData(BaseModel):
    """注册/登录成功响应 data（注册自动登录，有效期 1 天）。"""

    token: str = Field(description="JWT，后续请求头携带 Authorization: Bearer <token>")
    expires_at: datetime = Field(description="Token 过期时间 YYYY-MM-DD HH:mm:ss")
    user: UserBrief = Field(description="账号简要信息")

    @field_serializer("expires_at")
    def _serialize_expires_at(self, value: datetime) -> str | None:
        return format_datetime(value)


class AvatarData(BaseModel):
    """头像上传/恢复默认响应 data。"""

    avatar: str | None = Field(description="头像相对路径（如 uploads/avatars/1_a3f9c2d1.png），null = 已恢复默认头像")
