"""SSE 流式协议层：事件格式统一封装与流式响应驱动器（系统设计 5.1，接口文档 1.4）。

四条不变式由本模块保证，业务侧只管产出内容：

1. 进入生成器后**立即**推 `start`——用户点击到界面反馈 <300ms，覆盖 LLM 首字前的静默等待（NFR-004）；
2. 每个流式请求持有**独立 DB session**（不与请求级 session 混用），流结束即关闭；
3. 中途异常统一转 `error` 事件——`BizException` 取其 code，未知异常记堆栈后回 10000；
   已发出的 delta **不撤回**（前端保留已渲染内容并显示重试）；
4. 客户端断连（生成器被 `close()` → `GeneratorExit`）**原样抛出、不再写事件**，
   半成品落库由业务侧在自身 `finally` 中完成（系统设计 5.1）。

另有一层**输出节奏器**（`_Pacer`）：模型吐块又快又大时观感像"块状喷射"，协议层把
delta 的文本按 `settings.sse_pace_cps` 字/秒切成 1~4 字的小步缓释、标点后附加停顿；
**只对超前等待**（上游本就慢时零额外延迟）、首块不等待（首字延迟不受影响，NFR-001）。
只重排 delta 的内部切分，事件序列、`return` 载荷与断连语义不变；结构化段
（`_PACE_EXEMPT_SECTIONS`，一次性 JSON）整块直通，保持"一个 delta 即完整 JSON"的段契约。

业务侧写法（同步生成器：`yield` 事件、`return` 作为 done 载荷）：

    def _run(db: Session) -> Iterator[str]:
        for piece in client.stream_chat(config, messages):
            yield SSE.delta(piece)
        return {"record_id": save(db, ...)}

    return sse_response(_run, start_message="正在分析你的 JD…")
"""

import json
import logging
import random
import time
from collections.abc import Callable, Iterator

from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.exceptions import BizException, ErrorCode

logger = logging.getLogger(__name__)

SSE_MEDIA_TYPE = "text/event-stream"

# 关闭中间层缓冲：nginx 默认会攒批文本响应，逐字输出会退化成一次性吐出（V2 部署走 nginx）
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


class SSE:
    """事件构造器：与接口文档 1.4 的事件协议逐字段对应，业务侧 `yield` 其返回值即可。"""

    @staticmethod
    def start(message: str) -> str:
        """连接建立后立即推送的状态文案（感知延迟优化）。"""
        return _event("start", {"message": message})

    @staticmethod
    def delta(text: str, section: str | None = None) -> str:
        """LLM 增量文本；`section` 标识当前报告段落，仅分段输出的链路传（不传则不下发该字段）。"""
        data: dict = {"text": text}
        if section:
            data["section"] = section
        return _event("delta", data)

    @staticmethod
    def tool_call(tool_name: str, args: dict) -> str:
        """Agent 工具调用（仅 /stream/agent-chat）：参数完整后立即推送，前端据此出确认卡片。"""
        return _event("tool_call", {"tool_name": tool_name, "args": args})

    @staticmethod
    def done(record_id: int | None = None, extra: dict | None = None, seq: int | None = None) -> str:
        """流正常结束：携带落库记录 id 与附加数据（前端据此刷新列表/跳转）。

        `seq` 仅序号语义的链路传（模拟面试的题序，前端据此校准题号；不传则不下发该字段）。
        """
        data: dict = {"record_id": record_id, "extra": extra}
        if seq is not None:
            data["seq"] = seq
        return _event("done", data)

    @staticmethod
    def error(code: int | ErrorCode, message: str) -> str:
        """中途失败：code 取自接口文档 1.3 错误码表，前端提示并显示重试入口。"""
        return _event("error", {"code": int(code), "message": message})


def sse_response(
    work: Callable[[Session], Iterator[str]], *, start_message: str
) -> StreamingResponse:
    """把业务生成器包装为 SSE 响应（系统设计 5.1）。

    `work` 接收本请求独占的 DB session，逐条 `yield` 事件文本；其 `return` 值（可选，
    形如 `{"record_id": int | None, "extra": dict | None}`）作为 `done` 载荷。
    """
    return SSEStreamingResponse(
        _drive(work, start_message), media_type=SSE_MEDIA_TYPE, headers=SSE_HEADERS
    )


class SSEStreamingResponse(StreamingResponse):
    """SSE 响应：保证客户端断连时**显式关闭**业务生成器（步骤 12 修复）。

    Starlette 对同步生成器用 `iterate_in_threadpool` 包装，该包装在连接断开时只停止拉取、
    **不关闭**底层生成器——生成器会挂在 `yield` 处直到被 GC，`GeneratorExit` 迟迟不到，
    业务侧 `finally`（半成品落库、上游连接释放）随之失效（步骤 12 自测实测：断连后半个字都没落库）。
    这里在响应结束时补一次 `close()`（幂等，正常跑完的生成器再关无副作用），
    让 `GeneratorExit` 沿 `yield from` 链如期传到业务生成器。
    """

    def __init__(self, source: Iterator[str], **kwargs) -> None:
        self._source = source
        super().__init__(source, **kwargs)

    async def stream_response(self, send) -> None:
        try:
            await super().stream_response(send)
        finally:
            try:
                # 必须同步调用：断连在 spec_version 2.3 下走 cancel scope，此时 finally 里任何 await
                # 都会被立刻取消（close 就白写了）；同步代码打不断，才能真正执行到。代价是落库会让
                # 事件循环阻塞几十毫秒——只在断连路径发生，换取"兜底一定生效"。
                self._source.close()
            except Exception:
                # 客户端已断，这里再抛也没处报错，记日志即可（勿顶掉原始断连信号）
                logger.exception("SSE 业务生成器关闭失败")


def _drive(work: Callable[[Session], Iterator[str]], start_message: str) -> Iterator[str]:
    """驱动器：start 立即推 → 转发业务事件 → 正常结束发 done / 异常发 error。"""
    db = SessionLocal()
    try:
        yield SSE.start(start_message)
        source = work(db)
        cps = settings.sse_pace_cps
        payload = yield from (_paced(source, cps=cps) if cps > 0 else source)
    except GeneratorExit:
        # 客户端断连：连接已不可写，不再产事件；业务侧 finally 负责落半成品（系统设计 5.1）
        logger.info("SSE 客户端断连，终止流式生成")
        raise
    except BizException as exc:
        yield SSE.error(exc.code, exc.message)
    except Exception:
        logger.exception("SSE 流式处理未捕获异常")
        yield SSE.error(ErrorCode.INTERNAL_ERROR, ErrorCode.INTERNAL_ERROR.default_message)
    else:
        result = payload or {}
        yield SSE.done(result.get("record_id"), result.get("extra"), result.get("seq"))
    finally:
        db.close()


def _event(name: str, data: dict) -> str:
    """序列化为 SSE 报文：`event: <名>\\ndata: <单行 JSON>\\n\\n`（中文不转义，UTF-8 直出）。"""
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------- 输出节奏（2026-09-30） ----------

_DELTA_EVENT_PREFIX = "event: delta\n"  # `_event` 对 delta 的报文前缀（节奏器据此识别文本事件）

# 结构化段（一次性 JSON，前端整体解析）：整块直通、不拆步——拆碎会破坏「一个 delta 即完整 JSON」的段契约
_PACE_EXEMPT_SECTIONS = frozenset({"dimensions", "next_choices", "wrong_candidates", "tool_call"})

_PACE_STEP = (1, 4)  # 小步步长范围（字）：随机步长让出字连续、不机械
_PACE_PAUSE: dict[str, float] = {  # 标点后的停顿（秒）：逗号轻停、句末重停、换行最重
    "，": 0.10, ",": 0.10, "、": 0.10, "：": 0.10, ":": 0.10, "；": 0.12, ";": 0.12,
    "。": 0.18, ".": 0.18, "！": 0.18, "!": 0.18, "？": 0.18, "?": 0.18,
    "\n": 0.24,
}


class _Pacer:
    """delta 文本的节奏器：按「应发时刻」记账，把文本以小步缓释出去（每个流一个实例）。

    - 基础速率 `cps` 字/秒（小步 1~4 字、步长随机），标点后附加停顿；
    - **只对超前等待**——上游（LLM）本就慢于节奏时零额外延迟，总时长趋近
      max(上游速度, 节奏)；首个小步不等待（首字延迟不受影响，NFR-001）；
    - 只做时间与切分，不改文本内容（小步拼接恒等于原 delta 文本）。
    """

    def __init__(self, cps: float) -> None:
        self._cps = cps
        self._due: float | None = None  # 下一小步的应发时刻（monotonic）；None = 流刚开始

    def feed(self, text: str) -> Iterator[str]:
        """把一段 delta 文本切成小步逐步释放（步间按节奏 sleep）。"""
        for piece, pause in _split_steps(text):
            self._wait()
            yield piece
            self._due += len(piece) / self._cps + pause

    def _wait(self) -> None:
        now = time.monotonic()
        if self._due is None or self._due < now:
            self._due = now  # 上游落后于节奏：对齐到现在，不追补、不额外延迟
        elif self._due > now:
            time.sleep(self._due - now)


def _split_steps(text: str) -> Iterator[tuple[str, float]]:
    """切小步：遇标点即切（附停顿秒数），否则攒到随机步长上限再切。"""
    buf: list[str] = []
    limit = random.randint(*_PACE_STEP)
    for char in text:
        buf.append(char)
        pause = _PACE_PAUSE.get(char, 0.0)
        if pause or len(buf) >= limit:
            yield "".join(buf), pause
            buf = []
            limit = random.randint(*_PACE_STEP)
    if buf:
        yield "".join(buf), 0.0


def _paced(events: Iterator[str], *, cps: float) -> Iterator[str]:
    """给业务事件流套输出节奏：delta 的文本作小步缓释，其余事件原样直通。

    只重排 delta 的切分（拼接内容不变），事件序列与业务生成器的 `return` 载荷原样透传；
    结构化段（`_PACE_EXEMPT_SECTIONS`，一次性 JSON）整块直通，拆碎会破坏其段契约。
    断连（`GeneratorExit`）时显式 `close()` 上游，保证业务侧 `finally`（半成品落库、
    上游连接释放）如期执行——与直接 `yield from work(db)` 的传播语义一致。
    """
    pacer = _Pacer(cps)
    while True:
        try:
            event = next(events)
        except StopIteration as stop:
            return stop.value
        except GeneratorExit:
            events.close()
            raise
        if not event.startswith(_DELTA_EVENT_PREFIX):
            yield event
            continue
        data = _parse_delta(event)
        section = data.get("section")
        if section in _PACE_EXEMPT_SECTIONS:
            yield event
            continue
        for piece in pacer.feed(str(data.get("text") or "")):
            yield SSE.delta(piece, section)


def _parse_delta(event: str) -> dict:
    """从 delta 事件报文取回 data 字典（本模块 `_event` 的格式受控，取 data 行解析即可）。"""
    for line in event.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: "):])
    return {}
