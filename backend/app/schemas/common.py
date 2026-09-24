"""通用传输模型：统一响应体与分页（接口文档 1.2 / 1.1 分页规范）。"""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应体：全部 REST 接口（SSE 除外）共用。"""

    code: int = Field(default=0, description="业务码，0=成功，非 0 见错误码表")
    message: str = Field(default="ok", description="提示信息")
    data: T | None = Field(default=None, description="业务数据，无数据时为 null")


class PageData(BaseModel, Generic[T]):
    """分页数据：列表类接口 data 的统一形态。"""

    total: int = Field(description="符合条件的总条数")
    items: list[T] = Field(default_factory=list, description="当前页数据列表")


class HealthData(BaseModel):
    """健康检查响应数据。"""

    status: str = Field(description="服务状态，正常为 ok")
    llm_configured: bool = Field(description="是否已配置 AI 密钥（供前端提示未配置 AI）")
