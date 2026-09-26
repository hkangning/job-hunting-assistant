"""应用配置：从 .env / 环境变量加载，全部字段带默认值（缺 .env 也能启动）。"""

import secrets
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env 固定在 backend/ 下（不随启动时的工作目录变化），自动生成主密钥时也写回这一份
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


# 平台共享 Key 的环境变量前缀（.env 里写 SHARED_KEY_<供应商标识>，见系统设计 5.4）
SHARED_KEY_PREFIX = "shared_key_"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="allow",  # 共享 Key 走未声明变量（SHARED_KEY_<供应商>），见 shared_provider_keys
    )

    app_name: str = "个人求职助手"  # 应用名（OpenAPI 文档标题）
    debug: bool = True  # 调试模式（开发期开启）
    api_prefix: str = "/api/v1"  # 业务接口统一前缀（接口文档 1.1 Base URL）
    database_url: str = "mysql+pymysql://jobhunter@127.0.0.1:3306/job_hunter?charset=utf8mb4"  # MySQL 连接串（库需先手工创建，见数据库设计文档 §7）；密码涉密不写进代码，真实值在 .env 的 DATABASE_URL
    cors_origins: list[str] = ["http://localhost:5173"]  # 允许跨域的前端地址（Vite 开发端口）
    app_secret_key: str = ""  # JWT 签名 + Fernet 加密主密钥；为空时启动自动生成（见下）

    llm_provider: str = "deepseek"  # LLM 供应商 key（注册表见系统设计 5.4）
    llm_model: str = "deepseek-flash"  # 默认模型 ID
    llm_api_key: str = ""  # 环境变量兜底 Key（设置页配置优先）
    llm_base_url: str = ""  # 仅 custom 供应商填写
    llm_trust_env: bool = False  # AI 出网是否沿用系统代理；默认 false = 直连（系统代理多为代理软件遗留，工具没开时会直接连不通）

    def shared_provider_keys(self) -> dict[str, str]:
        """平台共享 Key（免费模型的 Key 来源）：`SHARED_KEY_<供应商标识>` → Key 明文。

        变量名大小写不敏感、值留空视为未配置（便于先占位后填值）；结果由启动同步写进
        `user_id=0` 的平台配置行（见 database._sync_shared_providers）。
        """
        result: dict[str, str] = {}
        for name, value in (self.model_extra or {}).items():
            key = str(name).lower()
            if not key.startswith(SHARED_KEY_PREFIX) or not isinstance(value, str):
                continue
            provider = key[len(SHARED_KEY_PREFIX) :]
            if provider and value.strip():
                result[provider] = value.strip()
        return result


def _ensure_secret_key(config: Settings) -> None:
    """主密钥缺失时生成随机值并写回 .env（系统设计 3.5）。

    不写回的话每次重启都会换一把新密钥，已签发的 Token 全失效、加密的 Key 也解不开。
    """
    if config.app_secret_key:
        return
    config.app_secret_key = secrets.token_urlsafe(48)
    line = f"APP_SECRET_KEY={config.app_secret_key}\n"
    if ENV_FILE.exists():
        content = ENV_FILE.read_text(encoding="utf-8")
        if "APP_SECRET_KEY" in content:
            return  # .env 里已有该键但值为空：尊重用户配置，仅本次运行用随机值
        ENV_FILE.write_text(content.rstrip("\n") + "\n" + line, encoding="utf-8")
    else:
        ENV_FILE.write_text(line, encoding="utf-8")


settings = Settings()
_ensure_secret_key(settings)
