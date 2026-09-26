"""供应商注册表与探测：12 家供应商的两级（供应商 → 模型）注册表、模型列表动态拉取、连通性测试。

全部走 OpenAI 兼容协议（系统设计 5.4）：选供应商 = 定 base_url 与 Key，选模型 = 定 model，调用代码零改动。

本模块只承担「不产生对话内容」的探测类操作（拉模型列表、测连通性）；
对话能力（`stream_chat` / `chat_json` / 超时重试）在步骤 10 的 `llm_client` 中实现并复用本模块。
"""

from dataclasses import dataclass

import httpx
import openai
from openai import OpenAI

from app.config import settings

PROBE_TIMEOUT = 10.0  # 探测类请求超时（秒）；对话链路的超时策略在步骤 10 的 llm_client 单独定义
# 免 Key 供应商（本地 ollama）的占位值：该服务不校验 Key，但 OpenAI SDK 要求该参数非空
KEYLESS_PLACEHOLDER = "keyless"

GROUP_CN = "国内"
GROUP_OVERSEAS = "国外"
GROUP_AGGREGATE = "聚合"
GROUP_LOCAL = "本地"
GROUP_CUSTOM = "自定义"


@dataclass(frozen=True)
class ModelMeta:
    """一个可选模型：`display_name` 用于界面展示，内置表维护。"""

    id: str
    display_name: str


@dataclass(frozen=True)
class ProviderMeta:
    """注册表条目：供应商的静态元数据（不含账号配置，配置见 `llm_provider_config` 表）。"""

    key: str  # 标识（入库 llm_provider_config.provider）
    name: str  # 界面展示名
    group: str  # 分组：国内 / 国外 / 聚合 / 本地 / 自定义
    base_url: str  # 内置默认端点（账号配置有值则优先生效，应对端点变更）
    default_model: str | None  # 默认模型（空 = 由用户选择，如本地与自定义）
    builtin_models: tuple[ModelMeta, ...] = ()  # 内置模型表（离线回退 + 未配 Key 时的预览清单；运行时以动态拉取为准）
    needs_key: bool = True  # 是否需要 API Key（ollama 本地无需）


# 供应商注册表（系统设计 5.4）：新增供应商只加配置，不改业务代码
PROVIDERS: dict[str, ProviderMeta] = {
    "deepseek": ProviderMeta(
        key="deepseek",
        name="DeepSeek",
        group=GROUP_CN,
        base_url="https://api.deepseek.com",
        default_model="deepseek-flash",
        builtin_models=(
            ModelMeta("deepseek-flash", "DeepSeek V4.1 Flash"),
            ModelMeta("deepseek-v4-pro", "DeepSeek V4 Pro（退役路由中）"),
        ),
    ),
    "zhipu": ProviderMeta(
        key="zhipu",
        name="智谱 GLM",
        group=GROUP_CN,
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4.7-flash",
        builtin_models=(
            ModelMeta("glm-4.7-flash", "GLM-4.7 Flash"),
            ModelMeta("glm-4-flash", "GLM-4 Flash"),
        ),
    ),
    "kimi": ProviderMeta(
        key="kimi",
        name="Kimi",
        group=GROUP_CN,
        base_url="https://api.moonshot.cn/v1",
        default_model="kimi-k2.6",
        builtin_models=(
            ModelMeta("kimi-k2.6", "Kimi K2.6"),
            ModelMeta("kimi-k2.7-code", "Kimi K2.7 Code"),
            ModelMeta("kimi-k3", "Kimi K3"),
        ),
    ),
    "qwen": ProviderMeta(
        key="qwen",
        name="通义千问",
        group=GROUP_CN,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen3-plus",
        builtin_models=(
            ModelMeta("qwen3-max", "Qwen3 Max"),
            ModelMeta("qwen3-plus", "Qwen3 Plus"),
            ModelMeta("qwen3-turbo", "Qwen3 Turbo"),
        ),
    ),
    "doubao": ProviderMeta(
        key="doubao",
        name="豆包",
        group=GROUP_CN,
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        default_model="doubao-seed-1.6",
        builtin_models=(
            ModelMeta("doubao-seed-1.6", "豆包 Seed 1.6"),
            ModelMeta("doubao-1.5-pro", "豆包 1.5 Pro"),
        ),
    ),
    "openai": ProviderMeta(
        key="openai",
        name="OpenAI",
        group=GROUP_OVERSEAS,
        base_url="https://api.openai.com/v1",
        default_model="gpt-5-mini",
        builtin_models=(
            ModelMeta("gpt-5", "GPT-5"),
            ModelMeta("gpt-5-mini", "GPT-5 mini"),
            ModelMeta("gpt-4o", "GPT-4o"),
        ),
    ),
    "gemini": ProviderMeta(
        key="gemini",
        name="Gemini",
        group=GROUP_OVERSEAS,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-2.5-flash",
        builtin_models=(
            ModelMeta("gemini-2.5-pro", "Gemini 2.5 Pro"),
            ModelMeta("gemini-2.5-flash", "Gemini 2.5 Flash"),
        ),
    ),
    "claude": ProviderMeta(
        key="claude",
        name="Claude",
        group=GROUP_OVERSEAS,
        base_url="https://api.anthropic.com/v1/",
        default_model="claude-sonnet-5",
        builtin_models=(
            ModelMeta("claude-opus-5-5", "Claude Opus 5.5"),
            ModelMeta("claude-sonnet-5", "Claude Sonnet 5"),
            ModelMeta("claude-haiku-4-5-20251001", "Claude Haiku 4.5"),
        ),
    ),
    "grok": ProviderMeta(
        key="grok",
        name="Grok",
        group=GROUP_OVERSEAS,
        base_url="https://api.x.ai/v1",
        default_model="grok-4",
        builtin_models=(
            ModelMeta("grok-4", "Grok 4"),
            ModelMeta("grok-3", "Grok 3"),
        ),
    ),
    "openrouter": ProviderMeta(
        key="openrouter",
        name="OpenRouter",
        group=GROUP_AGGREGATE,
        base_url="https://openrouter.ai/api/v1",
        default_model=None,  # 聚合中转，模型由用户从拉取结果中选择
        # 聚合家模型池极大（随账号额度变化），内置表只列最常见的三家主流，实际以动态拉取为准
        builtin_models=(
            ModelMeta("openai/gpt-5", "GPT-5"),
            ModelMeta("anthropic/claude-sonnet-5", "Claude Sonnet 5"),
            ModelMeta("google/gemini-2.5-pro", "Gemini 2.5 Pro"),
        ),
    ),
    "ollama": ProviderMeta(
        key="ollama",
        name="Ollama（本地）",
        group=GROUP_LOCAL,
        base_url="http://localhost:11434/v1",
        default_model=None,  # 本地已拉取的模型各不相同，以实时拉取为准
        builtin_models=(),
        needs_key=False,
    ),
    "custom": ProviderMeta(
        key="custom",
        name="自定义",
        group=GROUP_CUSTOM,
        base_url="",  # 端点由用户填写（保存与测试时必填）
        default_model=None,
        builtin_models=(),
    ),
}

PROVIDER_KEYS = tuple(PROVIDERS)  # 注册表全部标识（顺序即界面展示顺序：供应商下拉）

# 内置模型表全局索引（模型 ID → 元数据）：远程拉取的模型据此补展示名，见 enrich_remote_model
_BUILTIN_INDEX: dict[str, ModelMeta] = {
    item.id: item for meta in PROVIDERS.values() for item in meta.builtin_models
}


class ProviderProbeError(Exception):
    """供应商探测失败（网络 / 鉴权 / 模型不存在等）；`message` 可直接展示给用户。"""


class ProviderAuthError(ProviderProbeError):
    """鉴权类探测失败（Key 无效 / 无权限）：模型列表场景需直接报 10013，**不回退内置表**。"""


def get_provider(key: str) -> ProviderMeta | None:
    """按标识取注册表条目；标识非法返回 None（调用方转 10001）。"""
    return PROVIDERS.get(key)


def resolve_base_url(meta: ProviderMeta, override: str | None) -> str:
    """端点取值：账号配置非空则优先生效（应对供应商端点变更），否则用注册表内置默认值。"""
    return (override or "").strip() or meta.base_url


def enrich_remote_model(model_id: str) -> ModelMeta:
    """把远程拉取到的模型 ID 补齐展示信息。

    模型 ID 全局唯一，故**跨供应商**查内置表——聚合 / 自定义 / 本地供应商自身内置表为空，
    但拉回来的可能正是某家已记载的模型（如经代理调用 glm-4.7-flash），展示名仍应准确。
    内置表未记载的新模型以 ID 原样展示。
    """
    return _BUILTIN_INDEX.get(model_id, ModelMeta(id=model_id, display_name=model_id))


def _build_client(meta: ProviderMeta, base_url: str, api_key: str | None) -> OpenAI:
    """构造 OpenAI 兼容客户端；免 Key 供应商（本地 ollama）用占位值满足 SDK 必填要求。

    代理行为与对话链路同口径（见 llm_client._http_client）：默认直连、不走系统代理。
    """
    key = (api_key or "").strip() or (KEYLESS_PLACEHOLDER if not meta.needs_key else "")
    return OpenAI(
        api_key=key,
        base_url=base_url,
        timeout=PROBE_TIMEOUT,
        max_retries=0,
        http_client=httpx.Client(timeout=PROBE_TIMEOUT, trust_env=settings.llm_trust_env),
    )


def _translate(exc: Exception) -> ProviderProbeError:
    """把 SDK 异常翻译成可展示的探测错误；鉴权类返回 `ProviderAuthError`（调用方据此决定是否回退内置表）。"""
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return ProviderAuthError("API Key 无效或无权限")
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return ProviderProbeError("网络不通或请求超时，请检查端点与网络")
    if isinstance(exc, openai.NotFoundError):
        return ProviderProbeError("模型不存在或端点路径有误")
    if isinstance(exc, openai.RateLimitError):
        return ProviderProbeError("请求过于频繁或额度不足")
    if isinstance(exc, openai.BadRequestError):
        text = str(exc)
        if "model" in text.lower():
            return ProviderProbeError("模型不存在或不可用")
        return ProviderProbeError(f"请求被供应商拒绝：{text[:120]}")
    if isinstance(exc, openai.APIStatusError):
        return ProviderProbeError(f"供应商返回异常状态 {exc.status_code}")
    return ProviderProbeError(f"调用失败：{str(exc)[:120]}")


def list_models(provider: str, base_url: str | None, api_key: str | None) -> list[ModelMeta]:
    """实时拉取供应商当前可用模型（OpenAI 兼容 `GET /models`）。

    失败抛 `ProviderProbeError`——由服务层决定是回退内置表（拉列表场景）还是直接报错（Key 无效场景）。
    """
    meta = PROVIDERS[provider]
    client = _build_client(meta, resolve_base_url(meta, base_url), api_key)
    try:
        remote = client.models.list()
    except Exception as exc:  # noqa: BLE001 —— 统一翻译为可展示原因
        raise _translate(exc) from exc
    return [enrich_remote_model(item.id) for item in remote.data]


def test_connection(
    provider: str, base_url: str | None, api_key: str | None, model: str | None
) -> str:
    """连通性测试：向供应商发一条最小消息，成功返回实际生效的模型名。

    **不落库、不保存配置**（接口文档 3.3）；失败抛 `ProviderProbeError`，由路由层转 10013。
    """
    meta = PROVIDERS[provider]
    target = (model or "").strip() or meta.default_model
    if not target:
        raise ProviderProbeError("请先选择模型")
    client = _build_client(meta, resolve_base_url(meta, base_url), api_key)
    try:
        resp = client.chat.completions.create(
            model=target,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc) from exc
    return resp.model or target  # 供应商可能把退役模型路由到替代模型，回传实际模型名
