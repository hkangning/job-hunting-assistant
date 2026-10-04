"""语音合成客户端：edge-tts 在线合成 + 本地文件缓存（系统设计 5.6）。

- 音色表静态内置（中文音色 14 个，按 `edge_tts` 实测清单维护），默认音色（晓晓）置顶；
  `GET /tts/voices` 直接下发，`PUT /settings` 与合成接口按同表校验。
- 缓存：`backend/cache/tts/<sha1(text + voice)>.mp3`，重复文本重复播报零出网（断网可复播已有语音）。
- **唯一出网点下沉为私有 `_generate`**：便于离线单测缓存命中路径（替换该方法即可）。
- 注入点 `get_tts_client()`：测试以 `app.dependency_overrides` 替换为替身（测试计划 1.3）。
- 合成失败（网络 / 服务端异常）一律 60002，前端静默降级为纯文字。
"""

import asyncio
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.exceptions import BizException, ErrorCode

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "tts"  # backend/cache/tts

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"  # 默认音色（晓晓）


@dataclass(frozen=True)
class VoiceMeta:
    """一个可选音色的元数据。"""

    id: str  # 音色名（合成时传入的 voice）
    name: str  # 中文显示名
    gender: str  # 性别：Female / Male
    style: str  # 风格说明（设置页展示用）


# 中文音色清单（2026-10-04 按 edge_tts 实测核对：大陆 8 + 粤语 3 + 台湾 3）
VOICES: tuple[VoiceMeta, ...] = (
    VoiceMeta("zh-CN-XiaoxiaoNeural", "晓晓", "Female", "温暖亲和，通用首选"),
    VoiceMeta("zh-CN-XiaoyiNeural", "晓伊", "Female", "活泼轻快"),
    VoiceMeta("zh-CN-YunxiNeural", "云希", "Male", "阳光自然"),
    VoiceMeta("zh-CN-YunyangNeural", "云扬", "Male", "新闻播报腔"),
    VoiceMeta("zh-CN-YunjianNeural", "云健", "Male", "沉稳有力"),
    VoiceMeta("zh-CN-YunxiaNeural", "云夏", "Male", "童声清亮"),
    VoiceMeta("zh-CN-liaoning-XiaobeiNeural", "晓北", "Female", "东北口音"),
    VoiceMeta("zh-CN-shaanxi-XiaoniNeural", "晓妮", "Female", "陕西口音"),
    VoiceMeta("zh-HK-HiuGaaiNeural", "曉佳", "Female", "粤语女声，亲和"),
    VoiceMeta("zh-HK-HiuMaanNeural", "曉曼", "Female", "粤语女声，沉稳"),
    VoiceMeta("zh-HK-WanLungNeural", "雲龍", "Male", "粤语男声"),
    VoiceMeta("zh-TW-HsiaoChenNeural", "曉臻", "Female", "台湾国语女声"),
    VoiceMeta("zh-TW-HsiaoYuNeural", "曉雨", "Female", "台湾国语女声，轻快"),
    VoiceMeta("zh-TW-YunJheNeural", "雲哲", "Male", "台湾国语男声"),
)

VOICE_IDS = frozenset(voice.id for voice in VOICES)  # 校验用音色名集合


class TtsClient(ABC):
    """合成客户端抽象：生产实现为 edge-tts，测试替换为替身。"""

    @abstractmethod
    def synthesize(self, text: str, voice: str) -> bytes:
        """合成一段语音，返回 mp3 字节；失败抛 BizException（60002）。"""


class EdgeTtsClient(TtsClient):
    """edge-tts 在线合成 + 文件缓存：同文本同音色直接读缓存、零出网。"""

    def synthesize(self, text: str, voice: str) -> bytes:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = CACHE_DIR / f"{_cache_key(text, voice)}.mp3"
        if path.exists():
            return path.read_bytes()
        try:
            data = self._generate(text, voice)
        except BizException:
            raise
        except Exception as exc:
            raise BizException(ErrorCode.TTS_FAILED, "语音合成失败，请稍后重试") from exc
        if not data:
            raise BizException(ErrorCode.TTS_FAILED, "语音合成失败，请稍后重试")
        path.write_bytes(data)
        return data

    def _generate(self, text: str, voice: str) -> bytes:
        """真正出网的合成步骤（独立方法：单测替换即可离线验证缓存逻辑）。"""
        import edge_tts

        async def _collect() -> bytes:
            chunks: list[bytes] = []
            async for chunk in edge_tts.Communicate(text, voice).stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    chunks.append(chunk["data"])
            return b"".join(chunks)

        # 同步端点运行在线程池中，该线程无运行中的事件循环，asyncio.run 安全
        return asyncio.run(_collect())


def _cache_key(text: str, voice: str) -> str:
    """缓存键 = sha1(text + voice)；以换行分隔防「跨字段拼接」歧义。"""
    return hashlib.sha1(f"{text}\n{voice}".encode("utf-8")).hexdigest()


def get_tts_client() -> TtsClient:
    """FastAPI 依赖注入点：默认返回 edge-tts 实现；测试替换为替身（测试计划 1.3）。"""
    return EdgeTtsClient()
