"""应用配置：从 .env / 环境变量加载，全部字段带默认值（缺 .env 也能启动）。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "个人求职助手"  # 应用名（OpenAPI 文档标题）
    debug: bool = True  # 调试模式（开发期开启）
    api_prefix: str = "/api/v1"  # 业务接口统一前缀（接口文档 1.1 Base URL）
    database_url: str = "sqlite:///./app.db"  # SQLite 单文件库
    cors_origins: list[str] = ["http://localhost:5173"]  # 允许跨域的前端地址（Vite 开发端口）

    llm_provider: str = "deepseek"  # LLM 供应商 key（注册表见系统设计 5.4）
    llm_model: str = "deepseek-flash"  # 默认模型 ID
    llm_api_key: str = ""  # 环境变量兜底 Key（设置页配置优先）
    llm_base_url: str = ""  # 仅 custom 供应商填写


settings = Settings()
