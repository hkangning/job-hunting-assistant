"""云就业（BYSJY）适配器：AJAX 数据接口，一校一配置（panel_name 菜单名 + panel_id 菜单 ID）。

出网一次：`GET /module/getcareers` 按 start_page 翻页；`panel_name` / `panel_id` 各校不同，
必须成对匹配该校站点的菜单项，配置错误时接口不返回数据（该源记失败）。
"""

from __future__ import annotations

from urllib.parse import quote

from app.clients.crawler import compliance
from app.clients.crawler.base import RawItem, SourceError, max_pages_of, parse_datetime_text, source_params
from app.models.enums import InfoType

LIST_PATH = "/module/getcareers"
PAGE_SIZE = 20  # 每页条数


def fetch(source) -> list[RawItem]:
    """抓取一个云就业站点的宣讲会列表（翻页至上限或最后一页）。"""
    params = source_params(source)
    panel_name = str(params.get("panel_name") or "").strip()
    panel_id = str(params.get("panel_id") or "").strip()
    if not panel_name or not panel_id:
        raise SourceError("云就业源缺少 panel_name / panel_id 参数")
    base = source.domain.rstrip("/")
    max_pages = max_pages_of(params)
    items: list[RawItem] = []
    for page in range(1, max_pages + 1):
        url = (
            f"{base}{LIST_PATH}?start_page={page}&start=1&count={PAGE_SIZE}"
            f"&type=inner&panel_name={quote(panel_name)}&panel_id={quote(panel_id)}"
            "&k=&day=&professionals=&work_city=&is_yun_career="
        )
        resp = compliance.fetch(url)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise SourceError("接口响应不是合法 JSON") from exc
        if not isinstance(payload, dict):
            raise SourceError("接口返回异常：响应不是 JSON 对象")
        records = payload.get("data")
        if payload.get("code") != 1 or not isinstance(records, list):
            message = str(payload.get("msg") or "")[:80]
            raise SourceError(f"接口返回异常：{message or '缺少 data 字段'}")
        for record in records:
            if not isinstance(record, dict):
                continue
            item = _parse_record(record, base)
            if item is not None:
                items.append(item)
        if len(records) < PAGE_SIZE:
            break
    return items


def _parse_record(record: dict, base: str) -> RawItem | None:
    """单条记录 → RawItem；平台已标过期（overdue=1）或已取消（career_state=1）的条目跳过。"""
    if str(record.get("overdue") or "") == "1":
        return None
    if str(record.get("career_state") or "") == "1":
        return None
    title = str(record.get("meet_name") or "").strip()
    event_date = parse_datetime_text(str(record.get("meet_day") or ""), str(record.get("meet_time") or ""))
    if not title or event_date is None:
        return None
    room = str(record.get("room") or "").strip()
    address = str(record.get("address") or "").strip()
    talk_id = record.get("career_talk_id")
    return RawItem(
        title=title,
        event_date=event_date,
        info_type=InfoType.TALK.value,
        company=str(record.get("company_name") or "").strip() or None,
        location=room or address or None,
        major_req=str(record.get("professionals") or "").strip() or None,
        source_url=f"{base}/detail/career?id={talk_id}" if talk_id else None,
    )
