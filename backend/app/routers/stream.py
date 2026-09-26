"""SSE 流式端点（事件协议见接口文档 1.4，实现要点见系统设计 5.1）。

本步（步骤 11）交付**协议自检端点**，供前端 StreamText 组件联调与流式协议回归；
四条业务链路（JD 分析 / 陪练点评 / 模拟面试 / 面经复盘）自步骤 12 起逐个加入本文件。

路由层只做协议转换：取登录态、组装业务生成器、交给 `sse_response` 包装，不直接访问 ORM。
"""

import time
from collections.abc import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.clients.llm_client import LLMClient, get_llm_client, resolve_config
from app.deps import get_current_user
from app.models import User
from app.schemas.stream import DemoChatRequest
from app.utils.sse import SSE, sse_response

router = APIRouter(tags=["流式"])

DEMO_SYSTEM_PROMPT = "你是求职助手，请用中文简洁回答（200 字以内）。"


@router.post("/stream/demo", summary="流式协议自检（前端联调用）")
def demo_stream(
    payload: DemoChatRequest,
    current_user: User = Depends(get_current_user),
    client: LLMClient = Depends(get_llm_client),
) -> StreamingResponse:
    """把输入交给当前账号配置的 AI 流式回答：start → delta×N → done。

    不落库、不产生业务数据；`done.extra` 回报字数与首字/总耗时，供手工核对首字延迟（NFR-001）。
    """
    user_id = current_user.id
    started = time.perf_counter()

    def _run(db: Session) -> Iterator[str]:
        config = resolve_config(db, user_id)
        messages = [
            {"role": "system", "content": DEMO_SYSTEM_PROMPT},
            {"role": "user", "content": payload.message},
        ]
        chars = 0
        first_token_ms: int | None = None
        for piece in client.stream_chat(config, messages):
            if first_token_ms is None:
                first_token_ms = _ms_since(started)
            chars += len(piece)
            yield SSE.delta(piece)
        return {
            "extra": {"chars": chars, "first_token_ms": first_token_ms, "elapsed_ms": _ms_since(started)}
        }

    return sse_response(_run, start_message="正在生成回复…")


def _ms_since(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
