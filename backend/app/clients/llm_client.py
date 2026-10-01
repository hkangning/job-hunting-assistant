"""LLM 对话能力封装：流式对话、JSON 抽取、账号配置解析、超时与重试（系统设计 5.4）。

本模块只承担「产生对话内容」的调用；探测类（连通性测试 / 模型列表）在 `llm_provider.py`。
全部 AI 功能（JD 分析 / 陪练点评 / 模拟面试 / 面经复盘 / 定时文案）一律经本模块出网，
业务层不得直接 new openai 客户端（系统设计 3 章规则）。

失败一律抛 `LLMError`（`BizException` 子类，携带对外错误码）——普通请求由全局处理器转统一响应体，
SSE 场景由流式层取 code / message 发 error 事件，调用方无需转换异常类型。
"""

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import httpx
import openai
from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients import llm_provider as registry
from app.config import settings
from app.exceptions import BizException, ErrorCode
from app.models import LlmProviderConfig
from app.utils.security import decrypt_text

logger = logging.getLogger(__name__)

# 对话类超时（系统设计 5.4）：连接 5s；read 8s 兼作「首 token 超时」与「流中途静默超时」
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 8.0
WRITE_TIMEOUT = 10.0
POOL_TIMEOUT = 5.0

RETRY_TIMES = 1  # 临时性故障重试次数（系统设计 5.4：仅网络类；429 与鉴权错不重试）
RETRY_DELAY = 0.5  # 重试间隔（秒）

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


@dataclass(frozen=True)
class LLMConfig:
    """一次对话调用所需的配置（由 `resolve_config` 从账号生效行或 .env 兜底解析）。"""

    provider: str  # 供应商标识（注册表键）
    base_url: str  # API 端点（账号配置优先，缺省用注册表内置值）
    api_key: str  # 密钥明文（仅调用期间存在于内存；免 Key 供应商为占位值）
    model: str  # 模型 ID


@dataclass(frozen=True)
class TextDelta:
    """流式输出的一段文本增量。"""

    text: str


@dataclass(frozen=True)
class ToolCallDelta:
    """一次**完整**的工具调用（增量聚合完毕后才发出，Agent 链路用）。"""

    tool_name: str
    arguments: str  # 原始 JSON 字符串，由调用方解析（容错）与校验


class LLMError(BizException):
    """LLM 对话调用失败（配置缺失 / 鉴权 / 模型不存在 / 网络超时 / 输出格式）。

    继承 `BizException`：普通请求由全局处理器转 502 统一响应体，SSE 场景取 code / message 发 error 事件。
    """


def resolve_config(db: Session, user_id: int) -> LLMConfig:
    """解析当前账号的对话配置（系统设计 5.4 Key 读取链）：生效行 → .env 兜底 → 都无抛 10012。

    **生效行存在但不完整时不再走 .env 兜底**——否则会把环境变量的 Key 配到账号所选的端点上，
    Key 与端点错配比「未配置」更难排查。
    """
    row = db.scalar(
        select(LlmProviderConfig).where(
            LlmProviderConfig.user_id == user_id, LlmProviderConfig.is_active == 1
        )
    )
    if row is not None:
        return _config_from_row(db, row)
    return _config_from_env()


class LLMClient(ABC):
    """对话客户端抽象：所有 AI 链路经此出口调用。

    测试以 `app.dependency_overrides[get_llm_client]` 替换为替身（测试计划 1.3），生产代码零改动。
    """

    @abstractmethod
    def stream_chat(
        self, config: LLMConfig, messages: list[dict], tools: list[dict] | None = None
    ) -> Iterator[str]:
        """流式对话：逐块 yield 文本增量（LLM 侧 `stream=True`）。"""

    @abstractmethod
    def chat_json(self, config: LLMConfig, messages: list[dict]) -> dict:
        """非流式对话：返回解析后的 JSON 对象（面经结构化 / 投喂抽取用）。"""

    def stream_tool_chat(
        self, config: LLMConfig, messages: list[dict], tools: list[dict] | None = None
    ) -> Iterator[TextDelta | ToolCallDelta]:
        """带工具调用的流式对话（Agent 链路）：yield 文本增量与完整工具调用。

        **非抽象方法**（意为之）：默认实现降级为纯文本流、忽略 `tools`——测试替身不实现
        本方法也能正常实例化；需要验证 tool_call 事件序列的用例自行覆写。
        """
        for text in self.stream_chat(config, messages):
            yield TextDelta(text)


class OpenAICompatibleClient(LLMClient):
    """生产实现：12 家供应商全走 OpenAI 兼容协议（系统设计 5.4）。"""

    def stream_chat(
        self, config: LLMConfig, messages: list[dict], tools: list[dict] | None = None
    ) -> Iterator[str]:
        stream = _create_stream(_build_client(config), config, messages, tools)
        finished = False
        try:
            for chunk in stream:
                if not chunk.choices:  # 末尾用量统计等无 choices 的块
                    continue
                choice = chunk.choices[0]
                if choice.finish_reason:  # 终止标记（stop / length / content_filter / tool_calls）
                    finished = True
                delta = choice.delta
                if delta is not None and delta.content:
                    yield delta.content
        except Exception as exc:  # 流中途失败（超时 / 连接中断 / 服务端错误）：已输出的内容由上层保留
            raise _translate(exc) from exc
        finally:
            # 主动断开与供应商的连接（幂等）：SSE 断连时上层抛出 GeneratorExit，不关就只靠 GC 回收
            stream.close()
        _ensure_stream_finished(finished)

    def chat_json(self, config: LLMConfig, messages: list[dict]) -> dict:
        response = _create_chat(_build_client(config), config, messages)
        content = (response.choices[0].message.content or "") if response.choices else ""
        try:
            return parse_json_block(content)
        except ValueError as exc:
            raise LLMError(ErrorCode.LLM_OUTPUT_INVALID, f"AI 输出格式异常：{exc}") from exc

    def stream_tool_chat(
        self, config: LLMConfig, messages: list[dict], tools: list[dict] | None = None
    ) -> Iterator[TextDelta | ToolCallDelta]:
        """流式 + 工具调用：文本增量即时下发；tool_calls 按 index 聚合为完整调用后下发。

        聚合在 `finish_reason == "tool_calls"` 时发出；流正常结束后再兜底发一次，覆盖
        「终止标记非 tool_calls 但聚合仍有残片」的供应商差异。流结束无终止标记 = 上游被截断，
        按调用失败上抛（IS-56）。
        """
        stream = _create_stream(_build_client(config), config, messages, tools)
        pending: dict[int, dict] = {}  # index → 聚合中的调用（id 不收：结果以普通消息回灌，不走 role=tool）
        finished = False
        try:
            for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta is not None:
                    if delta.content:
                        yield TextDelta(delta.content)
                    for part in delta.tool_calls or []:
                        slot = pending.setdefault(part.index or 0, {"name": "", "arguments": ""})
                        if part.function is not None:
                            if part.function.name:  # 个别供应商把函数名也拆成多块
                                slot["name"] += part.function.name
                            if part.function.arguments:
                                slot["arguments"] += part.function.arguments
                if choice.finish_reason:
                    finished = True
                    if choice.finish_reason == "tool_calls":
                        yield from _flush_calls(pending)
        except Exception as exc:
            raise _translate(exc) from exc
        finally:
            stream.close()
        _ensure_stream_finished(finished)
        yield from _flush_calls(pending)  # 兜底：终止标记非 tool_calls 但聚合仍有残片的供应商差异


def get_llm_client() -> LLMClient:
    """对话客户端注入点（FastAPI 依赖）：测试覆盖此依赖即可注入替身（测试计划 1.3）。"""
    return OpenAICompatibleClient()


# ---------- 内部工具 ----------


def _config_from_row(db: Session, row: LlmProviderConfig) -> LLMConfig:
    """账号生效行 → 对话配置；任一项不完整即抛 10012 并指明缺什么。"""
    meta = registry.get_provider(row.provider)
    if meta is None:  # 历史数据指向已下线的注册表条目
        raise LLMError(ErrorCode.LLM_KEY_MISSING, "当前 AI 供应商已不可用，请前往 AI 配置页重新选择")
    api_key = decrypt_text(row.api_key) if row.api_key else ""
    base_url = registry.resolve_base_url(meta, row.base_url)
    if not base_url:
        raise LLMError(ErrorCode.LLM_KEY_MISSING, "该供应商缺少 API 端点，请前往 AI 配置页补全")
    if meta.needs_key and not api_key:
        raise LLMError(ErrorCode.LLM_KEY_MISSING)
    model = (row.model or "").strip() or meta.default_model or ""
    if not model:
        raise LLMError(ErrorCode.LLM_KEY_MISSING, "尚未选择模型，请前往 AI 配置页选择")
    return LLMConfig(meta.key, base_url, api_key or registry.KEYLESS_PLACEHOLDER, model)


def _config_from_env() -> LLMConfig:
    """环境变量兜底（本地单机场景）：账号未配置任何供应商时用 .env 的 LLM_* 四项。"""
    api_key = settings.llm_api_key.strip()
    if not api_key:
        raise LLMError(ErrorCode.LLM_KEY_MISSING)
    meta = registry.get_provider(settings.llm_provider)
    if meta is None:
        raise LLMError(
            ErrorCode.LLM_KEY_MISSING, f"环境变量 LLM_PROVIDER 指向的供应商不存在：{settings.llm_provider}"
        )
    base_url = registry.resolve_base_url(meta, settings.llm_base_url)
    model = settings.llm_model.strip() or meta.default_model or ""
    if not model:
        raise LLMError(ErrorCode.LLM_KEY_MISSING, "尚未选择模型，请前往 AI 配置页选择")
    return LLMConfig(meta.key, base_url, api_key, model)


def _build_client(config: LLMConfig) -> OpenAI:
    """构造对话客户端：连接 5s / 读取 8s；**不用 SDK 自带重试**，重试策略统一由本模块控制。

    代理行为见 `_http_client`（默认直连，不走系统代理）。
    """
    return OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=_timeout(),
        max_retries=0,
        http_client=_http_client(),
    )


def _timeout() -> httpx.Timeout:
    """对话类超时配置（连接 5s / 读取 8s / 写入 10s）。"""
    return httpx.Timeout(
        connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=WRITE_TIMEOUT, pool=POOL_TIMEOUT
    )


def _http_client() -> httpx.Client:
    """显式构造 httpx 客户端，代理行为由 `LLM_TRUST_ENV` 控制（默认直连）。

    httpx 默认 `trust_env=True`，会读系统代理设置（Windows 下取注册表）；代理软件退出后
    系统代理往往残留，导致请求全部 SSL 失败。默认直连更稳，需代理访问境外供应商时置 true。
    """
    return httpx.Client(timeout=_timeout(), trust_env=settings.llm_trust_env)


def _create_stream(
    client: OpenAI, config: LLMConfig, messages: list[dict], tools: list[dict] | None
) -> Iterator:
    """建立流式请求：连接 / 鉴权 / 429 等错误在此阶段抛出并翻译（此时尚未输出，可安全重试）。"""
    kwargs: dict = {"model": config.model, "messages": messages, "stream": True}
    if tools:
        kwargs["tools"] = tools
    return _retry(lambda: client.chat.completions.create(**kwargs))


def _flush_calls(pending: dict[int, dict]) -> list[ToolCallDelta]:
    """把聚合完毕的工具调用按 index 顺序取出，并清空缓冲区（无函数名的残片丢弃）。"""
    calls = [
        ToolCallDelta(slot["name"], slot["arguments"])
        for _, slot in sorted(pending.items())
        if slot["name"]
    ]
    pending.clear()
    return calls


def _ensure_stream_finished(finished: bool) -> None:
    """流结束却全程未收到终止标记 = 上游连接被截断（IS-56）：按调用失败上抛。

    OpenAI 兼容协议的流式响应收尾必带 `finish_reason`（stop / length / tool_calls 等）；
    `[DONE]` 会被 SDK 消费、不产生 chunk，判断依据只能是 `finish_reason`。截断时已产出的
    增量由调用方保留，但**不得当完整回复落库**——与各链路「失败不落库、重发即重试」口径一致。
    """
    if not finished:
        raise LLMError(ErrorCode.LLM_CALL_FAILED, "AI 回复被中断（未收到完成标记），请重试")


def _create_chat(client: OpenAI, config: LLMConfig, messages: list[dict]):
    """非流式请求：网络类故障重试后返回完整响应。"""
    return _retry(lambda: client.chat.completions.create(model=config.model, messages=messages))


def _retry(call: Callable):
    """临时性故障重试（系统设计 5.4）：仅连接错误 / 超时 / 服务端 5xx；429 与鉴权错立刻反馈。

    流式场景只重试建流阶段——已开始输出后再重试会导致内容重复。
    """
    for attempt in range(RETRY_TIMES + 1):
        try:
            return call()
        except Exception as exc:
            if attempt >= RETRY_TIMES or not _is_retryable(exc):
                raise _translate(exc) from exc
            logger.warning("LLM 调用失败，%.1fs 后重试：%s", RETRY_DELAY, exc)
            time.sleep(RETRY_DELAY)


def _is_retryable(exc: Exception) -> bool:
    """是否属可重试的临时性故障：连接错误 / 超时 / 服务端 5xx。"""
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return True
    return isinstance(exc, openai.APIStatusError) and exc.status_code >= 500


def _translate(exc: Exception) -> LLMError:
    """把 SDK 异常翻译为对外错误码（接口文档 1.3）：配置类 10012 / 模型类 10013 / 其余 10010。"""
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return LLMError(ErrorCode.LLM_KEY_MISSING, "API Key 无效或无权限，请前往 AI 配置页检查")
    if isinstance(exc, openai.NotFoundError):
        return LLMError(ErrorCode.LLM_TEST_FAILED, "模型不存在或端点有误，请前往 AI 配置页重新选择模型")
    if isinstance(exc, openai.RateLimitError):
        return LLMError(ErrorCode.LLM_CALL_FAILED, "请求过于频繁或额度不足，请稍后重试")
    if isinstance(exc, openai.BadRequestError):
        text = str(exc)
        if "model" in text.lower():
            return LLMError(ErrorCode.LLM_TEST_FAILED, "模型不存在或不可用，请前往 AI 配置页重新选择模型")
        return LLMError(ErrorCode.LLM_CALL_FAILED, f"请求被供应商拒绝：{text[:120]}")
    # 超时须先于连接错误判断：APITimeoutError 是 APIConnectionError 的子类，倒过来会被吞掉
    if isinstance(exc, openai.APITimeoutError):
        return LLMError(
            ErrorCode.LLM_CALL_FAILED,
            "AI 模型长时间无响应（超时），可重试，或前往 AI 配置页更换更快的模型",
        )
    if isinstance(exc, openai.APIConnectionError):
        return LLMError(
            ErrorCode.LLM_CALL_FAILED, "无法连接 AI 服务，请检查网络，或前往 AI 配置页核对 API 端点"
        )
    if isinstance(exc, openai.APIStatusError):
        return LLMError(ErrorCode.LLM_CALL_FAILED, f"AI 服务返回异常状态 {exc.status_code}")
    return LLMError(ErrorCode.LLM_CALL_FAILED, f"AI 调用失败：{str(exc)[:120]}")


def parse_json_block(text: str) -> dict:
    """解析模型返回的 JSON：容忍 ```json 围栏与前后解释文字（取首个 `{` 到末个 `}`）；失败抛 ValueError。

    公开：陪练的「判定」段（挑错模式的命中率）也吃这套容错，不复写一份。
    """
    raw = text.strip()
    fenced = _JSON_FENCE.search(raw)
    if fenced:
        raw = fenced.group(1).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("返回内容中未找到 JSON 对象")
    data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("JSON 顶层不是对象")
    return data


_parse_json = parse_json_block  # 兼容既有直测用例引用的旧名
