"""采集适配器协议与统一中间结构（系统设计 5.9）。

适配器按「一厂商一解析器 + 一校一配置」组织：同一就业网站系统的各校站点共用一套解析逻辑，
差异（学校代码、菜单 ID 等）全部放进 `crawl_source` 表的 `params` JSON 配置。
适配器只做「抓取 + 解析出条目」，不做指纹、判重、变更与落库（那是处理层与服务层的事）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import CrawlSource

MAX_PAGES_DEFAULT = 5  # 单次采集每列表的默认翻页上限（防失控保护，params.max_pages 可覆盖）
MAX_PAGES_LIMIT = 50  # 翻页上限的硬顶

_DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


@dataclass
class RawItem:
    """抓取条目的统一中间结构：只含元数据（NFR-016 只存元数据与链接，不存正文）。"""

    title: str  # 活动/会议标题
    event_date: datetime  # 开始时间（解析不到具体时刻则为当日 00:00）
    info_type: str  # InfoType 取值：TALK 宣讲会 / FAIR 双选会
    company: str | None = None  # 公司名（站点无此字段的来源为 None）
    location: str | None = None  # 举办地点
    major_req: str | None = None  # 专业要求（部分站点提供）
    source_url: str | None = None  # 详情页链接


class SourceError(Exception):
    """适配器抓取 / 解析失败。

    `blocked=True` 表示被站点明确拒绝（robots 禁止 / 403）→ 该源标记 BLOCKED 并停止重试；
    其余失败标记 FAILED，下次采集仍会重试。
    """

    def __init__(self, message: str, *, blocked: bool = False):
        self.blocked = blocked
        super().__init__(message)


def source_params(source: CrawlSource) -> dict:
    """解析源的 params 配置 JSON（对象）；空 / 非法一律按空对象处理。"""
    try:
        data = json.loads(source.params or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def max_pages_of(params: dict) -> int:
    """每列表翻页上限：params.max_pages 覆盖默认值，夹取到 1~MAX_PAGES_LIMIT。"""
    try:
        value = int(params.get("max_pages", MAX_PAGES_DEFAULT))
    except (TypeError, ValueError):
        return MAX_PAGES_DEFAULT
    return min(max(value, 1), MAX_PAGES_LIMIT)


def get_adapter(system_type: str) -> Callable[[CrawlSource], list[RawItem]]:
    """按系统类型取适配器入口；未注册的类型抛 SourceError（配置错误，该源记失败）。"""
    from app.clients.crawler.adapters import ADAPTERS

    adapter = ADAPTERS.get(system_type)
    if adapter is None:
        raise SourceError(f"未支持的源系统类型：{system_type}")
    return adapter


def parse_datetime_text(*texts: str | None) -> datetime | None:
    """从候选文本解析活动开始时间：先找日期，再取该文本中第一个时刻。

    只有日期（无时刻）→ 当日 00:00；时刻非法 → 回退当日 00:00；找不到日期 → None。
    供各适配器统一 event_date 口径使用（开始时间，精确到分钟）。
    """
    merged = " ".join(t for t in texts if t)
    date_match = _DATE_RE.search(merged)
    if date_match is None:
        return None
    year, month, day = (int(g) for g in date_match.groups())
    hour = minute = 0
    time_match = _TIME_RE.search(merged)
    if time_match is not None:
        hour, minute = int(time_match.group(1)), int(time_match.group(2))
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        pass
    try:
        return datetime(year, month, day)
    except ValueError:
        return None
