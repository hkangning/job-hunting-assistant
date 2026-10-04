"""校招情报测试：TC-23 / TC-73 ~ TC-82（步骤 21 多源采集层 + 步骤 22 岗位与订阅）。

分组（对齐测试计划 §用例）：
- A 处理器纯函数：跨源去重指纹（TC-73）、变更判定与空值保护（TC-74）、归档边界（TC-75）、匹配打分（TC-78）；
- B 适配器离线解析（TC-76）：三厂商快照经 stub 出网，全程不联网；
- C 合规组件（TC-77）：UA 标识、robots 检查、状态码分流、跨域拦截、同域限频；
- D 服务层编排：跨源合并与变更落库（TC-73/74）、归档执行与"全源失败不归档"（TC-75）、单源隔离与任务互斥（TC-23）；
- E API：源配置 CRUD 错误口径、手动触发逐源结果、`GET /campus-events` 过滤 / 分页 / 排序 / 来源映射、概览接入；
- F 岗位与投喂（步骤 22）：岗位列表隔离与状态口径、`is_applied` 归一比对、概览岗位、
  投喂三条路径（文本成功 / 抽取失败 / 链接被拒）；
- G 订阅与推送（步骤 22）：订阅 CRUD 与数组清洗、匹配语义（维度间 AND / 维度内 OR）、
  多规则并集、同日去重、候选限公共信息（投喂记录不参与推送）；
- H 日历（步骤 22）：四类事件聚合、区间边界、跨账号隔离。

口径出处：接口文档 v1.45 §3.4 / §3.14 / §3.16、系统设计 v1.41 §5.9、数据库设计 v1.24。
服务层与 API 用例走真实测试库（conftest 每例清库）；出网一律 stub（投喂链接抓取同理）。
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.clients.crawler import compliance, processor
from app.clients.crawler.adapters import bysjy, job91, jysd
from app.clients.crawler.base import RawItem, SourceError, parse_datetime_text
from app.clients.llm_client import LLMError
from app.database import SessionLocal
from app.exceptions import BizException, ErrorCode
from app.models import (
    Application,
    CampusEvent,
    Config,
    CrawlSource,
    JobPosting,
    Reminder,
    Subscription,
    User,
    UserProfile,
)
from app.models.enums import (
    ApplicationStatus,
    CrawlStatus,
    InfoStatus,
    InfoType,
    IngestSource,
    JobType,
    ReminderType,
)
from app.services import campus_service

API = "/api/v1"
TODAY = datetime.combine(date.today(), time(12, 0))  # 今天正午：自然日口径用例的安全基准


# ---------- 辅助 ----------


def _raw(title: str = "某公司宣讲会", event_date: datetime | None = None, **kw) -> RawItem:
    """造一条抓取中间结构；event_date 默认后天（未过期）。"""
    return RawItem(
        title=title,
        event_date=event_date or (TODAY + timedelta(days=2)),
        info_type=kw.pop("info_type", InfoType.TALK.value),
        **kw,
    )


def _add_source(
    db,
    *,
    school_name: str = "南京理工大学",
    system_type: str = "91JOB",
    domain: str = "https://njust.91job.org.cn",
    enabled: int = 1,
    params: dict | None = None,
    last_crawl_at: datetime | None = None,
    last_status: str | None = None,
) -> CrawlSource:
    row = CrawlSource(
        school_name=school_name,
        system_type=system_type,
        domain=domain,
        params=json.dumps(params) if params is not None else None,
        enabled=enabled,
        created_at=datetime.now(),
        last_crawl_at=last_crawl_at,
        last_status=last_status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _add_event(db, *, title: str = "某公司宣讲会", event_date: datetime | None = None, **kw) -> CampusEvent:
    """造一条落库活动；默认明天、ACTIVE、无来源映射。"""
    event_date = event_date or (TODAY + timedelta(days=1))
    row = CampusEvent(
        title=title,
        event_date=event_date,
        info_type=kw.pop("info_type", InfoType.TALK.value),
        company=kw.pop("company", None),
        location=kw.pop("location", None),
        major_req=kw.pop("major_req", None),
        source_url=kw.pop("source_url", None),
        source_site=kw.pop("source_site", "njust.91job.org.cn"),
        dedup_key=kw.pop("dedup_key", None) or f"k-{title}-{event_date:%Y%m%d%H%M}",
        status=kw.pop("status", InfoStatus.ACTIVE.value),
        first_seen_at=TODAY,
        last_seen_at=TODAY,
        changed_at=kw.pop("changed_at", None),
        **kw,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _ok(payload=None, *, text: str | None = None, url: str = "https://mock.edu.cn/") -> httpx.Response:
    """造一个 200 响应（json 或 text 二选一）。"""
    kwargs = {"json": payload} if payload is not None else {"text": text or ""}
    return httpx.Response(200, request=httpx.Request("GET", url), **kwargs)


def _stub_fetch(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """把 compliance.fetch 换成按 URL 分派的 stub（离线，不联网）。"""

    def fake(url: str, *, method: str = "GET", json_body: dict | None = None):
        return handler(url, method=method, json_body=json_body)

    monkeypatch.setattr(compliance, "fetch", fake)


def _no_robots(monkeypatch: pytest.MonkeyPatch) -> None:
    """跳过 robots 前置检查（服务层用例不测合规时用）。"""
    monkeypatch.setattr(compliance, "check_robots", lambda domain: None)


def _stub_adapter(monkeypatch: pytest.MonkeyPatch, by_source_id) -> None:
    """把 campus_service 的适配器入口换成按源 id 返回条目或抛错的假适配器。"""

    def fake_get_adapter(system_type: str):
        def adapter(source):
            result = by_source_id(source.id)
            if isinstance(result, Exception):
                raise result
            return result

        return adapter

    monkeypatch.setattr(campus_service, "get_adapter", fake_get_adapter)


def _create_source_via_api(client: TestClient, **overrides) -> httpx.Response:
    payload = {
        "school_name": "南京理工大学",
        "system_type": "91JOB",
        "domain": "https://njust.91job.org.cn",
        "params": {"xxdm": "10288"},
    }
    payload.update(overrides)
    return client.post(f"{API}/crawl-sources", json=payload)


# ========== A 组：处理器纯函数（TC-73 / TC-74 / TC-75 / TC-78） ==========


def test_dedup_key_same_across_sources():
    """TC-73：同一活动跨源表述差异（公司括号后缀 / 全角 / 空白 / 大小写）→ 指纹一致。"""
    a = processor.dedup_key("南京理工大学（中国）", "Tencent 2026 校园宣讲会", datetime(2026, 10, 8, 16, 0))
    b = processor.dedup_key("南京理工大学", "ＴＥＮＣＥＮＴ2026校园宣讲会", datetime(2026, 10, 8, 16, 0))
    assert a == b


def test_dedup_key_differs_on_date():
    """TC-73：日期不同（改期）→ 指纹不同（按新条目处理）。"""
    a = processor.dedup_key("某公司", "宣讲会", datetime(2026, 10, 8))
    b = processor.dedup_key("某公司", "宣讲会", datetime(2026, 10, 9))
    assert a != b


def test_merge_fields_detects_change_and_protects_empty():
    """TC-74：地点变化 → changed=True 且只写变化字段；新值为空不得清空库中已有值。"""
    current = SimpleNamespace(
        title="宣讲会",
        company="某公司",
        location="老地点",
        major_req="计算机",
        event_date=datetime(2026, 10, 8),
        source_url="https://a",
    )
    changed, writes = processor.merge_fields(
        current,
        _raw(title="宣讲会", event_date=datetime(2026, 10, 8), location="新地点", company=None),
    )
    assert changed is True
    assert writes == {"location": "新地点"}


def test_merge_fields_no_false_change_on_text_variance():
    """TC-74：原文表述差异（全角 / 空白）归一化后相同 → 不得误标变更。"""
    current = SimpleNamespace(
        title="Tencent 宣讲会",
        company="某公司",
        location="报告厅",
        major_req=None,
        event_date=datetime(2026, 10, 8),
        source_url="https://a",
    )
    changed, writes = processor.merge_fields(current, _raw(title="ＴＥＮＣＥＮＴ宣讲会", event_date=datetime(2026, 10, 8)))
    assert changed is False
    assert writes == {}


def test_match_score_three_dimensions():
    """TC-78：城市 +30 / 方向 +40 / 专业 +30，三项全中 = 100。"""
    profile = SimpleNamespace(target_city="南京", target_position="后端开发", major="计算机")
    item = SimpleNamespace(title="后端开发工程师宣讲会", location="南京理工大学", major_req="计算机科学与技术")
    assert processor.match_score(item, profile) == 100


def test_match_score_missing_fields_not_penalized():
    """TC-78：字段缺失的维度不加分也不隐藏（未写专业要求不判低分）；三项全空 = 0 且不报错。"""
    profile = SimpleNamespace(target_city="南京", target_position="后端开发", major="计算机")
    partial = SimpleNamespace(title="后端开发岗宣讲会", location=None, major_req=None)
    empty = SimpleNamespace(title="某宣讲会", location=None, major_req=None)
    assert processor.match_score(partial, profile) == 40
    assert processor.match_score(empty, profile) == 0


def test_match_score_generic_words_filtered():
    """TC-78：多词目标岗位的泛词片段被过滤（「后端开发 工程师」按「后端开发」命中，不因泛词「工程师」误命中无关标题）。"""
    profile = SimpleNamespace(target_city=None, target_position="后端开发 工程师", major=None)
    hit = SimpleNamespace(title="后端开发岗宣讲会", location=None, major_req=None)
    miss = SimpleNamespace(title="机械工程师宣讲会", location=None, major_req=None)
    assert processor.match_score(hit, profile) == 40
    assert processor.match_score(miss, profile) == 0


def test_should_expire_natural_day_boundary():
    """TC-75：活动当天全天有效、次日过期（自然日口径）。"""
    assert processor.should_expire(datetime(2026, 10, 3, 0, 0), datetime(2026, 10, 3, 23, 59)) is False
    assert processor.should_expire(datetime(2026, 10, 2, 23, 59), datetime(2026, 10, 3, 0, 1)) is True


def test_purge_before_90_days():
    """TC-75：物理删除界线 = 当天前推 90 天的 00:00。"""
    assert processor.purge_before(datetime(2026, 10, 3, 15, 0)) == datetime(2026, 7, 5, 0, 0)


def test_merge_source_sites_overflow_keeps_intact_hostname():
    """TC-73：来源逗号分隔保序去重；追加超列宽即止、保留完整主机名不截半。"""
    long_site = "a" * 30 + ".edu.cn"  # 37 字符
    merged = processor.merge_source_sites(None, long_site, max_len=40)
    assert merged == long_site
    assert processor.merge_source_sites(merged, "b.edu.cn", max_len=40) == long_site


def test_parse_datetime_text_variants():
    """基础解析：日期+时刻 / 仅日期（00:00）/ 无日期 → None / 非法日期 → None。"""
    assert parse_datetime_text("2026-10-08 16:00-18:00") == datetime(2026, 10, 8, 16, 0)
    assert parse_datetime_text("2026-10-08") == datetime(2026, 10, 8, 0, 0)
    assert parse_datetime_text("时间待定") is None
    assert parse_datetime_text("2026-13-40") is None


# ========== B 组：适配器离线解析（TC-76，stub 出网） ==========


def test_job91_parses_talk_and_fair(monkeypatch: pytest.MonkeyPatch):
    """TC-76：91job 免登录 JSON——宣讲会 / 招聘会字段映射与详情链接。"""
    talk = {"xjhmc": "某某公司宣讲会", "kssjd": "2026-10-08 16:00-18:00", "jbdd": "第一教学楼101", "xjhid": 111}
    fair = {"zphmc": "秋季双选会", "jbkssj": "2026-10-09 09:00", "jbcd": "体育馆", "zphid": 222}

    def handler(url, *, method="GET", json_body=None):
        records = [talk] if url.endswith(job91.TALK_PATH) else [fair]
        return _ok({"success": True, "result": {"records": records}, "message": "ok"}, url=url)

    _stub_fetch(monkeypatch, handler)
    source = SimpleNamespace(
        id=1, domain="https://njust.91job.org.cn", params=json.dumps({"xxdm": "10288"})
    )
    items = job91.fetch(source)

    assert [item.info_type for item in items] == [InfoType.TALK.value, InfoType.FAIR.value]
    assert items[0].title == "某某公司宣讲会"
    assert items[0].event_date == datetime(2026, 10, 8, 16, 0)
    assert items[0].location == "第一教学楼101"
    assert items[0].source_url == "https://njust.91job.org.cn/sub-station/lectureDetail?xjhid=111&xxdm=10288"
    assert items[1].title == "秋季双选会"
    assert items[1].event_date == datetime(2026, 10, 9, 9, 0)
    assert items[1].source_url == "https://njust.91job.org.cn/recruitment/meetingDetail?zphid=222"


def test_job91_pagination_stops_at_last_page(monkeypatch: pytest.MonkeyPatch):
    """TC-76：翻页——首页满页继续、末页不满即停。"""
    pages: list[int] = []

    def record(i: int) -> dict:
        return {"xjhmc": f"宣讲会{i}", "kssjd": "2026-10-08 16:00", "jbdd": "教室", "xjhid": i}

    def handler(url, *, method="GET", json_body=None):
        if not url.endswith(job91.TALK_PATH):
            return _ok({"success": True, "result": {"records": []}}, url=url)
        pages.append(json_body["current"])
        if json_body["current"] == 1:
            return _ok({"success": True, "result": {"records": [record(i) for i in range(20)]}}, url=url)
        return _ok({"success": True, "result": {"records": [record(99)]}}, url=url)

    _stub_fetch(monkeypatch, handler)
    source = SimpleNamespace(id=1, domain="https://njust.91job.org.cn", params=json.dumps({"xxdm": "1"}))
    items = job91.fetch(source)

    assert len(items) == 21
    assert pages == [1, 2]


def test_job91_missing_xxdm_raises():
    """TC-76：91job 源缺 xxdm 参数 → SourceError（配置错误记失败）。"""
    source = SimpleNamespace(id=1, domain="https://njust.91job.org.cn", params=None)
    with pytest.raises(SourceError, match="xxdm"):
        job91.fetch(source)


def test_bysjy_filters_overdue_and_cancelled(monkeypatch: pytest.MonkeyPatch):
    """TC-76：云就业——正常记录字段映射；平台标过期（overdue）/ 已取消（career_state）的条目跳过。"""
    data = [
        {
            "meet_name": "云就业宣讲会",
            "meet_day": "2026-10-08",
            "meet_time": "14:30",
            "room": "二教201",
            "company_name": "某某公司",
            "professionals": "计算机类",
            "career_talk_id": 333,
        },
        {"meet_name": "已过期场次", "meet_day": "2026-10-08", "meet_time": "14:30", "overdue": "1"},
        {"meet_name": "已取消场次", "meet_day": "2026-10-08", "meet_time": "14:30", "career_state": "1"},
    ]
    _stub_fetch(monkeypatch, lambda url, **kw: _ok({"code": 1, "data": data}, url=url))
    source = SimpleNamespace(
        id=1, domain="https://cqu.edu.cn", params=json.dumps({"panel_name": "宣讲会", "panel_id": "7"})
    )
    items = bysjy.fetch(source)

    assert [item.title for item in items] == ["云就业宣讲会"]
    assert items[0].event_date == datetime(2026, 10, 8, 14, 30)
    assert items[0].location == "二教201"
    assert items[0].company == "某某公司"
    assert items[0].major_req == "计算机类"
    assert items[0].source_url == "https://cqu.edu.cn/detail/career?id=333"


def test_bysjy_missing_params_raises():
    """TC-76：云就业源缺 panel_name / panel_id → SourceError。"""
    source = SimpleNamespace(id=1, domain="https://cqu.edu.cn", params=None)
    with pytest.raises(SourceError, match="panel_name"):
        bysjy.fetch(source)


def test_jysd_parses_server_rendered_page(monkeypatch: pytest.MonkeyPatch):
    """TC-76：才立方 SSR——标题 / 地点 / 时间从列表页解析，同主机「下一页」跟随翻页。"""
    page1 = """
    <html><head><meta charset="utf-8"></head><body>
      <ul class="infoList teachinList">
        <li class="span7"><a href="/teachin/view/id/555" title="才立方宣讲会">才立方宣讲会</a></li>
        <li class="span5">大学生活动中心</li>
        <li class="span5">2026-10-08 14:00-16:00</li>
      </ul>
      <ul class="pagination"><li class="next"><a href="/teachin/index?page=2">下一页</a></li></ul>
    </body></html>
    """
    page2 = """
    <html><head><meta charset="utf-8"></head><body>
      <ul class="infoList teachinList">
        <li class="span7"><a href="/teachin/view/id/556" title="第二页宣讲会">第二页宣讲会</a></li>
        <li class="span5">三教101</li>
        <li class="span5">2026-10-09 10:00</li>
      </ul>
    </body></html>
    """
    pages = {"https://mock.jysd.edu.cn/teachin/index": page1}

    def handler(url, *, method="GET", json_body=None):
        return _ok(text=pages.get(url, page2), url=url)

    _stub_fetch(monkeypatch, handler)
    source = SimpleNamespace(id=1, domain="https://mock.jysd.edu.cn", params=None)
    items = jysd.fetch(source)

    assert [item.title for item in items] == ["才立方宣讲会", "第二页宣讲会"]
    assert items[0].event_date == datetime(2026, 10, 8, 14, 0)
    assert items[0].location == "大学生活动中心"
    assert items[0].source_url == "https://mock.jysd.edu.cn/teachin/view/id/555"


def test_jysd_ignores_cross_host_next_link(monkeypatch: pytest.MonkeyPatch):
    """TC-76：才立方「下一页」跨域 → 忽略（只抓当前页，避免误抓）。"""
    page = """
    <html><head><meta charset="utf-8"></head><body>
      <ul class="infoList teachinList">
        <li class="span7"><a href="/teachin/view/id/1" title="宣讲会">宣讲会</a></li>
        <li class="span5">报告厅</li>
        <li class="span5">2026-10-08 14:00</li>
      </ul>
      <li class="next"><a href="https://evil.example.com/page2">下一页</a></li>
    </body></html>
    """
    calls = []

    def handler(url, *, method="GET", json_body=None):
        calls.append(url)
        return _ok(text=page, url=url)

    _stub_fetch(monkeypatch, handler)
    source = SimpleNamespace(id=1, domain="https://mock.jysd.edu.cn", params=None)
    items = jysd.fetch(source)

    assert len(items) == 1
    assert calls == ["https://mock.jysd.edu.cn/teachin/index"]


# ========== C 组：合规组件（TC-77） ==========


def _client_with_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """让 compliance 的出网走 MockTransport（保留 UA 等生产构造参数由各用例自行核对）。"""
    transport = httpx.MockTransport(handler)

    def fake_new_client():
        return httpx.Client(
            timeout=compliance.REQUEST_TIMEOUT,
            headers={"User-Agent": compliance.USER_AGENT},
            transport=transport,
            trust_env=False,
        )

    monkeypatch.setattr(compliance, "_new_client", fake_new_client)
    monkeypatch.setattr(compliance, "_wait_turn", lambda host: None)  # 限频另有专测，避免真实等待


def test_new_client_identifies_user_agent():
    """TC-77：出网客户端带固定 UA 标识与用途说明，且不走环境代理。"""
    with compliance._new_client() as client:
        assert client.headers["User-Agent"] == compliance.USER_AGENT
        assert "JobHunterBot/1.0" in compliance.USER_AGENT
        assert client.trust_env is False


def test_fetch_returns_200_response(monkeypatch: pytest.MonkeyPatch):
    """TC-77：正常 200 响应原样返回（适配器据其解析）。"""
    _client_with_transport(monkeypatch, lambda request: httpx.Response(200, json={"ok": True}))
    resp = compliance.fetch("https://mock.edu.cn/api")
    assert resp.status_code == 200 and resp.json() == {"ok": True}


def test_fetch_403_blocked(monkeypatch: pytest.MonkeyPatch):
    """TC-77：HTTP 403 → blocked（停止该源、不重试）。"""
    _client_with_transport(monkeypatch, lambda request: httpx.Response(403))
    with pytest.raises(SourceError) as exc:
        compliance.fetch("https://mock.edu.cn/a")
    assert exc.value.blocked is True


def test_fetch_429_failed_not_blocked(monkeypatch: pytest.MonkeyPatch):
    """TC-77：HTTP 429 → 失败（限流暂停），不算被拒（下次采集仍会重试）。"""
    _client_with_transport(monkeypatch, lambda request: httpx.Response(429))
    with pytest.raises(SourceError) as exc:
        compliance.fetch("https://mock.edu.cn/a")
    assert exc.value.blocked is False


def test_fetch_other_status_and_network_error(monkeypatch: pytest.MonkeyPatch):
    """TC-77：其余非 200 → 失败；网络异常 → 失败（均不 blocked）。"""
    _client_with_transport(monkeypatch, lambda request: httpx.Response(500))
    with pytest.raises(SourceError) as exc:
        compliance.fetch("https://mock.edu.cn/a")
    assert exc.value.blocked is False

    def boom(request):
        raise httpx.ConnectError("连接失败")

    _client_with_transport(monkeypatch, boom)
    with pytest.raises(SourceError, match="请求失败"):
        compliance.fetch("https://mock.edu.cn/a")


def test_fetch_redirect_not_followed_and_rejected(monkeypatch: pytest.MonkeyPatch):
    """TC-77：3xx 重定向默认不跟随 → 按非 200 分流终止该源（不落到跳转目标）。"""

    def handler(request):
        return httpx.Response(302, headers={"Location": "https://evil.example.com/x"})

    _client_with_transport(monkeypatch, handler)
    with pytest.raises(SourceError, match="302"):
        compliance.fetch("https://mock.edu.cn/a")


def test_check_same_host_rejects_cross_host():
    """TC-77：跳转后仍须同主机——跨域说明地址已失效或被劫持，终止该源。"""
    compliance._check_same_host("https://a.edu.cn/x", "https://a.edu.cn/y")  # 同主机放行
    with pytest.raises(SourceError, match="跨域"):
        compliance._check_same_host("https://a.edu.cn/x", "https://evil.example.com/x")


def test_fetch_rejects_non_http_scheme():
    """TC-77：仅支持 http/https 地址。"""
    with pytest.raises(SourceError, match="http"):
        compliance.fetch("ftp://mock.edu.cn/a")


def test_check_robots_disallow_blocked(monkeypatch: pytest.MonkeyPatch):
    """TC-77：robots 明确禁止 → blocked，且只请求 robots.txt、不抓页面。"""
    requested: list[str] = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, text="User-agent: *\nDisallow: /\n", request=request)

    _client_with_transport(monkeypatch, handler)
    with pytest.raises(SourceError) as exc:
        compliance.check_robots("https://mock.edu.cn/teachin/index")
    assert exc.value.blocked is True
    assert requested == ["https://mock.edu.cn/robots.txt"]


def test_check_robots_unavailable_passes(monkeypatch: pytest.MonkeyPatch):
    """TC-77：robots 读不到（404）或网络异常 → 按未声明处理，放行。"""
    _client_with_transport(monkeypatch, lambda request: httpx.Response(404, request=request))
    assert compliance.check_robots("https://mock.edu.cn") is None

    def boom(request):
        raise httpx.ConnectError("超时")

    _client_with_transport(monkeypatch, boom)
    assert compliance.check_robots("https://mock.edu.cn") is None


def test_rate_limit_waits_min_interval(monkeypatch: pytest.MonkeyPatch):
    """TC-77：同域请求间隔不足 2s 时等待补足；换域不等待。"""
    clock = {"t": 100.0}
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["t"] += seconds

    monkeypatch.setattr(compliance.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(compliance.time, "sleep", fake_sleep)
    compliance._last_request_at.clear()

    compliance._wait_turn("rate1.edu.cn")  # 首访不等待
    clock["t"] += 0.5
    compliance._wait_turn("rate1.edu.cn")  # 距上次 0.5s → 补 1.5s
    compliance._wait_turn("rate2.edu.cn")  # 换域不等待

    assert sleeps == [compliance.DOMAIN_INTERVAL - 0.5]
    compliance._last_request_at.clear()


# ========== D 组：服务层编排（TC-73 / TC-74 / TC-75 / TC-23） ==========


def test_store_items_cross_source_merge(db_session):
    """TC-73：同一活动两源抓到 → 落库一条、来源逗号分隔、new 只计一次（第二源记 updated）。"""
    source_a = _add_source(db_session, school_name="A大学", domain="https://a.91job.org.cn")
    source_b = _add_source(db_session, school_name="B大学", domain="https://b.91job.org.cn")
    item = _raw(title="某某公司宣讲会", event_date=datetime(2026, 10, 8, 16, 0), company="某某公司")

    counts_a = campus_service._store_items(db_session, source_a, [item], TODAY)
    counts_b = campus_service._store_items(db_session, source_b, [item], TODAY)
    db_session.commit()

    rows = list(db_session.scalars(select(CampusEvent)))
    assert len(rows) == 1
    assert counts_a.new == 1 and counts_a.updated == 0
    assert counts_b.new == 0 and counts_b.updated == 1
    assert rows[0].source_site == "a.91job.org.cn,b.91job.org.cn"


def test_store_items_marks_changed_on_field_update(db_session):
    """TC-74：重复采集内容变化 → status=CHANGED、changed_at 有值、items_changed 计数。"""
    source = _add_source(db_session)
    first = _raw(title="宣讲会", event_date=datetime(2026, 10, 8, 16, 0), location="老地点")
    campus_service._store_items(db_session, source, [first], TODAY)
    db_session.commit()

    second = _raw(title="宣讲会", event_date=datetime(2026, 10, 8, 16, 0), location="新地点")
    counts = campus_service._store_items(db_session, source, [second], TODAY + timedelta(days=1))
    db_session.commit()

    row = db_session.scalar(select(CampusEvent))
    assert counts.changed == 1
    assert row.location == "新地点"
    assert row.status == InfoStatus.CHANGED.value
    assert row.changed_at is not None


def test_store_items_repeat_is_updated_not_changed(db_session):
    """TC-74：内容未变重复采集 → 记 updated、不得误标 CHANGED。"""
    source = _add_source(db_session)
    item = _raw(title="宣讲会", event_date=datetime(2026, 10, 8, 16, 0), location="报告厅")
    campus_service._store_items(db_session, source, [item], TODAY)
    db_session.commit()
    counts = campus_service._store_items(db_session, source, [item], TODAY + timedelta(days=1))
    db_session.commit()

    row = db_session.scalar(select(CampusEvent))
    assert counts.updated == 1 and counts.changed == 0
    assert row.status == InfoStatus.ACTIVE.value and row.changed_at is None


def test_archive_expired_marks_and_purges(db_session):
    """TC-75：活动日已过 → EXPIRED；EXPIRED 超 90 天 → 物理删除；未来活动不动。"""
    past = _add_event(db_session, title="昨日活动", event_date=TODAY - timedelta(days=1))
    ancient = _add_event(
        db_session, title="远古活动", event_date=TODAY - timedelta(days=100), status=InfoStatus.EXPIRED.value
    )
    _add_event(db_session, title="未来活动", event_date=TODAY + timedelta(days=3))

    expired = campus_service._archive_expired(db_session, datetime.now())
    db_session.commit()

    assert expired == 1
    assert {row.title for row in db_session.scalars(select(CampusEvent))} == {"昨日活动", "未来活动"}
    assert db_session.get(CampusEvent, past.id).status == InfoStatus.EXPIRED.value
    assert db_session.get(CampusEvent, ancient.id) is None


def test_run_crawl_single_source_isolation(db_session, monkeypatch: pytest.MonkeyPatch):
    """TC-23：一源失败仅该源标 FAILED（含原因摘要），其余源照常入库。"""
    good = _add_source(db_session, school_name="好学校", domain="https://good.91job.org.cn")
    bad = _add_source(db_session, school_name="坏学校", domain="https://bad.91job.org.cn")
    _no_robots(monkeypatch)
    _stub_adapter(
        monkeypatch,
        lambda sid: SourceError("站点不可访问") if sid == bad.id else [_raw(title="好学校宣讲会")],
    )

    result = campus_service.run_crawl(db_session)

    assert result.total == 2 and result.ok == 1 and result.failed == 1
    details = {detail.school_name: detail for detail in result.details}
    assert details["坏学校"].status == CrawlStatus.FAILED.value
    assert details["坏学校"].error
    assert details["好学校"].counts.new == 1
    db_session.refresh(bad)
    assert bad.last_status == CrawlStatus.FAILED.value and bad.last_error
    assert [row.title for row in db_session.scalars(select(CampusEvent))] == ["好学校宣讲会"]


def test_run_crawl_blocked_source_recorded_as_blocked(db_session, monkeypatch: pytest.MonkeyPatch):
    """TC-23 / TC-77：robots 禁止 → 该源标 BLOCKED（不重试），不抓页面。"""
    _add_source(db_session, school_name="被拒学校")
    _stub_adapter(monkeypatch, lambda sid: SourceError("不该被抓取"))
    monkeypatch.setattr(compliance, "check_robots", lambda domain: (_ for _ in ()).throw(SourceError("robots 禁止", blocked=True)))

    result = campus_service.run_crawl(db_session)

    assert result.blocked == 1
    assert result.details[0].status == CrawlStatus.BLOCKED.value


def test_run_crawl_all_sources_fail_no_archive(db_session, monkeypatch: pytest.MonkeyPatch):
    """TC-75：本次全源失败时不归档（源故障不得误清数据）。"""
    _add_source(db_session)
    stale = _add_event(db_session, title="昨日活动", event_date=TODAY - timedelta(days=1))
    _no_robots(monkeypatch)
    _stub_adapter(monkeypatch, lambda sid: SourceError("全挂了"))

    result = campus_service.run_crawl(db_session)

    assert result.expired == 0
    db_session.refresh(stale)
    assert stale.status == InfoStatus.ACTIVE.value


def test_run_crawl_lock_mutex(db_session):
    """TC-23：采集任务执行中再次触发 → 10001（非阻塞锁，不排队不并发）。"""
    _add_source(db_session)
    assert campus_service._CRAWL_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(BizException) as exc:
            campus_service.run_crawl(db_session)
        assert exc.value.code == ErrorCode.PARAM_INVALID
    finally:
        campus_service._CRAWL_LOCK.release()


def test_manual_run_ignores_disabled_sources_and_daily_skip(db_session, monkeypatch: pytest.MonkeyPatch):
    """TC-23：手动全量只跑启用中的源、不受「每源每日 1 次」限制（强制刷新）。"""
    _add_source(db_session, school_name="启用的", domain="https://on.91job.org.cn", last_crawl_at=TODAY, last_status=CrawlStatus.OK.value)
    _add_source(db_session, school_name="停用的", domain="https://off.91job.org.cn", enabled=0)
    _no_robots(monkeypatch)
    _stub_adapter(monkeypatch, lambda sid: [_raw(title=f"活动{sid}")])

    result = campus_service.run_crawl(db_session, skip_recent=False)

    assert result.total == 1
    assert result.details[0].school_name == "启用的"


def test_run_scheduled_respects_switch_and_daily_once(db_session, monkeypatch: pytest.MonkeyPatch):
    """TC-23：每日任务——总开关关闭时静默跳过；开启后每源每日 1 次（今天已抓的跳过）。"""
    _add_source(db_session, last_crawl_at=TODAY, last_status=CrawlStatus.OK.value)
    _no_robots(monkeypatch)
    _stub_adapter(monkeypatch, lambda sid: [_raw(title="不该出现在每日任务外")])

    # 系统级 config 行跨用例保留（conftest 只清账号级行），故显式置值、用后还原，不依赖"当前默认"
    config = db_session.get(Config, (0, "crawl_enabled"))
    config.value = "false"
    db_session.commit()
    assert campus_service.run_scheduled() is None  # 总开关关闭 → 静默跳过

    config.value = "true"
    db_session.commit()
    result = campus_service.run_scheduled()  # 今天已抓过 → skip_recent 跳过
    assert result is not None and result.total == 0

    config.value = "false"  # 还原系统级默认值（expected_schema.SYSTEM_CONFIG），避免污染后续用例
    db_session.commit()


def test_store_items_clips_overlong_fields(db_session):
    """落库保护：超列宽原文按列宽裁剪（站点异常数据不撑爆列）。"""
    source = _add_source(db_session)
    counts = campus_service._store_items(db_session, source, [_raw(title="标" * 250)], TODAY)
    db_session.commit()

    row = db_session.scalar(select(CampusEvent))
    assert counts.new == 1
    assert len(row.title) == 200


# ========== E 组：API（源 CRUD / 手动触发 / campus-events / 概览） ==========


def test_crawl_source_crud_flow(client: TestClient):
    """源 CRUD：新增 → 清单 → 部分更新（未传字段保持原值）→ 停用 → 删除。"""
    resp = _create_source_via_api(client)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["school_name"] == "南京理工大学"
    assert data["enabled"] is True
    assert data["params"] == {"xxdm": "10288"}
    assert data["last_crawl_at"] is None and data["last_status"] is None and data["last_error"] is None
    source_id = data["id"]

    listing = client.get(f"{API}/crawl-sources").json()["data"]
    assert listing["total"] == 1 and listing["items"][0]["id"] == source_id

    resp = client.put(f"{API}/crawl-sources/{source_id}", json={"school_name": "南京理工大学（新）"})
    assert resp.json()["data"]["school_name"] == "南京理工大学（新）"
    assert resp.json()["data"]["domain"] == "https://njust.91job.org.cn"

    resp = client.put(f"{API}/crawl-sources/{source_id}", json={"enabled": False})
    assert resp.json()["data"]["enabled"] is False

    assert client.delete(f"{API}/crawl-sources/{source_id}").json()["data"] is None
    assert client.get(f"{API}/crawl-sources").json()["data"]["total"] == 0


def test_crawl_source_duplicate_conflict(client: TestClient):
    """同一系统 + 同一域名重复登记 → 10003（不同域名可共存）。"""
    _create_source_via_api(client)
    resp = _create_source_via_api(client, school_name="另一学校")
    assert resp.status_code == 409 and resp.json()["code"] == 10003

    assert _create_source_via_api(client, school_name="另一学校", domain="https://other.91job.org.cn").status_code == 200


def test_crawl_source_update_rejects_system_type_change(client: TestClient):
    """不支持修改系统类型 → 10001（需删除后重建）。"""
    source_id = _create_source_via_api(client).json()["data"]["id"]
    resp = client.put(f"{API}/crawl-sources/{source_id}", json={"system_type": "BYSJY"})
    assert resp.status_code == 400 and resp.json()["code"] == 10001


def test_crawl_source_invalid_domain_and_not_found(client: TestClient):
    """域名须以 http/https 开头 → 10001；不存在的源改 / 删 → 404 + 10002。"""
    resp = _create_source_via_api(client, domain="njust.91job.org.cn")
    assert resp.status_code == 400 and resp.json()["code"] == 10001

    assert client.put(f"{API}/crawl-sources/999", json={"school_name": "x"}).json()["code"] == 10002
    assert client.delete(f"{API}/crawl-sources/999").json()["code"] == 10002


def test_update_source_resets_last_crawl_status(client: TestClient):
    """编辑源后重置 last_status / last_error（可即时重试被 BLOCKED 的源），保留 last_crawl_at。"""
    source_id = _create_source_via_api(client).json()["data"]["id"]
    with SessionLocal() as db:
        row = db.get(CrawlSource, source_id)
        row.last_crawl_at = TODAY
        row.last_status = CrawlStatus.BLOCKED.value
        row.last_error = "robots.txt 明确禁止抓取"
        db.commit()

    data = client.put(f"{API}/crawl-sources/{source_id}", json={"school_name": "改个名"}).json()["data"]
    assert data["last_status"] is None and data["last_error"] is None
    assert data["last_crawl_at"] is not None


def test_run_all_sources_reports_per_source(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """手动触发（全部源）：逐源回报；全源失败整体仍 200、expired=0。"""
    _create_source_via_api(client)
    _create_source_via_api(client, school_name="第二学校", domain="https://b.91job.org.cn")
    _no_robots(monkeypatch)
    _stub_adapter(monkeypatch, lambda sid: SourceError("站点不可访问"))

    resp = client.post(f"{API}/crawl-sources/run", json={})

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total"] == 2 and data["failed"] == 2 and data["ok"] == 0 and data["expired"] == 0
    assert len(data["details"]) == 2
    assert all(detail["status"] == CrawlStatus.FAILED.value and detail["error"] for detail in data["details"])


def test_run_single_source_failure_502(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """指定单源且该源失败 → 502 + 70002（单源粒度才报错，便于调试）。"""
    source_id = _create_source_via_api(client).json()["data"]["id"]
    _no_robots(monkeypatch)
    _stub_adapter(monkeypatch, lambda sid: SourceError("站点不可访问"))

    resp = client.post(f"{API}/crawl-sources/run", json={"source_id": source_id})

    assert resp.status_code == 502 and resp.json()["code"] == 70002


def test_run_single_source_success_and_not_found(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """指定单源成功 → items_new 计数；源不存在 → 404 + 10002。"""
    source_id = _create_source_via_api(client).json()["data"]["id"]
    _no_robots(monkeypatch)
    _stub_adapter(monkeypatch, lambda sid: [_raw(title="宣讲会A"), _raw(title="宣讲会B")])

    data = client.post(f"{API}/crawl-sources/run", json={"source_id": source_id}).json()["data"]
    assert data["total"] == 1 and data["ok"] == 1 and data["items_new"] == 2

    assert client.post(f"{API}/crawl-sources/run", json={"source_id": 999}).json()["code"] == 10002


def test_crawl_requires_token(anon_client: TestClient):
    """鉴权：源接口全部在 §1.1 白名单外 → 无 Token 一律 401 + 80001。"""
    assert anon_client.get(f"{API}/crawl-sources").status_code == 401
    assert anon_client.post(f"{API}/crawl-sources", json={}).status_code == 401
    assert anon_client.post(f"{API}/crawl-sources/run", json={}).status_code == 401
    assert anon_client.get(f"{API}/campus-events").status_code == 401


def test_campus_events_source_site_mapping(client: TestClient):
    """来源站点口径：下发源配置学校名；映射不到回退站点标识；映射后同名去重。"""
    _create_source_via_api(client, school_name="南京理工大学", domain="https://njust.edu.cn")
    _create_source_via_api(client, school_name="重庆大学", domain="https://cqu.edu.cn")
    _create_source_via_api(client, school_name="重庆大学", domain="https://cqu2.edu.cn")
    with SessionLocal() as db:
        _add_event(db, title="跨源活动", source_site="njust.edu.cn,cqu.edu.cn,cqu2.edu.cn,gone.edu.cn")

    data = client.get(f"{API}/campus-events").json()["data"]

    assert data["items"][0]["source_site"] == "南京理工大学,重庆大学,gone.edu.cn"


def test_campus_events_filters(client: TestClient):
    """过滤：info_type / city（地点模糊）/ keyword（标题或公司）/ 日期区间 / 过期默认隐藏。"""
    with SessionLocal() as db:
        _add_event(db, title="南京宣讲会", location="南京理工大学", event_date=TODAY + timedelta(days=2))
        _add_event(db, title="双选会", info_type=InfoType.FAIR.value, location="体育馆", event_date=TODAY + timedelta(days=3))
        _add_event(
            db, title="过期宣讲会", location="南京", event_date=TODAY - timedelta(days=2), status=InfoStatus.EXPIRED.value
        )

    base = client.get(f"{API}/campus-events").json()["data"]
    assert base["total"] == 2  # 默认隐藏 EXPIRED

    assert client.get(f"{API}/campus-events?include_expired=true").json()["data"]["total"] == 3
    assert client.get(f"{API}/campus-events?info_type=FAIR").json()["data"]["total"] == 1
    assert client.get(f"{API}/campus-events?city=南京").json()["data"]["total"] == 1
    assert client.get(f"{API}/campus-events?keyword=双选").json()["data"]["total"] == 1

    date_from = (TODAY + timedelta(days=3)).date().isoformat()
    date_to = (TODAY + timedelta(days=2)).date().isoformat()
    assert client.get(f"{API}/campus-events?date_from={date_from}").json()["data"]["total"] == 1
    assert client.get(f"{API}/campus-events?date_to={date_to}").json()["data"]["total"] == 1


def test_campus_events_sort_time_and_match(client: TestClient, account):
    """排序：默认按活动时间升序；sort=match 按画像打分降序，字段缺失的条目不隐藏。"""
    with SessionLocal() as db:
        _add_event(db, title="晚场无关活动", location="天津", event_date=TODAY + timedelta(days=5))
        _add_event(db, title="早场后端开发宣讲", location="南京", major_req="计算机", event_date=TODAY + timedelta(days=1))
        profile = db.scalar(select(UserProfile).where(UserProfile.user_id == account["id"]))
        profile.target_city = "南京"
        profile.target_position = "后端开发"
        profile.major = "计算机"
        db.commit()

    by_time = client.get(f"{API}/campus-events").json()["data"]["items"]
    assert [item["title"] for item in by_time] == ["早场后端开发宣讲", "晚场无关活动"]

    by_match = client.get(f"{API}/campus-events?sort=match").json()["data"]["items"]
    assert by_match[0]["title"] == "早场后端开发宣讲"
    assert by_match[0]["match_score"] == 100
    assert len(by_match) == 2  # 低分条目不被隐藏


def test_campus_events_pagination_and_invalid_params(client: TestClient):
    """分页 total / 每页条数；页码与 page_size 越界、info_type / sort 非法 → 10001。"""
    with SessionLocal() as db:
        for index in range(12):
            _add_event(db, title=f"宣讲会{index}", event_date=TODAY + timedelta(days=1, hours=index))

    page1 = client.get(f"{API}/campus-events?page=1&page_size=10").json()["data"]
    page2 = client.get(f"{API}/campus-events?page=2&page_size=10").json()["data"]
    assert page1["total"] == 12 and len(page1["items"]) == 10
    assert len(page2["items"]) == 2

    assert client.get(f"{API}/campus-events?page_size=51").json()["code"] == 10001
    assert client.get(f"{API}/campus-events?page=0").json()["code"] == 10001
    assert client.get(f"{API}/campus-events?info_type=XXX").status_code == 400
    assert client.get(f"{API}/campus-events?info_type=XXX").json()["code"] == 10001
    assert client.get(f"{API}/campus-events?sort=xxx").json()["code"] == 10001


def test_overview_campus_events_and_last_crawl_at(client: TestClient):
    """概览接入：campus_events 下发来源学校名与已变更状态；last_crawl_at 取各源最近抓取时间。"""
    _create_source_via_api(client, school_name="南京理工大学", domain="https://njust.91job.org.cn")
    with SessionLocal() as db:
        _add_event(
            db,
            title="近期宣讲会",
            source_site="njust.91job.org.cn",
            event_date=TODAY + timedelta(days=2),
            status=InfoStatus.CHANGED.value,
            changed_at=TODAY,
        )
        db.get(CrawlSource, 1).last_crawl_at = TODAY
        db.commit()

    data = client.get(f"{API}/overview").json()["data"]

    assert data["campus_events"][0]["source_site"] == "南京理工大学"
    assert data["campus_events"][0]["status"] == InfoStatus.CHANGED.value
    assert data["last_crawl_at"] is not None


# ---------- F 岗位与投喂（TC-80 / TC-81，步骤 22） ----------


def _add_posting(
    db,
    *,
    user_id: int = 0,
    title: str = "后端开发工程师",
    company: str = "某科技有限公司",
    **kw,
) -> JobPosting:
    """造一条落库岗位；默认公共（user_id=0）、ACTIVE、今天入库。"""
    first_seen = kw.pop("first_seen_at", TODAY)
    row = JobPosting(
        user_id=user_id,
        title=title,
        company=company,
        city=kw.pop("city", None),
        edu_req=kw.pop("edu_req", None),
        major_req=kw.pop("major_req", None),
        salary_text=kw.pop("salary_text", None),
        job_type=kw.pop("job_type", None),
        deadline=kw.pop("deadline", None),
        source_site=kw.pop("source_site", None),
        source_url=kw.pop("source_url", None),
        ingest_source=kw.pop("ingest_source", IngestSource.AUTO.value),
        raw_excerpt=kw.pop("raw_excerpt", None),
        dedup_key=kw.pop("dedup_key", None) or f"posting-{user_id}-{company}-{title}",
        status=kw.pop("status", InfoStatus.ACTIVE.value),
        first_seen_at=first_seen,
        last_seen_at=kw.pop("last_seen_at", first_seen),
        changed_at=kw.pop("changed_at", None),
        **kw,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _add_subscription(db, user_id: int, *, name: str = "规则", enabled: int = 1, **arrays) -> Subscription:
    """造一条订阅规则；四个数组维度以 JSON 文本落库（模拟库中形态），空数组存 NULL。"""

    def dump(values: list[str]) -> str | None:
        return json.dumps(values, ensure_ascii=False) if values else None

    row = Subscription(
        user_id=user_id,
        name=name,
        keywords=dump(arrays.pop("keywords", [])),
        companies=dump(arrays.pop("companies", [])),
        cities=dump(arrays.pop("cities", [])),
        info_types=dump(arrays.pop("info_types", [])),
        enabled=enabled,
        created_at=datetime.now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_posting_dedup_key_normalizes_company_title_city():
    """TC-73（岗位侧）：指纹 = 归一公司 + 归一标题 + 归一城市——全半角括号与大小写／空白差异视为同一条，城市不同即不同。"""
    base = processor.posting_dedup_key("腾讯（南京）有限公司", "Java 开发工程师", "南京")
    assert base == processor.posting_dedup_key("腾讯(南京)有限公司", "java开发工程师", "南京")  # 同上一条
    assert base != processor.posting_dedup_key("腾讯(南京)有限公司", "Java 开发工程师", "深圳")
    assert base != processor.posting_dedup_key("字节跳动(南京)有限公司", "Java 开发工程师", "南京")


def test_list_job_postings_scope_and_status(db_session, account_id):
    """TC-81：结果 = 公共岗位 + 本账号投喂（他人投喂不可见）；status 三态口径与非法值 10001。"""
    _add_posting(db_session, user_id=0, title="公共岗位")
    _add_posting(db_session, user_id=account_id, title="我的投喂", ingest_source=IngestSource.FEED.value)
    _add_posting(db_session, user_id=account_id + 100, title="他人投喂", ingest_source=IngestSource.FEED.value)
    _add_posting(db_session, user_id=0, title="已变更岗位", status=InfoStatus.CHANGED.value, changed_at=TODAY)
    _add_posting(db_session, user_id=0, title="过期岗位", status=InfoStatus.EXPIRED.value)

    default = campus_service.list_job_postings(db_session, account_id)
    titles = {item.title for item in default.items}
    assert titles == {"公共岗位", "我的投喂", "已变更岗位"}  # 过期默认隐藏、他人投喂不可见

    assert campus_service.list_job_postings(db_session, account_id, status="ACTIVE").total == 3  # ACTIVE + CHANGED
    assert campus_service.list_job_postings(db_session, account_id, status="CHANGED").total == 1
    assert campus_service.list_job_postings(db_session, account_id, status="EXPIRED").total == 1

    with pytest.raises(BizException) as exc:
        campus_service.list_job_postings(db_session, account_id, status="DRAFT")
    assert exc.value.code == ErrorCode.PARAM_INVALID


def test_list_job_postings_filters_and_match_sort(db_session, account_id):
    """TC-78 / TC-81：过滤（城市等值 / 公司、关键词模糊 / job_type）与 sort=match 按画像打分降序、0 分不隐藏。"""
    profile = db_session.scalar(select(UserProfile).where(UserProfile.user_id == account_id))
    profile.target_city, profile.target_position, profile.major = "南京", "后端开发", "计算机"
    db_session.commit()
    _add_posting(db_session, title="低分岗位", company="甲公司", city="天津")
    _add_posting(db_session, title="后端开发工程师", company="乙公司", city="南京", major_req="计算机")
    _add_posting(db_session, title="实习岗位", company="丙公司", job_type=JobType.INTERN.value)

    assert campus_service.list_job_postings(db_session, account_id, city="南京").total == 1
    assert campus_service.list_job_postings(db_session, account_id, company="乙").total == 1
    assert campus_service.list_job_postings(db_session, account_id, keyword="后端").total == 1
    assert campus_service.list_job_postings(db_session, account_id, job_type="INTERN").total == 1
    with pytest.raises(BizException):
        campus_service.list_job_postings(db_session, account_id, job_type="XXX")
    with pytest.raises(BizException):
        campus_service.list_job_postings(db_session, account_id, sort="xxx")

    matched = campus_service.list_job_postings(db_session, account_id, sort="match").items
    assert matched[0].title == "后端开发工程师" and matched[0].match_score == 100
    assert len(matched) == 3  # 低分条目不被隐藏


def test_is_applied_normalized_comparison(db_session, account_id):
    """TC-81：is_applied 按「归一公司 + 归一岗位名」比对当前账号投递记录（投递原文的全半角 / 空白差异不影响判定）。"""
    db_session.add(
        Application(
            user_id=account_id,
            company="腾讯(南京)有限公司",
            position="Java 开发工程师",
            status=ApplicationStatus.APPLIED.value,
            applied_at=TODAY,
        )
    )
    db_session.commit()
    _add_posting(db_session, title="java开发工程师", company="腾讯（南京）有限公司")
    _add_posting(db_session, title="Java开发工程师", company="字节跳动")

    by_company = {item.company: item.is_applied for item in campus_service.list_job_postings(db_session, account_id).items}
    assert by_company == {"腾讯（南京）有限公司": True, "字节跳动": False}


def test_top_job_postings_limit_and_expired_filter(db_session, account_id):
    """概览岗位：默认 3 条、按匹配分降序、过滤 EXPIRED；含本账号投喂（接口文档 v1.45 §3.4）。"""
    profile = db_session.scalar(select(UserProfile).where(UserProfile.user_id == account_id))
    profile.target_city, profile.target_position, profile.major = "南京", "后端开发", "计算机"
    db_session.commit()
    _add_posting(db_session, user_id=0, title="后端开发工程师", city="南京", major_req="计算机")  # 100 分
    _add_posting(db_session, user_id=0, title="后端开发（天津）", city="天津")  # 40 分
    _add_posting(db_session, user_id=account_id, title="后端开发实习", city="天津", ingest_source=IngestSource.FEED.value)
    _add_posting(db_session, user_id=0, title="无关岗位", city="天津")  # 0 分，超默认条数（3）
    _add_posting(db_session, user_id=0, title="过期高分岗位", city="南京", major_req="计算机", status=InfoStatus.EXPIRED.value)

    top = campus_service.top_job_postings(db_session, account_id)
    assert len(top) == 3
    assert top[0].title == "后端开发工程师" and top[0].match_score == 100
    assert all(item.title != "过期高分岗位" for item in top)
    assert {item.title for item in top} == {"后端开发工程师", "后端开发（天津）", "后端开发实习"}


def test_ingest_text_preview_and_confirm(client: TestClient, account, llm_configured, fake_llm_client):
    """TC-80 ①：文本抽取返回 fields + missing、预览**不入库**；确认后以 FEED 通道入库并归属当前账号。"""
    fake_llm_client.json_result = {
        "title": "后端开发工程师",
        "company": "某科技公司",
        "city": "南京",
        "edu_req": "本科",
        "major_req": "计算机",
        "salary_text": None,
        "job_type": "CAMPUS",
        "deadline": "2026-11-30",
    }
    resp = client.post(f"{API}/job-postings/ingest", json={"text": "某科技公司招聘后端开发工程师，本科，计算机专业……"})
    data = resp.json()["data"]

    assert resp.status_code == 200
    assert data["fields"]["title"] == "后端开发工程师"
    assert data["fields"]["deadline"] == "2026-11-30"  # 截止时间归一为日期串
    assert data["missing"] == ["salary_text"]  # 未抽到的字段清单（按固定字段序）
    assert data["source"] == "FEED" and data["fetched_from"] == "text"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(JobPosting)) == 0  # 预览不落库

    created = client.post(f"{API}/job-postings", json={**data["fields"], "raw_excerpt": "原文摘要"}).json()["data"]
    assert created["ingest_source"] == IngestSource.FEED.value
    assert created["status"] == InfoStatus.ACTIVE.value
    assert created["job_type"] == JobType.CAMPUS.value
    with SessionLocal() as db:
        row = db.scalar(select(JobPosting))
        assert row.user_id == account["id"] and row.raw_excerpt == "原文摘要"  # 投喂记录才有原文摘录


def test_ingest_link_path_success(client: TestClient, llm_configured, fake_llm_client, monkeypatch: pytest.MonkeyPatch):
    """TC-80 ③（成功支路）：链接通道经合规组件抓正文 → 抽取；fetched_from=url。"""
    fake_llm_client.json_result = {"title": "前端开发工程师", "company": "某公司"}
    monkeypatch.setattr(compliance, "fetch_article", lambda url: "招聘前端开发工程师。岗位职责与任职要求详见正文。" * 10)

    data = client.post(f"{API}/job-postings/ingest", json={"url": "https://mock.edu.cn/job/1"}).json()["data"]

    assert data["fetched_from"] == "url" and data["fields"]["title"] == "前端开发工程师"
    assert data["missing"] == ["city", "edu_req", "major_req", "salary_text", "job_type", "deadline"]


def test_ingest_link_private_address_rejected(client: TestClient, llm_configured, fake_llm_client):
    """TC-80 ③：内网地址被 SSRF 防护拒绝 → 70003（走真实 check_public_url，环回地址无需出网）。"""
    resp = client.post(f"{API}/job-postings/ingest", json={"url": "http://127.0.0.1/job"})

    assert resp.status_code == 502
    assert resp.json()["code"] == ErrorCode.INGEST_PARSE_FAILED
    assert "内网" in resp.json()["message"]
    assert fake_llm_client.json_calls == []  # 未到抽取环节


def test_ingest_link_login_wall_rejected(client: TestClient, llm_configured, fake_llm_client, monkeypatch: pytest.MonkeyPatch):
    """TC-80 ③：登录墙页面 → 70003（stub 出网，走真实正文提取与登录判定，message 与内网地址可区分）。"""
    monkeypatch.setattr(compliance, "check_public_url", lambda url: None)
    monkeypatch.setattr(compliance, "check_robots", lambda domain: None)
    body = "<html><body><p>请先登录后查看该职位详情</p><p>" + "职位描述与任职要求。" * 12 + "</p></body></html>"
    monkeypatch.setattr(compliance, "fetch", lambda url, *, method="GET", json_body=None: _ok(text=body))

    resp = client.post(f"{API}/job-postings/ingest", json={"url": "https://mock.edu.cn/job/2"})

    assert resp.json()["code"] == ErrorCode.INGEST_PARSE_FAILED
    assert "登录" in resp.json()["message"]
    assert "内网" not in resp.json()["message"]


def test_ingest_llm_failure_and_param_guards(client: TestClient, llm_configured, fake_llm_client):
    """TC-80 ②：抽取不可解析 → 70003；同传 / 均缺 → 10001；未配 AI → 10012（不降级为手动填表）。"""
    fake_llm_client.error = LLMError(ErrorCode.LLM_OUTPUT_INVALID, "输出无法解析")
    invalid = client.post(f"{API}/job-postings/ingest", json={"text": "招聘信息原文……"})
    assert invalid.status_code == 502
    assert invalid.json()["code"] == ErrorCode.INGEST_PARSE_FAILED

    fake_llm_client.error = None
    both = client.post(f"{API}/job-postings/ingest", json={"text": "原文", "url": "https://mock.edu.cn/job/3"})
    assert both.status_code == 400 and both.json()["code"] == ErrorCode.PARAM_INVALID
    neither = client.post(f"{API}/job-postings/ingest", json={})
    assert neither.json()["code"] == ErrorCode.PARAM_INVALID


def test_ingest_requires_ai_configuration(client: TestClient, fake_llm_client):
    """TC-80：未配 AI 供应商 → 10012（引导配置，原文就绪可直接重试，不降级为手动填表）。"""
    resp = client.post(f"{API}/job-postings/ingest", json={"text": "某公司招聘后端开发工程师……"})

    assert resp.status_code == 400
    assert resp.json()["code"] == ErrorCode.LLM_KEY_MISSING
    assert fake_llm_client.json_calls == []


def test_create_job_posting_validation_and_repeat_overwrite(client: TestClient, account):
    """TC-80：title / company 必填（去空白后校验）；同账号重复投喂同一条 → 覆盖更新不报错、不新增行。"""
    blank = client.post(f"{API}/job-postings", json={"title": "  ", "company": "某公司"})
    assert blank.status_code == 400 and blank.json()["code"] == ErrorCode.PARAM_INVALID

    first = client.post(
        f"{API}/job-postings",
        json={"title": "后端开发工程师", "company": "某公司", "city": "南京", "salary_text": "20k"},
    ).json()["data"]
    again = client.post(
        f"{API}/job-postings",
        json={"title": "后端开发工程师", "company": "某公司", "city": "南京", "salary_text": "25k"},
    ).json()["data"]

    assert again["id"] == first["id"] and again["salary_text"] == "25k"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(JobPosting)) == 1


def test_delete_job_posting_rules(client: TestClient, account, make_account):
    """TC-81：投喂项可删；自动抓取项不可删 → 10001；他人 / 不存在的项 → 404 + 10002（不可区分）。"""
    mine = client.post(f"{API}/job-postings", json={"title": "我的投喂", "company": "甲公司"}).json()["data"]
    with SessionLocal() as db:
        auto = _add_posting(db, user_id=0, title="公共岗位", company="乙公司", ingest_source=IngestSource.AUTO.value)
        auto_id = auto.id
    other = make_account("job_other")
    others = client.post(
        f"{API}/job-postings", json={"title": "他人投喂", "company": "丙公司"}, headers=other["headers"]
    ).json()["data"]

    assert client.delete(f"{API}/job-postings/{auto_id}").json()["code"] == ErrorCode.PARAM_INVALID
    assert client.delete(f"{API}/job-postings/{others['id']}").status_code == 404
    assert client.delete(f"{API}/job-postings/{others['id']}").json()["code"] == ErrorCode.NOT_FOUND
    assert client.delete(f"{API}/job-postings/999999").json()["code"] == ErrorCode.NOT_FOUND
    assert client.delete(f"{API}/job-postings/{mine['id']}").status_code == 200
    assert client.get(f"{API}/job-postings").json()["data"]["total"] == 1  # 仅剩公共岗位


def test_job_postings_requires_token(anon_client: TestClient):
    """鉴权：岗位 / 投喂 / 订阅 / 日历接口均在 §1.1 白名单外 → 无 Token 一律 401 + 80001。"""
    assert anon_client.get(f"{API}/job-postings").status_code == 401
    assert anon_client.post(f"{API}/job-postings", json={"title": "a", "company": "b"}).status_code == 401
    assert anon_client.post(f"{API}/job-postings/ingest", json={"text": "x"}).status_code == 401
    assert anon_client.get(f"{API}/calendar?start=2026-01-01&end=2026-01-02").status_code == 401
    assert anon_client.get(f"{API}/subscriptions").status_code == 401


# ---------- G 订阅规则与推送（TC-79，步骤 22） ----------


def test_subscription_crud_and_cleaning(client: TestClient, make_account):
    """TC-79：订阅 CRUD——数组清洗（去空白 / 去重 / 单项截断 / 每维上限）、PUT 部分更新（空数组 = 清空）、越权 10002。"""
    created = client.post(
        f"{API}/subscriptions",
        json={"name": " 后端岗 ", "keywords": [" 后端 ", "后端", "", "Java"], "cities": ["南京"], "info_types": ["JOB"]},
    ).json()["data"]
    assert created["name"] == "后端岗"
    assert created["keywords"] == ["后端", "Java"]  # 去空白、去重、去空项
    assert created["cities"] == ["南京"] and created["info_types"] == ["JOB"] and created["enabled"] is True
    sid = created["id"]

    capped = client.post(f"{API}/subscriptions", json={"name": "上限", "keywords": [f"k{i}" for i in range(30)]}).json()["data"]
    assert len(capped["keywords"]) == 20  # 每维最多 20 项
    clipped = client.post(f"{API}/subscriptions", json={"name": "截断", "keywords": ["x" * 80]}).json()["data"]
    assert len(clipped["keywords"][0]) == 50  # 单项最多 50 字

    # PUT 部分更新：未传字段保持原值；传空数组 = 清空该维度（回到「不限」）
    updated = client.put(f"{API}/subscriptions/{sid}", json={"enabled": False}).json()["data"]
    assert updated["enabled"] is False and updated["keywords"] == ["后端", "Java"]
    cleared = client.put(f"{API}/subscriptions/{sid}", json={"keywords": []}).json()["data"]
    assert cleared["keywords"] == [] and cleared["cities"] == ["南京"] and cleared["name"] == "后端岗"

    # 列表只含本账号、按创建顺序；他人改 / 删 → 404 + 10002
    other = make_account("sub_other")
    assert [item["id"] for item in client.get(f"{API}/subscriptions").json()["data"]] == [sid, capped["id"], clipped["id"]]
    assert client.get(f"{API}/subscriptions", headers=other["headers"]).json()["data"] == []
    assert client.put(f"{API}/subscriptions/{sid}", headers=other["headers"], json={"name": "改名"}).status_code == 404
    assert client.delete(f"{API}/subscriptions/{sid}", headers=other["headers"]).json()["code"] == ErrorCode.NOT_FOUND

    assert client.delete(f"{API}/subscriptions/{sid}").status_code == 200
    assert client.delete(f"{API}/subscriptions/{sid}").json()["code"] == ErrorCode.NOT_FOUND


def test_rule_hits_dimensions_and_or():
    """TC-79：匹配语义纯逻辑——维度间 AND、维度内 OR、留空维度不限；城市维度岗位读 city、活动回退 location。"""
    rule = campus_service.SubscriptionRule
    item = SimpleNamespace(title="Java 后端开发工程师", company="字节跳动（南京）有限公司", city="南京", location=None)

    assert campus_service._rule_hits(rule(("java",), ("字节跳动",), ("南京",), ("JOB",)), item, "JOB") is True
    assert campus_service._rule_hits(rule(("java",), ("字节跳动",), ("南京",), ("JOB",)), item, "TALK") is False  # 类型不符
    assert campus_service._rule_hits(rule(("阿里", "后端"), (), (), ()), item, "JOB") is True  # 同维 OR
    assert campus_service._rule_hits(rule(("阿里",), (), (), ()), item, "JOB") is False
    assert campus_service._rule_hits(rule(("java",), ("阿里",), (), ()), item, "JOB") is False  # 维度间 AND
    assert campus_service._rule_hits(rule((), (), (), ()), item, "JOB") is True  # 全留空 = 不限

    event = SimpleNamespace(title="后端专场宣讲会", company="某公司", location="南京理工大学体育馆")
    assert campus_service._rule_hits(rule((), (), ("南京",), ("TALK",)), event, "TALK") is True  # 活动回退 location
    assert campus_service._rule_hits(rule((), (), ("天津",), ()), event, "TALK") is False


def test_match_new_items_writes_reminder_and_dedup(db_session, account_id):
    """TC-79：命中写 INFO_MATCH 提醒（ref_type 标识来源表、模板文案不调 LLM）；同信息同日不重复。"""
    _add_subscription(db_session, account_id, keywords=["后端"])
    # 两表自增 id 相互独立，撞值会合并提醒（已知边界，见下一条用例）——先各占位，使两条目标条目 id 不同
    for index in range(2):
        _add_posting(db_session, user_id=0, title=f"填充岗位{index}", company="填充公司")
    _add_event(db_session, title="填充活动", dedup_key="filler")
    posting = _add_posting(db_session, user_id=0, title="后端开发工程师", company="某公司")  # id=3
    event = _add_event(db_session, title="后端专场宣讲会")  # id=2
    assert posting.id != event.id

    assert campus_service.match_new_items(db_session, now=TODAY) == 2
    rows = db_session.scalars(select(Reminder).where(Reminder.reminder_type == ReminderType.INFO_MATCH.value)).all()
    assert {(row.ref_type, row.ref_id) for row in rows} == {("job_posting", posting.id), ("campus_event", event.id)}
    assert all(row.content.startswith("订阅命中：") for row in rows)  # 模板文案（不经 LLM）
    assert all(row.checked == 0 and row.remind_date == TODAY.date() for row in rows)

    assert campus_service.match_new_items(db_session, now=TODAY) == 0  # 同日同条目不重复


def test_match_reminder_ref_id_collision_known_boundary(db_session, account_id):
    """已知边界（数据库设计 v1.24 §3.12，**非缺陷**）：reminder 同日去重唯一键不含 ref_type——
    `campus_event` 与 `job_posting` 两条 id 撞值时合并为一条提醒；本用例钉住该行为，若将来改口径此处会失败。"""
    _add_subscription(db_session, account_id)  # 四维不限
    posting = _add_posting(db_session, user_id=0, title="后端岗位")
    event = _add_event(db_session, title="后端宣讲会")

    assert posting.id == event.id == 1
    assert campus_service.match_new_items(db_session, now=TODAY) == 1  # 撞值：只出一条
    reminder = db_session.scalar(select(Reminder))
    assert reminder.ref_id == 1 and reminder.ref_type in ("job_posting", "campus_event")


def test_match_new_items_scope_excludes_feeds_and_others(db_session, account_id):
    """TC-79 / TC-81：候选限当日新入库 / 变更的**公共**信息——投喂（本人或他人）不推送、EXPIRED 不推送、隔日不推送。"""
    _add_subscription(db_session, account_id)  # 四维全空 = 不限，任何公共信息都命中
    _add_posting(db_session, user_id=account_id, title="我投喂的后端岗", ingest_source=IngestSource.FEED.value)
    _add_posting(db_session, user_id=account_id + 100, title="他人投喂的后端岗", ingest_source=IngestSource.FEED.value)
    _add_posting(db_session, user_id=0, title="过期公共岗", status=InfoStatus.EXPIRED.value)
    _add_posting(db_session, user_id=0, title="昨日公共岗", first_seen_at=TODAY - timedelta(days=1))

    assert campus_service.match_new_items(db_session, now=TODAY) == 0  # 投喂 / 他人 / 过期 / 隔日 一律不推送

    # 当日变更（changed_at 在今天）的公共岗位参与匹配
    _add_posting(
        db_session,
        user_id=0,
        title="今日变更岗",
        status=InfoStatus.CHANGED.value,
        first_seen_at=TODAY - timedelta(days=3),
        changed_at=TODAY - timedelta(hours=1),
    )
    assert campus_service.match_new_items(db_session, now=TODAY) == 1


def test_match_new_items_multi_rules_and_accounts(db_session, account_id):
    """TC-79：多规则命中取并集（同一条信息两条规则命中仍只出一条提醒）；逐账号各自生成、停用规则跳过。"""
    other = User(username="sub_other", password_hash="x")
    db_session.add(other)
    db_session.commit()
    _add_subscription(db_session, account_id, name="规则一", keywords=["后端"])
    _add_subscription(db_session, account_id, name="规则二", cities=["南京"])
    _add_subscription(db_session, other.id, keywords=["后端"])
    _add_subscription(db_session, other.id, name="停用规则", enabled=0, keywords=["后端"])

    _add_posting(db_session, user_id=0, title="后端开发", company="甲公司", city="南京")

    assert campus_service.match_new_items(db_session, now=TODAY) == 2  # 本账号并集 1 条 + 另一账号 1 条
    mine = db_session.scalars(select(Reminder).where(Reminder.user_id == account_id)).all()
    theirs = db_session.scalars(select(Reminder).where(Reminder.user_id == other.id)).all()
    assert len(mine) == 1 and len(theirs) == 1


def test_overview_top_job_postings_and_match_count(client: TestClient, account):
    """概览接入：top_job_postings 按匹配分降序（过滤 EXPIRED）、match_reminder_count 为未读 INFO_MATCH 数。"""
    with SessionLocal() as db:
        profile = db.scalar(select(UserProfile).where(UserProfile.user_id == account["id"]))
        profile.target_city, profile.target_position, profile.major = "南京", "后端开发", "计算机"
        _add_posting(db, user_id=0, title="后端开发工程师", city="南京", major_req="计算机")
        _add_posting(db, user_id=0, title="无关岗位", city="天津")
        _add_posting(db, user_id=0, title="过期高分岗位", city="南京", major_req="计算机", status=InfoStatus.EXPIRED.value)
        db.add(Reminder(
            user_id=account["id"], reminder_type=ReminderType.INFO_MATCH.value, ref_id=1, ref_type="job_posting",
            content="订阅命中：岗位……", remind_date=TODAY.date(), checked=0,
        ))
        db.add(Reminder(
            user_id=account["id"], reminder_type=ReminderType.INFO_MATCH.value, ref_id=2, ref_type="campus_event",
            content="订阅命中：宣讲会……", remind_date=TODAY.date(), checked=1,
        ))
        db.commit()

    data = client.get(f"{API}/overview").json()["data"]

    assert [item["title"] for item in data["top_job_postings"]] == ["后端开发工程师", "无关岗位"]
    assert data["top_job_postings"][0]["match_score"] == 100
    assert data["match_reminder_count"] == 1  # 已读的不计


# ---------- H 日历（TC-82，步骤 22） ----------


def test_calendar_four_types_and_order(client: TestClient, account):
    """TC-82：一次请求返回四类事件、event_at 升序；EXAM / INTERVIEW 的 title 为岗位名、location 为空。"""
    start = (TODAY + timedelta(days=1)).date()
    end = (TODAY + timedelta(days=3)).date()
    with SessionLocal() as db:
        _add_event(
            db, title="宣讲会A", location="大学生活动中心",
            event_date=datetime.combine(start + timedelta(days=2), time(14, 0)),
        )
        _add_event(
            db, title="双选会B", info_type=InfoType.FAIR.value, event_date=datetime.combine(start, time(9, 0))
        )
        db.add_all([
            Application(
                user_id=account["id"], company="甲公司", position="后端开发",
                status=ApplicationStatus.WRITTEN.value, applied_at=TODAY,
                next_event_at=datetime.combine(start + timedelta(days=1), time(10, 0)),
            ),
            Application(
                user_id=account["id"], company="乙公司", position="前端开发",
                status=ApplicationStatus.INTERVIEW.value, applied_at=TODAY,
                next_event_at=datetime.combine(start + timedelta(days=2), time(16, 0)),
            ),
        ])
        db.commit()

    items = client.get(f"{API}/calendar?start={start}&end={end}").json()["data"]

    assert [item["event_type"] for item in items] == ["FAIR", "EXAM", "TALK", "INTERVIEW"]
    assert [item["event_at"] for item in items] == sorted(item["event_at"] for item in items)
    exam = next(item for item in items if item["event_type"] == "EXAM")
    assert exam["title"] == "后端开发" and exam["location"] is None  # 笔试 / 面试下发岗位名、无地点
    assert exam["ref_type"] == "application" and exam["status"] == ApplicationStatus.WRITTEN.value
    talk = next(item for item in items if item["event_type"] == "TALK")
    assert talk["ref_type"] == "campus_event" and talk["location"] is not None


def test_calendar_range_boundaries_and_isolation(client: TestClient, account, make_account):
    """TC-82：跨月区间正常、空区间返回空数组、end < start → 10001；EXPIRED 命中区间即返回；笔试 / 面试只含本账号。"""
    other = make_account("cal_other")
    month_start = date.today().replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    month_end = next_month - timedelta(days=1)  # 本月最后一天
    day2 = next_month + timedelta(days=1)
    with SessionLocal() as db:
        _add_event(db, title="月末宣讲会", event_date=datetime.combine(month_end, time(10, 0)))
        _add_event(
            db, title="下月初双选会", info_type=InfoType.FAIR.value, status=InfoStatus.EXPIRED.value,
            event_date=datetime.combine(next_month, time(9, 0)),
        )
        db.add(Application(
            user_id=account["id"], company="甲公司", position="后端开发",
            status=ApplicationStatus.INTERVIEW.value, applied_at=TODAY,
            next_event_at=datetime.combine(day2, time(14, 0)),
        ))
        db.add(Application(
            user_id=other["id"], company="乙公司", position="前端开发",
            status=ApplicationStatus.WRITTEN.value, applied_at=TODAY,
            next_event_at=datetime.combine(day2, time(15, 0)),
        ))
        db.commit()

    items = client.get(f"{API}/calendar?start={month_end}&end={day2}").json()["data"]
    assert [item["event_type"] for item in items] == ["TALK", "FAIR", "INTERVIEW"]  # 跨月；他人笔试不可见
    assert next(item for item in items if item["event_type"] == "FAIR")["status"] == InfoStatus.EXPIRED.value

    empty = client.get(f"{API}/calendar?start={day2 + timedelta(days=30)}&end={day2 + timedelta(days=31)}")
    assert empty.status_code == 200 and empty.json()["data"] == []

    bad = client.get(f"{API}/calendar?start={day2}&end={month_end}")
    assert bad.status_code == 400 and bad.json()["code"] == ErrorCode.PARAM_INVALID



