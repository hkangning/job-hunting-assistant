"""才立方（JYSD）适配器：服务端渲染 HTML，一校一子域，跟随「下一页」链接翻页。

出网一次列表页：`GET {domain}/teachin/index`（可经 params.start_path 覆盖入口路径）。
条目为 `ul.infoList.teachinList` 三列结构（标题链接 / 地点 / 时间段）；站点不提供公司字段。
"""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit

from lxml import etree, html as lxml_html

from app.clients.crawler import compliance
from app.clients.crawler.base import RawItem, SourceError, max_pages_of, parse_datetime_text, source_params
from app.models.enums import InfoType

ENTRY_PATH = "/teachin/index"  # 宣讲会列表入口
VIEW_MARK = "/teachin/view/id/"  # 详情页路径特征（用于识别条目链接）

_LIST_UL = (
    "//ul[contains(concat(' ', normalize-space(@class), ' '), ' infoList ') "
    "and contains(concat(' ', normalize-space(@class), ' '), ' teachinList ')]"
)
_SPAN5_LI = "./li[contains(concat(' ', normalize-space(@class), ' '), ' span5 ')]"
_NEXT_LINK = "//li[contains(concat(' ', normalize-space(@class), ' '), ' next ')]/a/@href"


def fetch(source) -> list[RawItem]:
    """抓取一个才立方站点的宣讲会列表（跟随「下一页」链接翻页至上限或无下一页）。"""
    params = source_params(source)
    base = source.domain.rstrip("/")
    start_path = str(params.get("start_path") or ENTRY_PATH)
    if not start_path.startswith("/"):
        start_path = "/" + start_path
    max_pages = max_pages_of(params)
    url = base + start_path
    items: list[RawItem] = []
    for _ in range(max_pages):
        resp = compliance.fetch(url)
        page_items, next_url = _parse_page(resp.content, url)
        items.extend(page_items)
        if not next_url:
            break
        url = next_url
    return items


def _parse_page(content: bytes, current_url: str) -> tuple[list[RawItem], str | None]:
    """解析一页列表：返回（本页条目, 下一页绝对地址或 None）；解析失败抛 SourceError。"""
    if not content or not content.strip():
        raise SourceError("页面内容为空")
    try:
        doc = lxml_html.fromstring(content)
    except (etree.ParserError, etree.XMLSyntaxError, ValueError) as exc:
        raise SourceError("页面解析失败（非 HTML 内容）") from exc
    items: list[RawItem] = []
    for ul in doc.xpath(_LIST_UL):
        item = _parse_entry(ul, current_url)
        if item is not None:
            items.append(item)
    next_url = None
    next_links = doc.xpath(_NEXT_LINK)
    if next_links:
        candidate = urljoin(current_url, next_links[0].strip())
        # 仅接受同主机跳转（跨域说明地址异常，忽略下一页避免误抓）
        if (urlsplit(candidate).hostname or "") == (urlsplit(current_url).hostname or ""):
            next_url = candidate
    return items, next_url


def _parse_entry(ul, current_url: str) -> RawItem | None:
    """单个条目解析：标题取详情链接文本，地点取 span5 列，时间从整段文本解析。"""
    links = ul.xpath(f".//a[contains(@href, '{VIEW_MARK}')]")
    if not links:
        return None
    link = links[0]
    title = (link.get("title") or link.text_content()).strip()
    if not title:
        return None
    texts = [li.text_content().strip() for li in ul.xpath("./li")]
    event_date = None
    for text in texts:
        event_date = parse_datetime_text(text)
        if event_date is not None:
            break
    if event_date is None:
        return None
    location = None
    span5 = ul.xpath(_SPAN5_LI)
    if span5:
        location = span5[0].text_content().strip() or None
    href = (link.get("href") or "").strip()
    return RawItem(
        title=title,
        event_date=event_date,
        info_type=InfoType.TALK.value,
        company=None,
        location=location,
        source_url=urljoin(current_url, href) if href else None,
    )
