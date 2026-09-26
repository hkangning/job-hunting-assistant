"""SSE 流式协议层：事件格式统一封装与流式响应驱动器（系统设计 5.1，接口文档 1.4）。

四条不变式由本模块保证，业务侧只管产出内容：

1. 进入生成器后**立即**推 `start`——用户点击到界面反馈 <300ms，覆盖 LLM 首字前的静默等待（NFR-004）；
2. 每个流式请求持有**独立 DB session**（不与请求级 session 混用），流结束即关闭；
3. 中途异常统一转 `error` 事件——`BizException` 取其 code，未知异常记堆栈后回 10000；
   已发出的 delta **不撤回**（前端保留已渲染内容并显示重试）；
4. 客户端断连（生成器被 `close()` → `GeneratorExit`）**原样抛出、不再写事件**，
   半成品落库由业务侧在自身 `finally` 中完成（系统设计 5.1）。

业务侧写法（同步生成器：`yield` 事件、`return` 作为 done 载荷）：

    def _run(db: Session) -> Iterator[str]:
        for piece in client.stream_chat(config, messages):
            yield SSE.delta(piece)
        return {"record_id": save(db, ...)}

    return sse_response(_run, start_message="正在分析你的 JD…")
"""

import json
import logging
from collections.abc import Callable, Iterator

from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

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
    def done(record_id: int | None = None, extra: dict | None = None) -> str:
        """流正常结束：携带落库记录 id 与附加数据（前端据此刷新列表/跳转）。"""
        return _event("done", {"record_id": record_id, "extra": extra})

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
        payload = yield from work(db)
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
        yield SSE.done(result.get("record_id"), result.get("extra"))
    finally:
        db.close()


def _event(name: str, data: dict) -> str:
    """序列化为 SSE 报文：`event: <名>\\ndata: <单行 JSON>\\n\\n`（中文不转义，UTF-8 直出）。"""
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
