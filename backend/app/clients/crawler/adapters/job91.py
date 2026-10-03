"""91job（江苏高校就业网系统）适配器：免登录 JSON 接口，一校一配置（xxdm 学校代码）。

出网两次：宣讲会列表 `getXjhPageList` + 招聘会列表 `getZphPageList`，均为 POST JSON。
参数名固定 `current` / `size`，学校由 `xxdm`（学校代码）区分；站点不提供公司字段（company 留空）。
"""

from __future__ import annotations

from collections.abc import Callable

from app.clients.crawler import compliance
from app.clients.crawler.base import RawItem, SourceError, max_pages_of, parse_datetime_text, source_params
from app.models.enums import InfoType

TALK_PATH = "/web/wsjysc/lbxq/getXjhPageList"  # 宣讲会分页接口
FAIR_PATH = "/web/wsjysc/lbxq/getZphPageList"  # 招聘会分页接口
PAGE_SIZE = 20  # 每页条数


def fetch(source) -> list[RawItem]:
    """抓取一个 91job 站点的宣讲会与招聘会列表（翻页至上限或最后一页）。"""
    params = source_params(source)
    xxdm = str(params.get("xxdm") or "").strip()
    if not xxdm:
        raise SourceError("91job 源缺少 xxdm（学校代码）参数")
    base = source.domain.rstrip("/")
    max_pages = max_pages_of(params)
    items = _fetch_pages(f"{base}{TALK_PATH}", xxdm, max_pages, _parse_talk, base)
    items.extend(_fetch_pages(f"{base}{FAIR_PATH}", xxdm, max_pages, _parse_fair, base))
    return items


def _fetch_pages(
    api_url: str, xxdm: str, max_pages: int, parser: Callable[[dict, str, str], RawItem | None], base: str
) -> list[RawItem]:
    """按页码翻页抓一个列表接口并逐条解析；records 少于每页条数即为最后一页。"""
    items: list[RawItem] = []
    for page in range(1, max_pages + 1):
        resp = compliance.fetch(api_url, method="POST", json_body={"current": page, "size": PAGE_SIZE, "xxdm": xxdm})
        try:
            payload = resp.json()
        except ValueError as exc:
            raise SourceError("接口响应不是合法 JSON") from exc
        if not isinstance(payload, dict):
            raise SourceError("接口返回异常：响应不是 JSON 对象")
        result = payload.get("result")
        records = result.get("records") if isinstance(result, dict) else None
        if not payload.get("success") or not isinstance(records, list):
            message = str(payload.get("message") or "")[:80]
            raise SourceError(f"接口返回异常：{message or '缺少 records 字段'}")
        for record in records:
            if not isinstance(record, dict):
                continue
            item = parser(record, base, xxdm)
            if item is not None:
                items.append(item)
        if len(records) < PAGE_SIZE:
            break
    return items


def _parse_talk(record: dict, base: str, xxdm: str) -> RawItem | None:
    """宣讲会记录 → RawItem：标题 xjhmc、时间 kssjd（形如 2026-10-08 16:00-18:00）、地点 jbdd。"""
    title = str(record.get("xjhmc") or "").strip()
    event_date = parse_datetime_text(str(record.get("kssjd") or ""), str(record.get("jbrq") or ""))
    if not title or event_date is None:
        return None
    talk_id = record.get("xjhid")
    source_url = f"{base}/sub-station/lectureDetail?xjhid={talk_id}&xxdm={xxdm}" if talk_id else None
    return RawItem(
        title=title,
        event_date=event_date,
        info_type=InfoType.TALK.value,
        company=None,
        location=str(record.get("jbdd") or "").strip() or None,
        source_url=source_url,
    )


def _parse_fair(record: dict, base: str, xxdm: str) -> RawItem | None:
    """招聘会记录 → RawItem：标题 zphmc、开始时间 jbkssj、场地 jbcd。"""
    title = str(record.get("zphmc") or "").strip()
    event_date = parse_datetime_text(str(record.get("jbkssj") or ""))
    if not title or event_date is None:
        return None
    fair_id = record.get("zphid")
    source_url = f"{base}/recruitment/meetingDetail?zphid={fair_id}" if fair_id else None
    return RawItem(
        title=title,
        event_date=event_date,
        info_type=InfoType.FAIR.value,
        company=None,
        location=str(record.get("jbcd") or "").strip() or None,
        source_url=source_url,
    )
