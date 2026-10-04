"""语音接口：转写 / 合成 / 音色列表（接口文档 3.13）。

转写供应商与默认音色均取当前账号设置；上传音频不落库、合成产物落本地文件缓存。
"""

from collections.abc import Callable

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.clients.asr_client import AUDIO_MAX_BYTES, AsrClient, get_asr_client_factory
from app.clients.tts_client import TtsClient, get_tts_client
from app.database import get_db
from app.deps import get_current_user
from app.exceptions import BizException, ErrorCode
from app.models import User
from app.schemas.common import ApiResponse
from app.schemas.voice import TranscribeData, TtsSynthesizeRequest, VoiceItem
from app.services import voice_service

router = APIRouter(tags=["语音"])


@router.post("/asr/transcribe", response_model=ApiResponse[TranscribeData], summary="语音转写")
def transcribe(
    file: UploadFile = File(..., description="音频片段（webm / ogg / wav，≤2MB）"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    asr_factory: Callable[[str, str, str], AsrClient] = Depends(get_asr_client_factory),
) -> ApiResponse[TranscribeData]:
    """转写一段音频片段；供应商按账号设置（本地 FunASR / 讯飞云端），音频不落库。"""
    content = file.file.read(AUDIO_MAX_BYTES + 1)  # 多读 1 字节判超限，避免大文件全量入内存
    if not content:
        raise BizException(ErrorCode.PARAM_INVALID, "音频文件为空")
    if len(content) > AUDIO_MAX_BYTES:
        raise BizException(ErrorCode.PARAM_INVALID, "音频片段不能超过 2MB")
    result = voice_service.transcribe(db, current_user.id, content, asr_factory)
    return ApiResponse[TranscribeData](
        data=TranscribeData(text=result.text, duration_ms=result.duration_ms)
    )


@router.post("/tts/synthesize", summary="语音合成")
def synthesize(
    payload: TtsSynthesizeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    tts_client: TtsClient = Depends(get_tts_client),
) -> Response:
    """合成语音，返回 mp3 音频流（不走统一响应体）；失败返回标准错误体 + 60002。"""
    audio = voice_service.synthesize(db, current_user.id, payload.text, payload.voice, tts_client)
    return Response(content=audio, media_type="audio/mpeg")


@router.get("/tts/voices", response_model=ApiResponse[list[VoiceItem]], summary="音色列表")
def list_voices(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ApiResponse[list[VoiceItem]]:
    """全部中文音色清单；当前账号设置音色置顶。"""
    return ApiResponse[list[VoiceItem]](data=voice_service.list_voices(db, current_user.id))
