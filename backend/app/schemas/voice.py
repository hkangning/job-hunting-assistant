"""语音链路 DTO（接口文档 3.13）。"""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

TtsText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class TranscribeData(BaseModel):
    """转写结果。"""

    text: str = Field(description="转写文本（识别为空时为空白串）")
    duration_ms: int = Field(description="音频片段时长（毫秒，按解码后采样数推出）")


class TtsSynthesizeRequest(BaseModel):
    """语音合成请求体（POST /tts/synthesize）。"""

    text: TtsText = Field(description="待合成文本（strip 后 1~2000 字）")
    voice: str | None = Field(
        default=None, description="音色名（可省略，缺省用账号设置音色）；传值必须在音色清单内，否则 10001"
    )


class VoiceItem(BaseModel):
    """音色元数据（GET /tts/voices 列表项）。"""

    id: str = Field(description="音色名（合成时传入的 voice）")
    name: str = Field(description="中文显示名")
    gender: str = Field(description="性别：Female / Male")
    style: str = Field(description="风格说明（设置页展示用）")
