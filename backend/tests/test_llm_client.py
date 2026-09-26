"""TC-50：LLM 对话客户端（步骤 10，系统设计 v1.16 §5.4 / 接口文档 v1.16 §1.3）。

**打桩方式**：`monkeypatch` 替换 `llm_client._build_client`，返回一个把网络层换成
`httpx.MockTransport` 的**真实 `OpenAI` 客户端**——SDK 的 SSE 解析、状态码→异常构造、
请求计数全是真的，只有 socket 被换掉。全程不触网（测试计划 §1.1）。

**私有函数直测**：`_parse_json` / `_is_retryable` 带下划线，但它们是本模块的核心逻辑
（容错边界与错误码映射），且已被接口文档 §1.3 与系统设计 §5.4 约定为对外行为；绕到公开
方法去覆盖同一分支，反而要构造精巧的 mock 响应才能命中（设计文档 §3.3）。
"""

import json

import httpx
import openai
import pytest
from sqlalchemy.orm import Session

from app.clients import llm_client
from app.clients.llm_client import (
    LLMConfig,
    LLMError,
    OpenAICompatibleClient,
    _is_retryable,
    _parse_json,
    get_llm_client,
    resolve_config,
)
from app.exceptions import ErrorCode
from app.main import app
from app.models import LlmProviderConfig
from app.utils.security import encrypt_text

CONFIG = LLMConfig(
    provider="deepseek",
    base_url="https://mock.local/v1",
    api_key="sk-test",
    model="test-model",
)
MSG = [{"role": "user", "content": "你好"}]


@pytest.fixture(autouse=True)
def _no_retry_delay(monkeypatch):
    """重试间隔对断言无意义，清零以省掉每条重试用例的 0.5s。"""
    monkeypatch.setattr(llm_client, "RETRY_DELAY", 0)


def _install(monkeypatch, *responses) -> list[httpx.Request]:
    """把 `_build_client` 换成走 MockTransport 的真实 SDK 客户端，返回请求记录表。

    `responses` 按顺序发放，每项可以是 `httpx.Response`，也可以是 `(request) -> Response`
    的函数（后者用于抛 `httpx.ReadTimeout` / `ConnectError` 这类传输层异常）。
    发完之后再请求会抛错——超出预期的调用要立刻暴露（如“不该重试却重试了”）。
    """
    seen: list[httpx.Request] = []
    queue = list(responses)

    def _handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert queue, f"超出预期的请求：{request.url}"
        item = queue.pop(0)
        return item(request) if callable(item) else item

    def _build(_config: LLMConfig) -> openai.OpenAI:
        return openai.OpenAI(
            api_key="sk-mock",
            base_url="http://mock.local/v1",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(_handle)),
        )

    monkeypatch.setattr(llm_client, "_build_client", _build)
    return seen


def _sse(*deltas: str, extra: str = "") -> httpx.Response:
    """OpenAI 兼容的流式响应：每个 delta 一个 data 块；extra 用于插额外块（如用量统计）。"""
    body = "".join(
        f"data: {json.dumps({'choices': [{'delta': {'content': d}}]}, ensure_ascii=False)}\n\n"
        for d in deltas
    )
    return httpx.Response(
        200,
        content=(body + extra + "data: [DONE]\n\n").encode(),
        headers={"content-type": "text/event-stream"},
    )


def _json_response(payload: dict) -> httpx.Response:
    """非流式响应：assistant 消息的 content 为 payload 的 JSON 文本。"""
    content = json.dumps(payload, ensure_ascii=False)
    return httpx.Response(
        200, json={"choices": [{"message": {"role": "assistant", "content": content}}]}
    )


def _error(status: int, message: str = "boom") -> httpx.Response:
    return httpx.Response(
        status, json={"error": {"message": message, "type": "invalid_request_error"}}
    )


# ---------- A 组：配置解析 resolve_config ----------


def _row(db: Session, user_id: int, **overrides) -> LlmProviderConfig:
    """直接落一行供应商配置（Key 走密文，与真实落库形态一致）。"""
    fields = {
        "provider": "deepseek",
        "base_url": None,
        "api_key": encrypt_text("sk-decrypted"),
        "model": "row-model",
        "is_active": 1,
    }
    fields.update(overrides)
    row = LlmProviderConfig(user_id=user_id, **fields)
    db.add(row)
    db.commit()
    return row


@pytest.fixture()
def _no_env_key(monkeypatch):
    """清掉 .env 兜底配置，让“账号无配置”这一前提成立。"""
    monkeypatch.setattr(llm_client.settings, "llm_api_key", "")
    monkeypatch.setattr(llm_client.settings, "llm_provider", "deepseek")
    monkeypatch.setattr(llm_client.settings, "llm_model", "")


def test_resolve_config_no_config_raises_10012(db_session: Session, account_id: int, _no_env_key):
    """TC-50：账号无生效行、.env 也无 Key → 10012（AI 未配置）。"""
    with pytest.raises(LLMError) as exc:
        resolve_config(db_session, account_id)

    assert exc.value.code == ErrorCode.LLM_KEY_MISSING


def test_resolve_config_env_fallback(db_session: Session, account_id: int, monkeypatch):
    """TC-50：账号无生效行时取 .env 四项；端点留空取注册表内置值。"""
    monkeypatch.setattr(llm_client.settings, "llm_provider", "deepseek")
    monkeypatch.setattr(llm_client.settings, "llm_api_key", "sk-from-env")
    monkeypatch.setattr(llm_client.settings, "llm_model", "env-model")
    monkeypatch.setattr(llm_client.settings, "llm_base_url", "")

    config = resolve_config(db_session, account_id)

    assert (config.provider, config.api_key, config.model) == ("deepseek", "sk-from-env", "env-model")
    assert config.base_url == "https://api.deepseek.com"  # 注册表内置端点


def test_resolve_config_active_row_decrypts_key(db_session: Session, account_id: int):
    """TC-50：账号生效行优先，库中密文取用时解密为明文。"""
    _row(db_session, account_id, model="row-model")

    config = resolve_config(db_session, account_id)

    assert config.api_key == "sk-decrypted"  # 密文已解密
    assert config.model == "row-model"


def test_resolve_config_incomplete_row_does_not_fall_back(
    db_session: Session, account_id: int, monkeypatch
):
    """TC-50：生效行存在但缺 Key 时**不走 .env 兜底**——Key 与端点错配比“未配置”更难排查。"""
    monkeypatch.setattr(llm_client.settings, "llm_api_key", "sk-from-env")  # .env 有 Key 也不许用
    _row(db_session, account_id, api_key=None)

    with pytest.raises(LLMError) as exc:
        resolve_config(db_session, account_id)

    assert exc.value.code == ErrorCode.LLM_KEY_MISSING


def test_resolve_config_model_falls_back_to_registry(db_session: Session, account_id: int):
    """TC-50：生效行 model 留空 → 取注册表该供应商的默认模型。"""
    _row(db_session, account_id, model="")

    assert resolve_config(db_session, account_id).model == "deepseek-flash"


# ---------- B 组：流式 stream_chat ----------


def test_stream_chat_yields_increments(monkeypatch):
    """TC-50：逐块 yield 文本增量，拼接结果等于完整文本。"""
    _install(monkeypatch, _sse("你", "好", "呀"))

    chunks = list(OpenAICompatibleClient().stream_chat(CONFIG, MSG))

    assert chunks == ["你", "好", "呀"]
    assert "".join(chunks) == "你好呀"


def test_stream_chat_skips_chunk_without_choices(monkeypatch):
    """TC-50：夹带的无 choices 块（真实用量统计块即此形态）不产出内容、不报错。"""
    usage_block = f"data: {json.dumps({'choices': [], 'usage': {'total_tokens': 9}})}\n\n"
    _install(monkeypatch, _sse("答", "案", extra=usage_block))

    assert list(OpenAICompatibleClient().stream_chat(CONFIG, MSG)) == ["答", "案"]


def test_stream_chat_builds_stream_once(monkeypatch):
    """TC-50：流式只建流一次——已开始输出后不重试（重试会导致内容重复）。"""
    seen = _install(monkeypatch, _sse("好"))

    list(OpenAICompatibleClient().stream_chat(CONFIG, MSG))

    assert len(seen) == 1


# ---------- C 组：JSON 解析 ----------


def test_parse_json_plain():
    """TC-50：标准 JSON 原样解析。"""
    assert _parse_json('{"a": 1}') == {"a": 1}


def test_parse_json_fenced():
    """TC-50：剥掉围栏标记后解析（模型常把 JSON 包在代码块里）。"""
    assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_with_surrounding_text():
    """TC-50：前后带解释文字时，取首个 `{` 到末个 `}`。"""
    assert _parse_json('好的，结果如下：{"a": 1} 希望有帮助') == {"a": 1}


def test_parse_json_no_object_raises():
    """TC-50：整段没有 JSON 对象 → ValueError。"""
    with pytest.raises(ValueError):
        _parse_json("抱歉，我无法回答这个问题")


def test_parse_json_top_level_array_raises():
    """TC-50：顶层是数组而非对象 → ValueError（调用方按 dict 消费）。"""
    with pytest.raises(ValueError):
        _parse_json("[1, 2]")


def test_chat_json_non_json_raises_10011(monkeypatch):
    """TC-50：经 chat_json 走完整路径，模型输出不可解析 → 10011。"""
    _install(
        monkeypatch,
        httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "抱歉，我无法回答"}}]},
        ),
    )

    with pytest.raises(LLMError) as exc:
        OpenAICompatibleClient().chat_json(CONFIG, MSG)

    assert exc.value.code == ErrorCode.LLM_OUTPUT_INVALID


def test_chat_json_parses_fenced_output(monkeypatch):
    """TC-50：非流式路径的围栏容错——出网侧与上面 5 条纯函数互为印证。"""
    _install(monkeypatch, _json_response({"city": "南京"}))

    assert OpenAICompatibleClient().chat_json(CONFIG, MSG) == {"city": "南京"}


# ---------- D 组：重试与异常映射 ----------


def _raw(status: int) -> httpx.Response:
    """构造 SDK 异常对象所需的最小 httpx 响应。"""
    request = httpx.Request("POST", "http://mock.local/v1/chat/completions")
    return httpx.Response(status, request=request)


class _BrokenStream(httpx.SyncByteStream):
    """先吐一个 delta 再断的流：模拟“已开始输出后连接中断”。"""

    def __iter__(self):
        payload = json.dumps({"choices": [{"delta": {"content": "部分"}}]}, ensure_ascii=False)
        yield f"data: {payload}\n\n".encode()
        raise httpx.ReadError("连接中断")


def test_stream_failure_midway_keeps_emitted_chunks(monkeypatch):
    """TC-50：流中途失败 → 抛 LLMError，**已产出的块已经 yield 出去**（上层据此保留已渲染内容）。

    同时确认不重试：重试会让已经输出的内容重复。
    """
    seen = _install(monkeypatch, httpx.Response(200, stream=_BrokenStream()))
    got: list[str] = []

    with pytest.raises(LLMError) as exc:
        for chunk in OpenAICompatibleClient().stream_chat(CONFIG, MSG):
            got.append(chunk)

    assert got == ["部分"]
    assert exc.value.code == ErrorCode.LLM_CALL_FAILED
    assert len(seen) == 1  # 不重试


def test_retry_succeeds_after_500(monkeypatch):
    """TC-50：服务端 5xx 重试 1 次后成功（请求共 2 次）。"""
    seen = _install(monkeypatch, _error(500), _sse("好"))

    assert "".join(OpenAICompatibleClient().stream_chat(CONFIG, MSG)) == "好"
    assert len(seen) == 2


def test_retry_exhausted_on_persistent_500(monkeypatch):
    """TC-50：持续 500 → 10010，重试 1 次后放弃（请求共 2 次）。"""
    seen = _install(monkeypatch, _error(500), _error(500))

    with pytest.raises(LLMError) as exc:
        list(OpenAICompatibleClient().stream_chat(CONFIG, MSG))

    assert exc.value.code == ErrorCode.LLM_CALL_FAILED
    assert len(seen) == 2


def test_rate_limit_not_retried(monkeypatch):
    """TC-50：429 不重试（请求 1 次）——限流重试只会加重限流。"""
    seen = _install(monkeypatch, _error(429, "rate limit"))

    with pytest.raises(LLMError) as exc:
        list(OpenAICompatibleClient().stream_chat(CONFIG, MSG))

    assert exc.value.code == ErrorCode.LLM_CALL_FAILED
    assert len(seen) == 1


def test_auth_error_maps_to_10012(monkeypatch):
    """TC-50：401 → 10012（Key 无效），不重试。"""
    seen = _install(monkeypatch, _error(401, "invalid api key"))

    with pytest.raises(LLMError) as exc:
        list(OpenAICompatibleClient().stream_chat(CONFIG, MSG))

    assert exc.value.code == ErrorCode.LLM_KEY_MISSING
    assert len(seen) == 1


def test_permission_denied_maps_to_10012(monkeypatch):
    """TC-50：403 → 10012（无权限），与 401 同档。"""
    _install(monkeypatch, _error(403, "permission denied"))

    with pytest.raises(LLMError) as exc:
        list(OpenAICompatibleClient().stream_chat(CONFIG, MSG))

    assert exc.value.code == ErrorCode.LLM_KEY_MISSING


def test_not_found_maps_to_10013(monkeypatch):
    """TC-50：404 → 10013（模型不存在或端点有误）。"""
    _install(monkeypatch, _error(404, "model not found"))

    with pytest.raises(LLMError) as exc:
        list(OpenAICompatibleClient().stream_chat(CONFIG, MSG))

    assert exc.value.code == ErrorCode.LLM_TEST_FAILED


def test_bad_request_with_model_hint_maps_to_10013(monkeypatch):
    """TC-50：400 且报错文本含 model → 10013（模型选择的锅，引导去 AI 配置页）。"""
    _install(monkeypatch, _error(400, "invalid model specified"))

    with pytest.raises(LLMError) as exc:
        list(OpenAICompatibleClient().stream_chat(CONFIG, MSG))

    assert exc.value.code == ErrorCode.LLM_TEST_FAILED


def test_bad_request_without_model_hint_maps_to_10010(monkeypatch):
    """TC-50：400 但与 model 无关 → 10010（请求本身被拒，非配置问题）。"""
    _install(monkeypatch, _error(400, "invalid params: temperature"))

    with pytest.raises(LLMError) as exc:
        list(OpenAICompatibleClient().stream_chat(CONFIG, MSG))

    assert exc.value.code == ErrorCode.LLM_CALL_FAILED


def test_timeout_maps_to_10010_and_retries(monkeypatch):
    """TC-50：读超时属于临时性故障 → 重试 1 次，最终 10010。"""

    def _timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("读取超时", request=request)

    seen = _install(monkeypatch, _timeout, _timeout)

    with pytest.raises(LLMError) as exc:
        list(OpenAICompatibleClient().stream_chat(CONFIG, MSG))

    assert exc.value.code == ErrorCode.LLM_CALL_FAILED
    assert len(seen) == 2


def test_connection_error_maps_to_10010_and_retries(monkeypatch):
    """TC-50：连接被拒属于临时性故障 → 重试 1 次，最终 10010。"""

    def _refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("拒绝连接", request=request)

    seen = _install(monkeypatch, _refused, _refused)

    with pytest.raises(LLMError) as exc:
        list(OpenAICompatibleClient().stream_chat(CONFIG, MSG))

    assert exc.value.code == ErrorCode.LLM_CALL_FAILED
    assert len(seen) == 2


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (openai.APIConnectionError(request=httpx.Request("POST", "http://x")), True),
        (openai.APITimeoutError(request=httpx.Request("POST", "http://x")), True),
        (openai.InternalServerError("500", response=_raw(500), body=None), True),
        (openai.RateLimitError("429", response=_raw(429), body=None), False),
        (openai.AuthenticationError("401", response=_raw(401), body=None), False),
        (openai.BadRequestError("400", response=_raw(400), body=None), False),
        (openai.NotFoundError("404", response=_raw(404), body=None), False),
    ],
)
def test_is_retryable_matrix(exc: Exception, expected: bool):
    """TC-50：重试判定矩阵——连接错误 / 超时 / 5xx 才重试；429 与各类 4xx 立刻反馈。"""
    assert _is_retryable(exc) is expected


# ---------- E 组：注入点 ----------


def test_get_llm_client_returns_new_instance():
    """TC-50：注入点**每请求新建**实例——实例携带本次调用的降级状态（`degraded_from`），
    做成单例会被并发请求互相污染（系统设计 §5.4）。"""
    first, second = get_llm_client(), get_llm_client()

    assert isinstance(first, OpenAICompatibleClient)
    assert first is not second


def test_dependency_override_registers_and_restores(fake_llm_client):
    """TC-50：`dependency_overrides` 覆盖后取到替身；撤销后恢复生产实现。

    `dependency_overrides` 是 app 级全局字典，本用例同时钉住“清理有效”这一约定——
    漏清理会静默污染其后所有用例（设计文档 §3.2）。
    """
    assert app.dependency_overrides[get_llm_client]() is fake_llm_client

    app.dependency_overrides.pop(get_llm_client)
    assert isinstance(get_llm_client(), OpenAICompatibleClient)


def test_fake_llm_client_records_and_plays(fake_llm_client):
    """TC-50：替身按预设吐块、返回 dict，并记录入参——后续步骤据此断言“内容来自哪次调用”。"""
    fake_llm_client.chunks = ["甲", "乙"]
    fake_llm_client.json_result = {"score": 8}
    tools = [{"type": "function"}]

    assert list(fake_llm_client.stream_chat(CONFIG, MSG, tools=tools)) == ["甲", "乙"]
    assert fake_llm_client.chat_json(CONFIG, MSG) == {"score": 8}
    assert fake_llm_client.stream_calls == [(CONFIG, MSG, tools)]
    assert fake_llm_client.json_calls == [(CONFIG, MSG)]


# ---------- TC-106：公开免 Key 服务与自动降级 ----------


def _public_config(*, fallback: LLMConfig | None) -> LLMConfig:
    """公开免 Key 服务的调用配置（`is_public` 的供应商，Key 为占位值）。"""
    return LLMConfig(
        provider="pollinations",
        base_url="https://mock.local/v1",
        api_key="placeholder",
        model="openai-fast",
        fallback=fallback,
    )


def _fallback_config() -> LLMConfig:
    return LLMConfig(
        provider="zhipu", base_url="https://mock.local/v1", api_key="sk-platform", model="glm-4.7-flash"
    )


def test_public_service_degrades_on_failure(monkeypatch):
    """TC-106：公开免 Key 服务失败 → 自动改用平台共享 Key 重试一次，并记录 `degraded_from`。

    公开服务是第三方公益端点、可用性不可控；不降级的话使用者只会反复重试。
    """
    seen = _install(monkeypatch, _error(500), _error(500), _sse("退而求其次"))
    client = OpenAICompatibleClient()

    assert "".join(client.stream_chat(_public_config(fallback=_fallback_config()), MSG)) == "退而求其次"
    assert client.degraded_from == "pollinations"
    assert len(seen) == 3  # 公开服务 500 重试 1 次（共 2）→ 换源成功（第 3 次）


def test_degrade_happens_once_only(monkeypatch):
    """TC-106：**只降一级、不递归**——兜底也失败时不再找下一个，且不计降级（`degraded_from` 为 None）。"""
    seen = _install(monkeypatch, _error(401), _error(401))  # 401 鉴权错不重试：公开 1 次 + 兜底 1 次
    client = OpenAICompatibleClient()

    with pytest.raises(LLMError):
        list(client.stream_chat(_public_config(fallback=_fallback_config()), MSG))

    assert client.degraded_from is None
    assert len(seen) == 2


def test_no_fallback_target_attaches_hint(monkeypatch):
    """TC-106：无兜底目标时按原错误上报，**并补一句可操作提示**（引导换来源或填自己的 Key）。"""
    _install(monkeypatch, _error(500), _error(500))

    with pytest.raises(LLMError) as exc:
        list(OpenAICompatibleClient().stream_chat(_public_config(fallback=None), MSG))

    assert "公开免费服务可用性有限" in str(exc.value)
    assert "AI 配置页" in str(exc.value)
    assert exc.value.code == ErrorCode.LLM_CALL_FAILED


def test_hint_only_for_public_service(monkeypatch):
    """TC-106：那句提示**只针对公开免 Key 服务**——普通供应商失败时消息保持原样。"""
    _install(monkeypatch, _error(401))

    with pytest.raises(LLMError) as exc:
        list(OpenAICompatibleClient().stream_chat(CONFIG, MSG))

    assert "公开免费服务" not in str(exc.value)


def test_resolve_config_public_row_needs_no_key(db_session: Session, account_id: int):
    """TC-106：公开免 Key 服务行**不需要账号自备 Key**（用占位值），且解析出平台共享兜底配置。"""
    # 平台行：免费档的兜底来源（按注册表顺序取第一个有 Key 的家）
    _row(db_session, 0, provider="zhipu", model="glm-4.7-flash", api_key=encrypt_text("sk-platform"))
    # 账号行：选用公开免 Key 服务（use_shared=1、无 api_key）
    _row(db_session, account_id, provider="pollinations", model="openai-fast", api_key=None, use_shared=1)

    config = resolve_config(db_session, account_id)

    assert config.provider == "pollinations"
    assert config.api_key  # 非空（占位值，SDK 必填）
    assert config.model == "openai-fast"
    assert config.fallback is not None
    assert config.fallback.provider == "zhipu"


def test_resolve_config_shared_row_reads_platform_key(db_session: Session, account_id: int):
    """TC-106：平台共享档从 `user_id=0` 平台行取 Key（账号行自己没有 Key 也能用）。"""
    _row(db_session, 0, provider="zhipu", model="glm-4.7-flash", api_key=encrypt_text("sk-platform"))
    _row(db_session, account_id, provider="zhipu", model="glm-4-flash", api_key=None, use_shared=1)

    config = resolve_config(db_session, account_id)

    assert config.provider == "zhipu"
    assert config.api_key == "sk-platform"  # 取自平台行
    assert config.model == "glm-4-flash"  # 模型仍用账号本行所选
    assert config.fallback is None  # 平台共享档自身不是公开服务，无兜底


def test_resolve_config_shared_row_without_platform_key(db_session: Session, account_id: int):
    """TC-106：平台行被撤下（该家免费模型已下线）→ **10012 且提示去 AI 配置页重选**，不回退 .env。"""
    _row(db_session, account_id, provider="zhipu", model="glm-4-flash", api_key=None, use_shared=1)

    with pytest.raises(LLMError) as exc:
        resolve_config(db_session, account_id)

    assert exc.value.code == ErrorCode.LLM_KEY_MISSING
    assert "免费模型已下线" in str(exc.value)
