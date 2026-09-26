"""AI 供应商配置传输模型（接口文档 3.3；表结构见数据库设计 3.17）。"""

from pydantic import BaseModel, Field

BASE_URL_MAX = 200  # 与 llm_provider_config.base_url 字段长度一致
MODEL_MAX = 100  # 与 llm_provider_config.model 字段长度一致


class ProviderItemDTO(BaseModel):
    """单个供应商的配置卡片（GET /llm-providers 列表项、PUT 保存响应）。"""

    provider: str = Field(description="供应商标识（注册表 12 项之一）")
    name: str = Field(description="供应商展示名")
    group: str = Field(description="分组：国内 / 国外 / 聚合 / 本地 / 自定义")
    base_url: str = Field(description="生效端点（账号配置优先，空则回落到注册表默认值）")
    needs_key: bool = Field(description="该供应商是否需要 API Key（注册表静态属性；ollama 本地部署为 false）")
    key_set: bool = Field(description="该账号是否已存 Key（**永不回显明文或片段**；needs_key=false 时恒为 false）")
    model: str = Field(description="该账号所选模型（空串 = 用注册表默认模型）")
    is_active: bool = Field(description="是否当前生效供应商（每账号至多一项为 true）")


class ProviderListDTO(BaseModel):
    """供应商列表响应（GET /llm-providers）：含未配置项，供前端渲染全部卡片。"""

    active: str | None = Field(default=None, description="当前生效供应商标识，未配置任何供应商时为 null")
    providers: list[ProviderItemDTO] = Field(default_factory=list, description="注册表全部供应商")


class ProviderSaveRequest(BaseModel):
    """保存供应商配置请求体（PUT /llm-providers/{provider}）。"""

    api_key: str | None = Field(default=None, description="密钥；省略或留空 = 不修改已存 Key（首次配置必填，ollama 可空）")
    base_url: str | None = Field(
        default=None, max_length=BASE_URL_MAX, description="覆盖注册表默认端点；省略 = 不修改，传空串 = 恢复默认"
    )
    model: str | None = Field(default=None, max_length=MODEL_MAX, description="该供应商下所选模型 ID（候选见模型列表接口）")


class ActiveProviderDTO(BaseModel):
    """激活结果（POST /llm-providers/{provider}/activate）。"""

    active: str = Field(description="切换后的生效供应商标识")


class ModelItemDTO(BaseModel):
    """一个可选模型（GET /llm-providers/{provider}/models 列表项）。"""

    id: str = Field(description="模型 ID（调用时传给供应商的 model 参数）")
    display_name: str = Field(description="展示名（内置表有记载的用中文名，新模型以 ID 展示）")
    is_free: bool = Field(description="是否免费额度模型（按内置表判定；新模型默认非免费）")


class ModelListDTO(BaseModel):
    """模型列表响应（GET /llm-providers/{provider}/models）。"""

    models: list[ModelItemDTO] = Field(default_factory=list, description="可用模型列表")
    source: str = Field(description="数据来源：remote = 实时拉取 / builtin = 拉取失败回退内置表")
    fetched_at: str | None = Field(default=None, description="本次拉取时间 YYYY-MM-DD HH:mm:ss（builtin 为 null）")


class ProviderTestRequest(BaseModel):
    """连通性测试请求体（POST /llm-providers/test）：**不落库、不保存配置**。"""

    provider: str = Field(description="待测供应商标识（注册表 12 项之一）")
    api_key: str | None = Field(default=None, description="待测 Key；省略则用当前账号已存 Key")
    base_url: str | None = Field(default=None, max_length=BASE_URL_MAX, description="待测端点（custom 必填，其余可省略）")
    model: str | None = Field(default=None, max_length=MODEL_MAX, description="待测模型；省略用注册表默认模型")


class ProviderTestDTO(BaseModel):
    """连通性测试结果（成功时）。"""

    message: str = Field(description="固定为 ok")
    model: str = Field(description="实际生效的模型名（供应商可能把退役模型路由到替代模型）")
