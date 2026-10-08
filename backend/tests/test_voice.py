"""步骤 24 语音链路用例（测试计划 5.2 / 台账 #107）。

- **全 mock、离线可跑**：ASR 走 `get_asr_client_factory` 工厂依赖替身（funasr / xunfei
  两分支都被接管）、TTS 走 `get_tts_client` 无参依赖替身——不加载本地模型、不调 edge-tts。
- 音频解码与校验（`decode_checked`，PyAV）在工厂之外、服务层内，用例仍**真走解码**：
  音频样本用小型真 wav 字节（16k 单声道），垃圾字节 / 空文件 / 超限验证 10001。
- 静音片段（纯静音 / 仅底噪）服务端短路为空文本、不进引擎（替身未被调用即证明）。
"""

import io
import math
import struct
import wave
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from sqlalchemy import select

from app.clients.asr_client import AsrClient, build_asr_client, get_asr_client_factory
from app.clients.tts_client import TtsClient, get_tts_client
from app.database import SessionLocal
from app.exceptions import BizException, ErrorCode
from app.main import app
from app.models import Config

API = "/api/v1"

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"


# ---------- 音频样本 ----------


def _pcm_wav(frames: list[int], rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(frames)}h", *frames))
    return buf.getvalue()


def _speech_wav(seconds: float = 1.0, rate: int = 16000, amp: float = 0.4) -> bytes:
    """带语音级信号的 wav：440Hz 正弦（RMS≈0.28，过 has_speech 阈值走真引擎分支）。"""
    n = int(seconds * rate)
    return _pcm_wav([int(amp * 32767 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(n)], rate)


def _silence_wav(seconds: float = 1.5, rate: int = 16000) -> bytes:
    return _pcm_wav([0] * int(seconds * rate), rate)


# ---------- 替身与注入 ----------


class FakeAsrClient(AsrClient):
    """转写替身：返回固定文本，记录收到的采样数组。"""

    def __init__(self, text: str = "这是转写文本") -> None:
        self.text = text
        self.calls: list[Any] = []

    def transcribe(self, samples: Any) -> str:
        self.calls.append(samples)
        return self.text


class FakeTtsClient(TtsClient):
    """合成替身：返回固定 mp3 字节；可置 error 模拟引擎异常。"""

    def __init__(self, data: bytes = b"\xff\xfb\x90\x00stub-mp3-bytes") -> None:
        self.data = data
        self.error: Exception | None = None
        self.calls: list[tuple[str, str]] = []

    def synthesize(self, text: str, voice: str) -> bytes:
        self.calls.append((text, voice))
        if self.error is not None:
            raise self.error
        return self.data


@pytest.fixture()
def fake_asr() -> Iterator[FakeAsrClient]:
    """ASR 工厂依赖替身：funasr / xunfei 两分支都返回同一替身，并记录工厂入参。"""
    fake = FakeAsrClient()
    fake.provider_calls = []  # type: ignore[attr-defined]

    def factory(provider: str, app_id: str, api_key: str) -> AsrClient:
        fake.provider_calls.append((provider, app_id, api_key))  # type: ignore[attr-defined]
        return fake

    app.dependency_overrides[get_asr_client_factory] = lambda: factory
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_asr_client_factory, None)


@pytest.fixture()
def fake_tts() -> Iterator[FakeTtsClient]:
    fake = FakeTtsClient()
    app.dependency_overrides[get_tts_client] = lambda: fake
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_tts_client, None)


def _post_audio(client: Any, data: bytes, name: str = "segment.wav") -> Any:
    return client.post(f"{API}/asr/transcribe", files={"file": (name, data, "audio/wav")})


# ---------- POST /asr/transcribe ----------


def test_transcribe_success(client: Any, fake_asr: FakeAsrClient) -> None:
    """转写成功：文本来自替身、duration_ms 与音频时长一致、默认走 funasr。"""
    resp = _post_audio(client, _speech_wav(1.0))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["text"] == "这是转写文本"
    assert data["duration_ms"] == pytest.approx(1000, abs=20)
    assert len(fake_asr.calls) == 1
    assert len(fake_asr.calls[0]) == 16000  # 1 秒 @16k
    assert fake_asr.provider_calls[0][0] == "funasr"  # type: ignore[attr-defined]


def test_transcribe_empty_file(client: Any, fake_asr: FakeAsrClient) -> None:
    resp = _post_audio(client, b"")
    assert resp.status_code == 400
    assert resp.json()["code"] == 10001
    assert fake_asr.calls == []


def test_transcribe_too_large(client: Any, fake_asr: FakeAsrClient) -> None:
    resp = _post_audio(client, b"x" * (2 * 1024 * 1024 + 1))
    assert resp.status_code == 400
    assert resp.json()["code"] == 10001
    assert fake_asr.calls == []


def test_transcribe_undecodable(client: Any, fake_asr: FakeAsrClient) -> None:
    """垃圾字节 → 10001；校验先于引擎调用（替身未被触达）。"""
    resp = _post_audio(client, b"not-an-audio-file" * 50)
    assert resp.status_code == 400
    assert resp.json()["code"] == 10001
    assert fake_asr.calls == []


def test_transcribe_silence_short_circuit(client: Any, fake_asr: FakeAsrClient) -> None:
    """纯静音片段：短路为空文本、duration_ms 照常、不进引擎。"""
    resp = _post_audio(client, _silence_wav(1.5))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["text"] == ""
    assert data["duration_ms"] == pytest.approx(1500, abs=20)
    assert fake_asr.calls == []


def test_transcribe_decode_dependency_missing_is_10000(
    client: Any,
    fake_asr: FakeAsrClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """解码依赖缺失（ImportError 家族）→ 10000「服务环境未就绪」，与坏音频（10001）分道（IS-64）。

    依赖为延迟导入，直接在 `decode_audio` 注入异常覆盖该态、无需真装卸依赖；
    warning 携带原始异常类型，换机少装 numpy / av 时排查不被误导到音频字节上。
    """
    import app.clients.asr_client as asr_module

    def _missing(audio: bytes):
        raise ModuleNotFoundError("No module named 'av'")

    monkeypatch.setattr(asr_module, "decode_audio", _missing)
    resp = _post_audio(client, _speech_wav(1.0))

    assert resp.status_code == 500
    assert resp.json()["code"] == 10000
    assert fake_asr.calls == []  # 校验先于引擎调用
    assert "音频解码依赖缺失" in caplog.text


def test_transcribe_broken_audio_remains_10001(
    client: Any, fake_asr: FakeAsrClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """分道另一侧：非 ImportError 的解码异常仍按 400 + 10001（IS-64 不改其口径）。"""
    import app.clients.asr_client as asr_module

    def _broken(audio: bytes):
        raise ValueError("Invalid data found when processing input")

    monkeypatch.setattr(asr_module, "decode_audio", _broken)
    resp = _post_audio(client, _speech_wav(1.0))

    assert resp.status_code == 400
    assert resp.json()["code"] == 10001
    assert fake_asr.calls == []


def test_build_asr_client_xunfei_without_credential() -> None:
    """讯飞未配凭据 → 60001（直接单测真实工厂）。"""
    with pytest.raises(BizException) as exc_info:
        build_asr_client("xunfei", "", "")
    assert exc_info.value.code == ErrorCode.ASR_FAILED


def test_transcribe_xunfei_broken_credential(client: Any, fake_asr: FakeAsrClient) -> None:
    """provider 切讯飞 + 库中凭据密文损坏 → 60001（不是 Key 类错误码）。"""
    # 先落一行密文（服务层会正常加密），再直接改库为损坏值——模拟历史脏数据 / 密钥轮换
    client.put(f"{API}/settings", json={"asr_provider": "xunfei", "asr_api_key": "dummy-key"})
    with SessionLocal() as session:
        row = session.scalar(
            select(Config).where(
                Config.user_id == client.auth_account["id"], Config.key == "asr_api_key"
            )
        )
        assert row is not None
        row.value = "not-a-valid-fernet-token"
        session.commit()
    resp = _post_audio(client, _speech_wav(0.5))
    assert resp.status_code == 502
    assert resp.json()["code"] == 60001
    assert fake_asr.calls == []  # 凭据解析失败先于引擎构造


# ---------- POST /tts/synthesize ----------


def test_synthesize_success(client: Any, fake_tts: FakeTtsClient) -> None:
    """合成成功：返回音频流（不走统一响应体）、缺省用账号音色。"""
    resp = client.post(f"{API}/tts/synthesize", json={"text": "你好，世界"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("audio/mpeg")
    assert resp.content == fake_tts.data
    assert fake_tts.calls == [("你好，世界", DEFAULT_VOICE)]


def test_synthesize_voice_explicit(client: Any, fake_tts: FakeTtsClient) -> None:
    resp = client.post(
        f"{API}/tts/synthesize", json={"text": "你好", "voice": "zh-TW-HsiaoChenNeural"}
    )
    assert resp.status_code == 200
    assert fake_tts.calls[0][1] == "zh-TW-HsiaoChenNeural"


def test_synthesize_text_blank(client: Any, fake_tts: FakeTtsClient) -> None:
    resp = client.post(f"{API}/tts/synthesize", json={"text": "   "})
    assert resp.status_code == 400
    assert resp.json()["code"] == 10001
    assert fake_tts.calls == []


def test_synthesize_text_max_boundary(client: Any, fake_tts: FakeTtsClient) -> None:
    """2000 字边界可合成、2001 字拒绝。"""
    ok = client.post(f"{API}/tts/synthesize", json={"text": "字" * 2000})
    assert ok.status_code == 200
    too_long = client.post(f"{API}/tts/synthesize", json={"text": "字" * 2001})
    assert too_long.status_code == 400
    assert too_long.json()["code"] == 10001


def test_synthesize_voice_invalid(client: Any, fake_tts: FakeTtsClient) -> None:
    resp = client.post(f"{API}/tts/synthesize", json={"text": "你好", "voice": "bad-voice"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 10001
    assert fake_tts.calls == []


def test_synthesize_engine_failure(client: Any, fake_tts: FakeTtsClient) -> None:
    fake_tts.error = BizException(ErrorCode.TTS_FAILED, "语音合成失败，请稍后重试")
    resp = client.post(f"{API}/tts/synthesize", json={"text": "你好"})
    assert resp.status_code == 502
    assert resp.json()["code"] == 60002


def test_tts_cache_hit_no_regenerate(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """缓存命中不重复合成：同文本 + 同音色第二次不再触达真实合成（离线单测缓存逻辑）。"""
    from app.clients import tts_client

    monkeypatch.setattr(tts_client, "CACHE_DIR", tmp_path)
    calls: list[tuple[str, str]] = []

    def fake_generate(self: Any, text: str, voice: str) -> bytes:
        calls.append((text, voice))
        return b"generated-mp3"

    monkeypatch.setattr(tts_client.EdgeTtsClient, "_generate", fake_generate)

    c = tts_client.EdgeTtsClient()
    assert c.synthesize("同一段文案", DEFAULT_VOICE) == b"generated-mp3"
    assert c.synthesize("同一段文案", DEFAULT_VOICE) == b"generated-mp3"
    assert len(calls) == 1
    assert len(list(tmp_path.glob("*.mp3"))) == 1


# ---------- GET /tts/voices 与设置白名单 ----------


def test_voices_list_default_first(client: Any) -> None:
    """音色清单 14 条；账号未设置时默认音色（晓晓）置顶。"""
    resp = client.get(f"{API}/tts/voices")
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert len(items) == 14
    assert items[0]["id"] == DEFAULT_VOICE
    assert {"id", "name", "gender", "style"} <= set(items[0])


def test_voices_account_voice_first(client: Any) -> None:
    """账号所配音色置顶。"""
    client.put(f"{API}/settings", json={"tts_voice": "zh-HK-WanLungNeural"})
    items = client.get(f"{API}/tts/voices").json()["data"]
    assert len(items) == 14
    assert items[0]["id"] == "zh-HK-WanLungNeural"


def test_settings_tts_voice_whitelist(client: Any) -> None:
    """PUT /settings 的 tts_voice 白名单：非法值 → 10001。"""
    resp = client.put(f"{API}/settings", json={"tts_voice": "bad-voice"})
    assert resp.status_code == 400
    assert resp.json()["code"] == 10001
