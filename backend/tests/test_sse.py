"""TC-99~104：SSE 协议层单测（步骤 11，系统设计 v1.18 §5.1 / 接口文档 v1.17 §1.4）。

**不经 HTTP**：协议层与 HTTP 解耦（后端「不继承 StreamingResponse」的决策正为此），
故手写 `work` 生成器直接喂给 `_drive`，断言产出的事件序列——比经 TestClient 读流更精确，
也不必起服务（台账 #43）。

**业务侧形态**：`work: (Session) -> Iterator[str]` 是同步生成器，`yield` 事件文本、
`return {"record_id", "extra"}` 作 done 载荷（协议层经 `yield from` 取回）。
"""

import json
from types import SimpleNamespace

import pytest

from app.exceptions import BizException, ErrorCode
from app.utils import sse as sse_module
from app.utils.sse import SSE, _drive


def _parse(raw: str) -> tuple[str, dict]:
    """按接口文档 1.4 的报文格式解析单条事件：`event: <名>\\ndata: <JSON>\\n\\n`。"""
    lines = raw.strip().split("\n")
    assert lines[0].startswith("event: "), f"报文首行应为 event：{raw!r}"
    assert lines[1].startswith("data: "), f"报文次行应为 data：{raw!r}"
    assert raw.endswith("\n\n"), f"报文应以空行结尾：{raw!r}"
    return lines[0][len("event: ") :], json.loads(lines[1][len("data: ") :])


def _events(work, start_message: str = "正在处理…") -> list[tuple[str, dict]]:
    """跑完整个流，返回 [(事件名, data), ...]（含协议层自发的 start / done）。"""
    return [_parse(raw) for raw in _drive(work, start_message)]


def _work(*event_texts, result=None):
    """构造业务生成器：按顺序产出给定事件文本，最后 return result。"""

    def _run(db):
        for text in event_texts:
            yield text
        return result

    return _run


# ---------- A 组：报文格式 ----------


def test_event_wire_format():
    """TC-99：报文固定 `event: <名>\\ndata: <JSON>\\n\\n`，与接口文档 1.4 逐字节一致。"""
    assert SSE.delta("你好") == 'event: delta\ndata: {"text": "你好"}\n\n'


def test_event_keeps_chinese_unescaped():
    """TC-99：data 为 UTF-8 JSON，中文不转义（前端无需二次解码）。"""
    assert "\\u" not in SSE.start("正在分析你的 JD…")
    assert "正在分析你的 JD…" in SSE.start("正在分析你的 JD…")


def test_delta_section_optional():
    """TC-99：`section` 仅在传入时下发——不传则 data 里没有该字段。"""
    _, without = _parse(SSE.delta("片段"))
    _, with_section = _parse(SSE.delta("片段", section="match_score"))

    assert "section" not in without
    assert with_section["section"] == "match_score"


def test_tool_call_payload():
    """TC-99：`tool_call` 带工具名与完整参数，供前端出确认卡片（步骤 19 消费）。"""
    name, data = _parse(SSE.tool_call("create_application", {"company": "满帮"}))

    assert name == "tool_call"
    assert data == {"tool_name": "create_application", "args": {"company": "满帮"}}


# ---------- B 组：事件顺序与 start 首发 ----------


def test_event_order_start_delta_done():
    """TC-100：事件顺序恒为 start → delta×N → done。"""
    events = _events(_work(SSE.delta("甲"), SSE.delta("乙"), result={"record_id": 7}))

    assert [name for name, _ in events] == ["start", "delta", "delta", "done"]
    assert "".join(d["text"] for name, d in events if name == "delta") == "甲乙"


def test_start_emitted_before_work_runs():
    """TC-100：`start` 先于一切——`work` 第一行就抛异常，`start` 仍已发出。

    界面的即时反馈（NFR-004：点击到反馈 <300ms）靠的就是这一点。
    """

    def _boom(db):
        raise RuntimeError("第一行就炸")
        yield  # 使其成为生成器函数

    events = _events(_boom)

    assert [name for name, _ in events] == ["start", "error"]


def test_start_message_passed_through():
    """TC-100：`start` 文案由调用方指定，各链路写各自的「正在分析…」。"""
    events = _events(_work(), start_message="正在分析你的 JD…")

    assert events[0] == ("start", {"message": "正在分析你的 JD…"})


# ---------- C 组：done 载荷 ----------


def test_done_payload_from_work_return():
    """TC-101：`done` 载荷取自 `work` 的 `return`——业务侧不拼报文。"""
    events = _events(_work(result={"record_id": 42, "extra": {"chars": 9}}))

    assert events[-1] == ("done", {"record_id": 42, "extra": {"chars": 9}})


def test_done_payload_defaults_when_no_return():
    """TC-101：`work` 无 `return` 时两项均为 null（自检端点即此形态）。"""
    assert _events(_work())[-1] == ("done", {"record_id": None, "extra": None})


# ---------- D 组：异常分派 ----------


def test_biz_exception_emits_its_code():
    """TC-102：`work` 抛 `BizException` → `error` 携带其 code（`LLMError` 是其子类）。"""

    def _run(db):
        yield SSE.delta("前半段")
        raise BizException(ErrorCode.LLM_KEY_MISSING)
        yield  # 使其成为生成器函数

    events = _events(_run)

    assert [name for name, _ in events] == ["start", "delta", "error"]
    assert events[-1][1]["code"] == ErrorCode.LLM_KEY_MISSING


def test_error_carries_message():
    """TC-102：`error` 同时下发 message，前端可直接展示。"""

    def _run(db):
        raise BizException(ErrorCode.LLM_KEY_MISSING, "API Key 无效或无权限，请前往 AI 配置页检查")
        yield

    assert _events(_run)[-1][1]["message"] == "API Key 无效或无权限，请前往 AI 配置页检查"


def test_unknown_exception_emits_10000(caplog):
    """TC-102：其余异常 → 记堆栈 + `error 10000`（不把内部细节透给前端）。"""

    def _run(db):
        raise ValueError("内部实现细节")
        yield

    with caplog.at_level("ERROR"):
        events = _events(_run)

    assert events[-1][1]["code"] == ErrorCode.INTERNAL_ERROR
    assert "内部实现细节" not in str(events[-1][1])  # 细节只进日志、不进响应
    assert any(record.levelno >= 40 for record in caplog.records)


def test_deltas_survive_error():
    """TC-102：中途失败时已发出的 `delta` 不撤回，且**不再发 `done`**（二者互斥）。"""

    def _run(db):
        yield SSE.delta("已渲染的")
        raise BizException(ErrorCode.LLM_CALL_FAILED)
        yield

    names = [name for name, _ in _events(_run)]

    assert names == ["start", "delta", "error"]
    assert "done" not in names


# ---------- E 组：客户端断连 ----------


def test_close_propagates_to_work():
    """TC-103：断连时 `GeneratorExit` 沿 `yield from` 传播到 `work`——上游据此停止消费 AI 流。"""
    finished = []

    def _run(db):
        try:
            for i in range(5):
                yield SSE.delta(str(i))
        finally:
            finished.append("work-finally")

    gen = _drive(_run, "正在生成…")
    next(gen)  # start
    next(gen)  # 第一个 delta
    gen.close()

    assert finished == ["work-finally"]


def test_generator_exit_reraised():
    """TC-103：协议层**不吞** `GeneratorExit`——吞掉就等于切不断上游（系统设计 5.1）。

    用 `throw` 而非 `close` 才能区分：重新抛出时该异常会传给调用方，吞掉则只得到 StopIteration。
    """
    gen = _drive(_work(SSE.delta("x")), "正在生成…")
    next(gen)

    with pytest.raises(GeneratorExit):
        gen.throw(GeneratorExit)


def test_no_events_after_close():
    """TC-103：断连后不再产事件（连接已不可写，接口文档 1.4）。"""
    gen = _drive(_work(SSE.delta("x")), "正在生成…")
    next(gen)
    gen.close()

    with pytest.raises(StopIteration):
        next(gen)


# ---------- F 组：独立会话 ----------


class _SpySession:
    """假会话：只观察 close 是否被调用（协议层自己管生命周期）。"""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def spy_session(monkeypatch) -> SimpleNamespace:
    """把协议层的 `SessionLocal` 换成 Spy：记录创建次数并返回同一个假会话。"""
    session = _SpySession()
    created: list[int] = []

    def _make() -> _SpySession:
        created.append(1)
        return session

    monkeypatch.setattr(sse_module, "SessionLocal", _make)
    return SimpleNamespace(session=session, created=created)


def test_session_created_and_closed(spy_session):
    """TC-104：协议层为每个流建**独立会话**（不复用请求级会话），流结束即关闭。"""
    list(_drive(_work(SSE.delta("x")), "正在生成…"))

    assert len(spy_session.created) == 1
    assert spy_session.session.closed is True


def test_session_closed_on_error_path(spy_session):
    """TC-104：异常路径同样关闭——会话不因中途失败而泄漏。"""

    def _run(db):
        raise BizException(ErrorCode.LLM_CALL_FAILED)
        yield

    list(_drive(_run, "正在生成…"))

    assert spy_session.session.closed is True
