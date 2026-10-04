"""语音转写客户端：FunASR 本地模型整段识别（默认）+ 讯飞 RTASR 实时转写（备选）（系统设计 5.6）。

- 音频解码与校验在 `decode_checked`（服务层调用）：PyAV 统一解 webm / ogg / wav / mp3 为
  16k 单声道 float32，顺带得出片段时长；客户端只负责「音频数组 → 文本」，音频**不落库**。
- `has_speech`：无有效语音信号的片段（纯静音 / 环境底噪）由服务层直接短路为空文本——
  非流式模型对这类输入会幻觉出「嗯没有没有」之类的假文本（实测），不过模型更稳。
- FunASR 模型进程内**单例 + 启动预热**（`warmup_asr_model`，main.py 启动钩子后台线程调用）：
  避免首次转写等冷加载；预热失败或未启用时首次转写仍会懒加载兜底；加载与推理用锁串行化；
  重依赖（av / numpy / funasr）一律函数内延迟导入，未安装时仅转写报错、不影响应用启动与测试。
- 注入点 `get_asr_client_factory()`：测试以 `app.dependency_overrides` 替换为替身工厂。
- 失败一律抛 `BizException`：音频不可用（不可解码 / 无音频流 / 空）→ 10001；
  转写引擎失败（模型不可用 / 讯飞未配凭据 / 云端异常）→ 60001。
"""

import base64
import hashlib
import hmac
import io
import json
import logging
import sys
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode

from app.exceptions import BizException, ErrorCode

logger = logging.getLogger(__name__)

TARGET_RATE = 16000  # 送模型 / 讯飞的统一采样率
AUDIO_MAX_BYTES = 2 * 1024 * 1024  # 单片段体积上限 2MB（接口文档 3.13）

FUNASR_MODEL = "paraformer-zh"  # FunASR 本地非流式模型（整段识别；首次自动下载到用户缓存目录）
SPEECH_RMS_THRESHOLD = 0.005  # 有效语音能量下限：整段 RMS 低于此值视为无语音（实测说话 ≥0.042、底噪 ≤0.010，两端留 4 倍余量）

XUNFEI_WS_URL = "wss://rtasr.xfyun.cn/v1/ws"
XUNFEI_FRAME_BYTES = 1280  # 讯飞建议的音频帧长度（40ms @ 16k 16bit）
XUNFEI_RECV_TIMEOUT = 30.0  # 单次接收超时（秒）


@dataclass(frozen=True)
class AsrResult:
    """一次转写的结果。"""

    text: str  # 转写文本（已去首尾空白）
    duration_ms: int  # 音频片段时长（毫秒，按解码后采样数推出）


def decode_audio(data: bytes) -> tuple[Any, int]:
    """解码任意音频字节 → (16k 单声道 float32 数组, 时长毫秒)。

    用 PyAV（ffmpeg 绑定）统一处理容器与编码：前端 MediaRecorder 的 webm / ogg、
    传统 wav / mp3 均通吃；无法解码或无音频流时抛原生异常，由调用方按参数错误处理。
    """
    import av  # 延迟导入：29MB 级重依赖，只在转写时加载
    import numpy as np

    with av.open(io.BytesIO(data)) as container:
        if not container.streams.audio:
            raise ValueError("文件中没有音频流")
        resampler = av.AudioResampler(format="flt", layout="mono", rate=TARGET_RATE)
        chunks: list[Any] = []
        for frame in container.decode(container.streams.audio[0]):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):  # 冲净重采样器缓冲，避免尾部丢样本
            chunks.append(out.to_ndarray().reshape(-1))
    audio = (
        np.concatenate(chunks).astype(np.float32)
        if chunks
        else np.zeros(0, dtype=np.float32)
    )
    return audio, int(round(audio.size / TARGET_RATE * 1000))


def to_pcm16(audio: Any) -> bytes:
    """float32 [-1, 1] → 16bit 小端 PCM 字节（讯飞 RTASR 的输入格式）。"""
    import numpy as np

    return (audio * 32767).clip(-32768, 32767).astype(np.int16).tobytes()


def decode_checked(audio: bytes) -> tuple[Any, int]:
    """解码 + 校验上传音频，返回 (16k 单声道 float32 数组, 时长毫秒)。

    不可解码 / 无音频流 / 空音频一律 10001（参数类错误，与引擎无关，故置于客户端之外）。
    """
    try:
        samples, duration_ms = decode_audio(audio)
    except Exception as exc:  # PyAV 的 InvalidDataError / ValueError 等
        raise BizException(ErrorCode.PARAM_INVALID, "音频格式不支持或文件已损坏") from exc
    if samples.size == 0:
        raise BizException(ErrorCode.PARAM_INVALID, "音频片段为空")
    return samples, duration_ms


def has_speech(samples: Any) -> bool:
    """片段里是否含有效语音信号（整段 RMS 与阈值比较）。

    用途：误触录音 / 只录到环境底噪的片段——非流式模型对这类输入会幻觉输出
    （实测静音 1.5s 被转出「嗯没有没有」），服务层据此短路为空文本、不进模型。
    """
    import numpy as np

    if samples.size == 0:
        return False
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))
    return rms >= SPEECH_RMS_THRESHOLD


class AsrClient(ABC):
    """转写客户端抽象：按账号配置选用实现（默认本地 FunASR、可选讯飞云端）。"""

    @abstractmethod
    def transcribe(self, samples: Any) -> str:
        """转写一段 16k 单声道 float32 音频，返回文本；失败抛 BizException（60001）。"""


_model: Any = None  # FunASR 模型单例（进程内；启动预热加载，未启用或预热失败时首次转写懒加载）
_model_lock = threading.Lock()  # 首次加载互斥
_infer_lock = threading.Lock()  # 推理串行化（模型内部有状态，防并发竞争）


def _get_model() -> Any:
    """取 FunASR 模型单例：首次调用加载（含模型下载），之后复用。"""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from funasr import AutoModel  # 延迟导入：含 torch，导入与加载都重

                _model = AutoModel(
                    model=FUNASR_MODEL,
                    disable_update=True,  # 不联网检查更新
                    disable_pbar=True,
                    device="cpu",
                )
    return _model


def warmup_asr_model() -> None:
    """应用启动后后台预热：提前加载模型，省去首次转写的冷加载等待（约 5 秒，模型已下载时）。

    由 main.py 启动钩子在后台线程调用（开关 `ASR_WARMUP_ENABLED`）；失败仅告警，
    首次转写时仍会懒加载兜底。测试进程直接跳过——测试计划约定语音用例走替身、
    不加载真模型（也避免在未下载模型的机器上跑测试时误触发联网下载）。
    """
    if "pytest" in sys.modules:
        return
    try:
        _get_model()
        logger.info("语音转写模型预热完成")
    except Exception as exc:
        logger.warning("语音转写模型预热失败（首次转写时将重试）：%s", exc)


class FunAsrClient(AsrClient):
    """FunASR 本地转写（默认）：进程内推理、不出网；片段整段识别，长录音由前端切段覆盖。"""

    def transcribe(self, samples: Any) -> str:
        try:
            model = _get_model()
            with _infer_lock:
                return _run_inference(model, samples)
        except BizException:
            raise
        except Exception as exc:
            raise BizException(ErrorCode.ASR_FAILED, "本地语音模型转写失败") from exc


def _run_inference(model: Any, samples: Any) -> str:
    """整段一次送入模型，返回识别文本（已去空白）。

    输入已由前端 VAD 切成 3~15 秒短句，非流式模型整段识别、一次给出全文——实测同音频下
    质量优于流式模型的整段调用（技术词误识更少）、速度不降；输出逐字间带空格，此处一并去除。
    """
    res = model.generate(input=samples, batch_size_s=300)
    text = res[0].get("text") if res else ""
    return "".join((text or "").split())


class XunfeiAsrClient(AsrClient):
    """讯飞 RTASR 实时转写（备选）：WebSocket 推流云端识别，需账号配置凭据。

    协议按官方文档实现（签名 URL + base64 音频帧 + 结束帧），**未经真实凭据联调**，
    上线前需用有效凭据实测一遍；测试计划以替身覆盖，不阻塞用例（TC-31）。
    """

    def __init__(self, app_id: str, api_key: str):
        self._app_id = app_id
        self._api_key = api_key

    def transcribe(self, samples: Any) -> str:
        try:
            return self._run_rtasr(to_pcm16(samples))
        except BizException:
            raise
        except Exception as exc:
            raise BizException(ErrorCode.ASR_FAILED, "讯飞语音转写失败") from exc

    def _run_rtasr(self, pcm: bytes) -> str:
        from websockets.exceptions import ConnectionClosed
        from websockets.sync.client import connect

        pieces: list[str] = []
        with connect(_signed_url(self._app_id, self._api_key), open_timeout=10, close_timeout=5) as ws:
            for offset in range(0, len(pcm), XUNFEI_FRAME_BYTES):
                ws.send(
                    json.dumps(
                        {
                            "end": False,
                            "audio": base64.b64encode(pcm[offset : offset + XUNFEI_FRAME_BYTES]).decode(),
                        }
                    )
                )
            ws.send(json.dumps({"end": True}))
            while True:  # 服务端处理完会主动关闭连接
                try:
                    message = ws.recv(timeout=XUNFEI_RECV_TIMEOUT)
                except (ConnectionClosed, TimeoutError):
                    break
                data = json.loads(message)
                if data.get("action") == "error":
                    raise ValueError(f"讯飞返回错误：{data.get('code')} {data.get('desc')}")
                if data.get("action") != "result":
                    continue
                st = (json.loads(data.get("data") or "{}").get("cn") or {}).get("st") or {}
                if st.get("type") == "0":  # type=0 断句结果（type=1 为中间结果，丢弃）
                    pieces.append(_extract_text(st))
        return "".join(pieces).strip()


def _signed_url(app_id: str, api_key: str) -> str:
    """生成带签名的 RTASR 连接地址：signa = base64(hmac_sha1(api_key, md5(app_id + ts)))。"""
    ts = str(int(time.time()))
    origin = hashlib.md5((app_id + ts).encode()).hexdigest()
    signa = base64.b64encode(
        hmac.new(api_key.encode(), origin.encode(), hashlib.sha1).digest()
    ).decode()
    return f"{XUNFEI_WS_URL}?{urlencode({'appid': app_id, 'ts': ts, 'signa': signa})}"


def _extract_text(st: dict) -> str:
    """从讯飞结果块 `cn.st` 中拼出文本（rt → ws → cw → w 四层结构）。"""
    parts: list[str] = []
    for rt in st.get("rt") or []:
        for word_seg in rt.get("ws") or []:
            for cw in word_seg.get("cw") or []:
                if cw.get("w"):
                    parts.append(cw["w"])
    return "".join(parts)


def build_asr_client(provider: str, app_id: str, api_key: str) -> AsrClient:
    """按账号配置构造转写客户端（生产实现；测试经注入点整体替换）。"""
    if provider == "xunfei":
        if not app_id or not api_key:
            raise BizException(ErrorCode.ASR_FAILED, "未配置讯飞语音凭据，请前往设置页填写")
        return XunfeiAsrClient(app_id, api_key)
    if provider == "funasr":
        return FunAsrClient()
    raise BizException(ErrorCode.ASR_FAILED, f"语音供应商配置异常：{provider}")


def get_asr_client_factory() -> Callable[[str, str, str], AsrClient]:
    """FastAPI 依赖注入点：返回「按供应商构造客户端」的工厂。

    转写实现随**账号配置**（`asr_provider`）而变，故注入工厂而非单例客户端——
    测试替换后 funasr / xunfei 两个分支都被替身接管（测试计划 1.3）。
    """
    return build_asr_client
