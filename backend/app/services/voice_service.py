"""语音链路业务：转写、合成、音色列表（接口文档 3.13，系统设计 5.6）。

- 转写按账号配置的供应商构造客户端（缺省本地 FunASR）；讯飞凭据**仅在选用讯飞时**解密。
- 合成音色缺省取账号设置；显式传入的音色必须命中静态音色表（10001）。
- 音频不落库；合成产物由 `tts_client` 落文件缓存（`backend/cache/tts/`）。
"""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.asr_client import AsrClient, AsrResult, decode_checked, has_speech
from app.clients.tts_client import DEFAULT_VOICE, VOICES, VOICE_IDS, TtsClient
from app.database import ACCOUNT_CONFIG
from app.exceptions import BizException, ErrorCode
from app.models import Config
from app.schemas.voice import VoiceItem
from app.utils.security import decrypt_text

ASR_PROVIDER_DEFAULT = ACCOUNT_CONFIG["asr_provider"]  # 缺省供应商：本地 FunASR


def transcribe(
    db: Session, user_id: int, audio: bytes, factory: Callable[[str, str, str], AsrClient]
) -> AsrResult:
    """转写一段音频（POST /asr/transcribe）：先解码校验，再按账号配置选供应商转写。

    无有效语音信号的片段（误触录音 / 仅环境底噪）直接返回空文本、不进引擎——
    非流式模型对静音会幻觉输出（实测「嗯没有没有」）。
    """
    samples, duration_ms = decode_checked(audio)
    if not has_speech(samples):
        return AsrResult(text="", duration_ms=duration_ms)
    cfg = _load_account_config(db, user_id)
    provider = (cfg.get("asr_provider") or ASR_PROVIDER_DEFAULT).strip()
    app_id = api_key = ""
    if provider == "xunfei":  # 仅选用讯飞时才解密凭据（损坏凭据不阻塞本地转写）
        app_id = _decrypt_credential(cfg.get("asr_app_id"))
        api_key = _decrypt_credential(cfg.get("asr_api_key"))
    text = factory(provider, app_id, api_key).transcribe(samples)
    return AsrResult(text=text, duration_ms=duration_ms)


def synthesize(db: Session, user_id: int, text: str, voice: str | None, client: TtsClient) -> bytes:
    """合成语音（POST /tts/synthesize）：音色缺省取账号设置，显式传值须命中音色表。"""
    if voice is None:
        voice = _account_voice(db, user_id)
    else:
        voice = voice.strip()
        if voice not in VOICE_IDS:
            raise BizException(ErrorCode.PARAM_INVALID, "音色不存在，请在设置页重新选择")
    return client.synthesize(text, voice)


def list_voices(db: Session, user_id: int) -> list[VoiceItem]:
    """音色列表（GET /tts/voices）：当前账号设置音色置顶，其余保持清单顺序。"""
    current = _account_voice(db, user_id)
    return [
        VoiceItem(id=v.id, name=v.name, gender=v.gender, style=v.style)
        for v in sorted(VOICES, key=lambda v: 0 if v.id == current else 1)
    ]


# ---------- 内部工具 ----------


def _load_account_config(db: Session, user_id: int) -> dict[str, str]:
    """取当前账号的语音相关配置键（跳过空值行，走默认兜底）。"""
    rows = db.scalars(
        select(Config).where(
            Config.user_id == user_id,
            Config.key.in_(("asr_provider", "asr_app_id", "asr_api_key", "tts_voice")),
        )
    ).all()
    return {row.key: row.value for row in rows if row.value}


def _account_voice(db: Session, user_id: int) -> str:
    """账号设置音色；未设置或值非法（历史数据）时兜底全局默认音色。"""
    value = db.scalar(
        select(Config.value).where(Config.user_id == user_id, Config.key == "tts_voice")
    )
    voice = (value or "").strip()
    return voice if voice in VOICE_IDS else DEFAULT_VOICE


def _decrypt_credential(cipher: str | None) -> str:
    """解密讯飞凭据；密文损坏时按「凭据不可用」处理（60001），不抛 Key 类错误码。"""
    if not cipher:
        return ""
    try:
        return decrypt_text(cipher)
    except BizException as exc:
        raise BizException(ErrorCode.ASR_FAILED, "讯飞语音凭据解析失败，请前往设置页重新填写") from exc
