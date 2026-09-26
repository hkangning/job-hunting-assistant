"""TC-20、TC-32：JD 匹配分析（步骤 12，接口文档 v1.18 §3.6）。

分四组：A 段落切分器（纯函数）、B 分数提取（纯函数）、C 落库与查询（服务层 + API）、
D 流式端点（TestClient，验端到端与校验顺序）。

**A / B 组直测纯函数**——`section_splitter` 与 `utils/sse.py` 同为协议层工具、零业务依赖，
不经 HTTP 也不碰数据库（台账 #45 点明了这条路）。

**fixture 用法**：服务层用例用 `db_session` / `account_id`，API 用例用 `client` / `account`，
两者**不混用**——它们各自会清库，混用会互相踩（`test_llm_providers.py` 的 `_row_count` 是既有先例）。
"""

import json
import random

import pytest
from fastapi.testclient import TestClient

from app.exceptions import BizException, ErrorCode
from app.prompts import JD_ANALYSIS_SECTION_RULES
from app.services import jd_service
from app.utils.section_splitter import SectionSplitter

API = "/api/v1"

# 一段带全部五个标题的样例报告（与 prompts.py 的关键词表对应）
SAMPLE_REPORT = """## 1. 综合匹配度评分
综合匹配度：85 分

## 2. 分项评分
技术栈 40/40，项目经验 30/40。

## 3. 优势分析
- 后端技术栈对口

## 4. 差距分析
- 缺少高并发经验

## 5. 提升建议
1. 补一个限流项目
"""


def _split_all(chunks: list[str]) -> tuple[str, list[str | None]]:
    """按给定分块喂入切分器，返回（拼接文本, section 序列）。"""
    splitter = SectionSplitter(JD_ANALYSIS_SECTION_RULES)
    text, sections = "", []
    for chunk in chunks:
        for piece, section in splitter.feed(chunk):
            text += piece
            sections.append(section)
    for piece, section in splitter.flush():
        text += piece
        sections.append(section)
    return text, sections


def _even_chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


# ---------- A 组：SectionSplitter ----------


def test_splitter_reassembles_by_line():
    """TC-32：逐行喂入时，拼接结果 == 原文（标题行原样保留，不被吞）。"""
    lines = [line + "\n" for line in SAMPLE_REPORT.split("\n") if line]

    text, _ = _split_all(lines)

    assert text == "".join(lines)


def test_splitter_reassembles_under_random_chunking():
    """TC-32：**随机切块**（含把标题行从中间切开）下拼接仍 == 原文。

    这是「落库全文 == delta 拼接」成立的前提——切分器可以延迟输出，但不能丢字或加字。
    """
    rng = random.Random(20260926)  # 固定种子：失败可复现
    for _ in range(30):
        chunks, i = [], 0
        while i < len(SAMPLE_REPORT):
            size = rng.randint(1, 17)
            chunks.append(SAMPLE_REPORT[i : i + size])
            i += size

        text, _ = _split_all(chunks)

        assert text == SAMPLE_REPORT


def test_splitter_reassembles_char_by_char():
    """TC-32：逐字符喂入（最极端的切块）下拼接仍 == 原文。"""
    text, _ = _split_all(list(SAMPLE_REPORT))

    assert text == SAMPLE_REPORT


def test_splitter_section_sequence():
    """TC-32：section 序列恒为五段顺序；**首个标题出现前为 None**。"""
    # SAMPLE_REPORT 第一行就是标题，故前置一段说明文字来验证「标题前为 None」
    text_with_preamble = "好的，以下是分析：\n\n" + SAMPLE_REPORT

    _, sections = _split_all(_even_chunks(text_with_preamble, 7))
    # 每个 piece 都带当前 section，取「变化点」才是段落序列
    changes = [s for i, s in enumerate(sections) if i == 0 or s != sections[i - 1]]

    assert changes == [None, "match_score", "scores", "strengths", "gaps", "advice"]


def test_splitter_falls_back_to_plain_text():
    """TC-32：AI 没按模板输出标题时全程不下发 section（纯文本降级，不把内容错标进某段）。"""
    plain = "这是一段没有标题的普通回答。\n第二行也一样。\n"

    _, sections = _split_all(_even_chunks(plain, 5))

    assert set(sections) == {None}


def test_splitter_keeps_heading_hash():
    """TC-32：标题行**原样保留 `#` 前缀**——这正是「落库全文 == delta 拼接」的成立条件。"""
    text, sections = _split_all(_even_chunks("## 1. 综合匹配度评分\n正文", 4))

    assert text.startswith("## 1. 综合匹配度评分")
    assert sections[0] == "match_score"


# ---------- B 组：extract_score ----------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("综合匹配度：85 分", 85),  # 模板给的标准格式
        ("综合匹配度：76", 76),  # 无「分」字
        ("综合匹配度评分：90", 90),  # 变体措辞
        ("**综合匹配度评分**：63", 63),  # markdown 加粗
        ("综合匹配度: 58", 58),  # 全角冒号
        ("综合匹配度：0 分", 0),  # 边界下
        ("综合匹配度：100 分", 100),  # 边界上
    ],
)
def test_extract_score_accepts(text: str, expected: int):
    """TC-20：兼容全 / 半角冒号与 markdown 加粗，取 0~100 的整数。"""
    assert jd_service.extract_score(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "这份 JD 和你很匹配。",  # 没有该字段
        "综合匹配度：101 分",  # 越界上
        "综合匹配度：-5 分",  # 越界下
    ],
)
def test_extract_score_returns_none(text: str):
    """TC-20：取不到或越界一律 None——不算失败，报告照常保留。"""
    assert jd_service.extract_score(text) is None


# ---------- C 组：落库与查询 ----------


def test_save_report_stores_text_and_score(db_session, account_id: int):
    """TC-20：五段文本与提取出的 score 一并落库，关联投递可为空。"""
    report_id = jd_service.save_report(db_session, account_id, "某 JD 原文", None, SAMPLE_REPORT)

    from app.models import JdAnalysisReport
    from app.database import SessionLocal

    with SessionLocal() as session:
        row = session.get(JdAnalysisReport, report_id)
        assert row.report_text == SAMPLE_REPORT
        assert row.score == 85
        assert row.jd_text == "某 JD 原文"
        assert row.application_id is None


def test_save_report_skips_empty_text(db_session, account_id: int):
    """TC-20：一个字都没生成时不落库（断连发生在首个 delta 之前即此情形）。"""
    from app.models import JdAnalysisReport

    assert jd_service.save_report(db_session, account_id, "某 JD", None, "   \n") is None
    assert db_session.query(JdAnalysisReport).count() == 0


def _seed_report(user_id: int, jd_text: str, report_text: str) -> int | None:
    """经服务层直接造一份报告。

    自开会话而**不用 `db_session` fixture**——后者会清库，与 `client` fixture 的清库相互冲突。
    """
    from app.database import SessionLocal

    with SessionLocal() as session:
        return jd_service.save_report(session, user_id, jd_text, None, report_text)


def test_report_list_orders_and_paginates(client: TestClient):
    """TC-20：列表按生成时间倒序（同一秒内按 id 倒序）；`page_size` 越界 → 10001。"""
    user_id = client.auth_account["id"]
    for i in range(3):
        _seed_report(user_id, f"JD {i}", f"报告 {i}\n综合匹配度：{60 + i} 分")

    listed = client.get(f"{API}/jd-reports", params={"page": 1, "page_size": 10}).json()["data"]
    assert listed["total"] == 3
    assert [item["score"] for item in listed["items"]] == [62, 61, 60]  # 新旧倒序

    assert client.get(f"{API}/jd-reports", params={"page_size": 51}).json()["code"] == 10001


def test_report_detail_is_per_account(client: TestClient, make_account):
    """TC-20：详情跨账号不可见——他人报告与不存在的报告返回同一错误码（不可区分）。"""
    report_id = _seed_report(client.auth_account["id"], "JD", "报告正文")
    other = make_account("jd_other")

    mine = client.get(f"{API}/jd-reports/{report_id}").json()["data"]
    assert mine["report_text"] == "报告正文"

    stolen = client.get(f"{API}/jd-reports/{report_id}", headers=other["headers"]).json()
    missing = client.get(f"{API}/jd-reports/99999999", headers=other["headers"]).json()
    assert stolen["code"] == missing["code"] == 10002


# ---------- D 组：流式端点（端到端） ----------


@pytest.fixture()
def jd_client(client: TestClient) -> TestClient:
    """配好供应商的客户端——JD 分析链路要先过 `resolve_config`，账号未配置会直接回 10012。

    这一步**不 mock**：配置解析是链路的一部分，用假 Key 走真实路径即可（真正的出网由
    `fake_llm_client` 挡在网外）。自开会话写库而非用 `db_session`，理由同 `_seed_report`。
    """
    from app.database import SessionLocal
    from app.models import LlmProviderConfig
    from app.utils.security import encrypt_text

    with SessionLocal() as session:
        session.add(
            LlmProviderConfig(
                user_id=client.auth_account["id"],
                provider="deepseek",
                api_key=encrypt_text("sk-test"),
                model="test-model",
                is_active=1,
            )
        )
        session.commit()
    return client


def _sse_events(text: str) -> list[tuple[str, dict]]:
    """解析响应体里的 SSE 事件序列（`event: <名>\\ndata: <JSON>`）。"""
    events = []
    for block in text.split("\n\n"):
        lines = block.strip().split("\n")
        if len(lines) < 2 or not lines[0].startswith("event: "):
            continue
        events.append((lines[0][len("event: ") :], json.loads(lines[1][len("data: ") :])))
    return events


def _run_analysis(client: TestClient, fake_llm_client, report_text: str, **payload):
    """把预设报告按固定大小分块喂给流式端点，返回（响应, 事件序列）。"""
    fake_llm_client.chunks = _even_chunks(report_text, 11)
    resp = client.post(
        f"{API}/stream/jd-analysis",
        json={"jd_text": "某公司 Java 后端岗位 JD", **payload},
    )
    return resp, _sse_events(resp.text)


def test_stream_event_order_and_record_id(jd_client: TestClient, fake_llm_client):
    """TC-32：事件顺序 start → delta×N → done；`start` 是第一个事件；`done.record_id` 可查。"""
    resp, events = _run_analysis(jd_client, fake_llm_client, SAMPLE_REPORT)

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert events[0][0] == "start"
    assert events[-1][0] == "done"
    assert all(name == "delta" for name, _ in events[1:-1])

    record_id = events[-1][1]["record_id"]
    assert record_id is not None
    assert jd_client.get(f"{API}/jd-reports/{record_id}").json()["code"] == 0


def test_stream_deltas_concat_equals_stored_text(jd_client: TestClient, fake_llm_client):
    """TC-32 核心：落库全文**恒等于**全部 `delta` 拼接（标题行原样下发，前端无需二次处理）。"""
    _, events = _run_analysis(jd_client, fake_llm_client, SAMPLE_REPORT)

    streamed = "".join(d["text"] for name, d in events if name == "delta")
    record_id = events[-1][1]["record_id"]
    stored = jd_client.get(f"{API}/jd-reports/{record_id}").json()["data"]["report_text"]

    assert stored == streamed == SAMPLE_REPORT


def test_stream_emits_section_anchors(jd_client: TestClient, fake_llm_client):
    """TC-32：`delta` 携带 `section` 锚点，依次为五段；**标题行本身仍在 `text` 里**。"""
    _, events = _run_analysis(jd_client, fake_llm_client, SAMPLE_REPORT)

    sections = [d.get("section") for name, d in events if name == "delta"]
    changes = [s for i, s in enumerate(sections) if i == 0 or s != sections[i - 1]]
    full_text = "".join(d["text"] for name, d in events if name == "delta")

    assert changes == ["match_score", "scores", "strengths", "gaps", "advice"]
    assert "## 1. 综合匹配度评分" in full_text


def test_validation_precedes_stream(jd_client: TestClient, fake_llm_client):
    """TC-32：两类校验都在流式建立**之前**完成，按普通响应体返回（不产生 SSE 事件）。

    前端据此按普通接口错误处理，不必当流事件解析。
    """
    bad_app = jd_client.post(
        f"{API}/stream/jd-analysis", json={"jd_text": "某 JD", "application_id": 99999999}
    )
    assert bad_app.status_code == 404
    assert bad_app.json()["code"] == 10002
    assert "event:" not in bad_app.text

    empty_jd = jd_client.post(f"{API}/stream/jd-analysis", json={"jd_text": ""})
    assert empty_jd.status_code == 400
    assert empty_jd.json()["code"] == 10001
    assert "event:" not in empty_jd.text


def test_llm_failure_does_not_save(jd_client: TestClient, fake_llm_client):
    """TC-32：中途失败 → `error` 事件且**不落库**（与断连落半成品是相反口径，勿混测）。"""
    fake_llm_client.chunks = ["## 1. 综合匹配度评分\n综合匹配度：8"]
    fake_llm_client.error = BizException(ErrorCode.LLM_CALL_FAILED, "供应商不可用")

    resp = jd_client.post(f"{API}/stream/jd-analysis", json={"jd_text": "某公司 JD"})
    events = _sse_events(resp.text)

    assert events[0][0] == "start"
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == ErrorCode.LLM_CALL_FAILED
    assert "done" not in [name for name, _ in events]

    listed = jd_client.get(f"{API}/jd-reports").json()["data"]
    assert listed["total"] == 0
