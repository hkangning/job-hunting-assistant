"""SSE 流式端点（事件协议见接口文档 1.4，实现要点见系统设计 5.1）。

- `/stream/demo`：协议自检端点（步骤 11），供前端 StreamText 组件联调与流式协议回归；
- `/stream/jd-analysis`：JD 匹配分析（步骤 12），首条完整业务链路——画像+JD 组装 prompt，
  AI 逐段产出五段报告，`section_splitter` 逐块标注段落，全文随流落库。

其余业务链路（陪练点评 / 模拟面试 / 面经复盘）后续步骤逐个加入本文件。

路由层只做协议转换：取登录态、校验入参、组装业务生成器、交给 `sse_response` 包装，不直接访问 ORM。
"""

import logging
import time
from collections.abc import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.clients.llm_client import LLMClient, get_llm_client, resolve_config
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.prompts import JD_ANALYSIS_SECTION_RULES
from app.schemas.stream import DemoChatRequest, JdAnalysisRequest
from app.services import jd_service
from app.utils.section_splitter import SectionSplitter
from app.utils.sse import SSE, sse_response

logger = logging.getLogger(__name__)

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


@router.post("/stream/jd-analysis", summary="JD 匹配分析（流式）")
def jd_analysis_stream(
    payload: JdAnalysisRequest,
    current_user: User = Depends(get_current_user),
    client: LLMClient = Depends(get_llm_client),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """画像 + JD 原文交给 AI 流式产出五段匹配报告：start → delta×N（逐段带 section）→ done(record_id)。

    报告全文随流自动落库（`report_text` 即所有 delta 的拼接，前端可据此渲染历史回看）。
    客户端中途断开时，已生成的内容同样落库并标记为未完成（接口文档 3.6），前端重新发起即可再次分析。
    """
    user_id = current_user.id
    jd_text = payload.jd_text
    application_id = payload.application_id
    # 关联投递的归属校验必须在流式响应建立之前完成（系统设计 5.1：入参校验先于流式建立）
    jd_service.ensure_application(db, user_id, application_id)

    def _run(stream_db: Session) -> Iterator[str]:
        config = resolve_config(stream_db, user_id)
        messages = jd_service.build_messages(stream_db, user_id, jd_text)
        splitter = SectionSplitter(JD_ANALYSIS_SECTION_RULES)
        pieces: list[str] = []
        try:
            for chunk in client.stream_chat(config, messages):
                for text, section in splitter.feed(chunk):
                    pieces.append(text)
                    yield SSE.delta(text, section)
            for text, section in splitter.flush():  # 收尾：吐出仍在缓冲的尾巴
                pieces.append(text)
                yield SSE.delta(text, section)
            record_id = jd_service.save_report(
                stream_db, user_id, jd_text, application_id, "".join(pieces)
            )
            return {"record_id": record_id}
        except GeneratorExit:
            # 客户端断连：已生成内容落库并标记为未完成后原样抛出（协议层靠它终止上游，系统设计 5.1）
            _save_partial(stream_db, user_id, jd_text, application_id, pieces)
            raise

    return sse_response(_run, start_message="正在分析你的 JD…")


def _save_partial(
    db: Session, user_id: int, jd_text: str, application_id: int | None, pieces: list[str]
) -> None:
    """断连兜底落库：以 is_finished=False 标记半成品（数据库设计 3.2）。"""
    if not pieces:
        return
    try:
        jd_service.save_report(
            db, user_id, jd_text, application_id, "".join(pieces), is_finished=False
        )
    except Exception:
        logger.exception("JD 分析半成品落库失败（账号 %s）", user_id)
