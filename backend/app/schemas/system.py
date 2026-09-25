"""画像传输模型（接口文档 3.12；表结构见数据库设计 3.15）。"""

from datetime import datetime

from pydantic import BaseModel, Field, field_serializer

from app.utils.datetime_utils import format_datetime


class ProfileDTO(BaseModel):
    """用户画像 DTO（GET /profile、PUT /profile 响应 data）；每账号一份，按登录态隔离。"""

    name: str | None = Field(description="姓名")
    school: str | None = Field(description="学校")
    major: str | None = Field(description="专业")
    degree: str | None = Field(description="学历（本科/硕士）")
    gpa: str | None = Field(description="GPA 文本")
    english_level: str | None = Field(description="英语水平（如 CET-6 441）")
    resume_text: str | None = Field(description="简历全文（JD 分析核心输入）")
    target_position: str | None = Field(description="目标岗位")
    target_city: str | None = Field(description="目标城市")
    skills: str | None = Field(description="技能栈标签，逗号分隔")
    weaknesses: str | None = Field(description="弱项标签，逗号分隔")
    note: str | None = Field(description="备注")
    updated_at: datetime = Field(description="更新时间 YYYY-MM-DD HH:mm:ss")

    @field_serializer("updated_at")
    def _serialize_updated_at(self, value: datetime) -> str | None:
        """时间字段按接口口径输出 `YYYY-MM-DD HH:mm:ss`（接口文档 1.1）。"""
        return format_datetime(value)


class ProfileUpdateRequest(BaseModel):
    """画像更新请求体（PUT /profile）：只提交需要变更的字段，未提交的保持原值（传 null 即清空）。"""

    name: str | None = Field(default=None, max_length=50, description="姓名，≤50 字")
    school: str | None = Field(default=None, max_length=100, description="学校，≤100 字")
    major: str | None = Field(default=None, max_length=100, description="专业，≤100 字")
    degree: str | None = Field(default=None, max_length=20, description="学历（本科/硕士），≤20 字")
    gpa: str | None = Field(default=None, max_length=20, description="GPA 文本（如 3.20/4.00），≤20 字")
    english_level: str | None = Field(default=None, max_length=50, description="英语水平（如 CET-6 441），≤50 字")
    resume_text: str | None = Field(default=None, description="简历全文，不限长度（JD 分析核心输入）")
    target_position: str | None = Field(default=None, max_length=100, description="目标岗位，≤100 字")
    target_city: str | None = Field(default=None, max_length=50, description="目标城市，≤50 字")
    skills: str | None = Field(default=None, description="技能栈标签，逗号分隔")
    weaknesses: str | None = Field(default=None, description="弱项标签，逗号分隔")
    note: str | None = Field(default=None, description="备注，不限长度")
