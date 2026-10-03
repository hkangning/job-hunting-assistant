"""处理层纯函数（系统设计 5.9）：归一化 / 去重指纹 / 合并判定 / 归档判定 / 匹配打分。

全部为零 IO、零副作用的纯函数，可脱离网络与数据库离线单测。
归一化结果只用于比较（指纹、变更判定、匹配），不改写原文——落库始终存站点原文。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, time, timedelta

ARCHIVE_AFTER_DAYS = 90  # 过期后再保留天数，超过物理删除（数据库设计 3.13）

_SPACE_RE = re.compile(r"\s+")
_COMPANY_PAREN_RE = re.compile(r"[(（][^)）]*[)）]")
_MULTI_SPLIT_RE = re.compile(r"[,，、/;；\s]+")

# 方向匹配泛词：几乎出现在所有技术岗标题里，不构成方向命中
_DIRECTION_STOPWORDS = {"工程师", "招聘", "岗位", "实习", "应届", "校园", "校招", "公司"}


def normalize_text(text: str | None) -> str:
    """文本归一化：全角转半角（NFKC）、压缩空白、统一小写；仅用于比较，不改写原文。"""
    if not text:
        return ""
    return _SPACE_RE.sub("", unicodedata.normalize("NFKC", str(text))).casefold()


def normalize_company(company: str | None) -> str:
    """公司名归一化：在通用归一化基础上去掉括号后缀（如「XX（中国）有限公司」）。"""
    return _COMPANY_PAREN_RE.sub("", normalize_text(company))


def dedup_key(company: str | None, title: str, event_date: datetime) -> str:
    """去重指纹：sha1(归一公司 + 归一标题 + 日期)，同一活动跨源 / 跨天重复出现时键一致。"""
    parts = [normalize_company(company), normalize_text(title), event_date.strftime("%Y-%m-%d")]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def content_hash(item) -> str:
    """内容哈希：sha1(归一标题 + 归一公司 + 时间 + 地点 + 专业)，用于变更检测与审计。

    入参为鸭子类型对象（RawItem 或 CampusEvent 行均可），只读取字段不写入。
    """
    parts = [
        normalize_text(item.title),
        normalize_company(item.company),
        item.event_date.strftime("%Y-%m-%d %H:%M") if item.event_date else "",
        normalize_text(item.location),
        normalize_text(item.major_req),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def merge_fields(current, item) -> tuple[bool, dict]:
    """库中已存在行 vs 本次抓到条目 → (是否有内容变更, 待写入字段)。

    空值保护：新值为空一律不写（防站点表述缺省把已有值清空）；
    归一化后相同视为未变（原文差异不触发变更）；
    source_url 仅在库中为空时填充（保留首次来源链接，不覆盖）。
    """
    writes: dict[str, object] = {}
    if normalize_text(item.title) != normalize_text(current.title):
        writes["title"] = item.title
    for field in ("company", "location", "major_req"):
        new_value = getattr(item, field, None)
        if not new_value:
            continue
        # 公司名按去括号口径比较（与指纹、content_hash 同一套归一化）：
        # 同一活动在不同源的简称 / 全称差异不应被判为变更、来回改写
        norm = normalize_company if field == "company" else normalize_text
        if norm(new_value) != norm(getattr(current, field, None)):
            writes[field] = new_value
    if item.event_date != current.event_date:
        writes["event_date"] = item.event_date
    if item.source_url and not current.source_url:
        writes["source_url"] = item.source_url
    changed = any(field in writes for field in ("title", "company", "location", "major_req", "event_date"))
    return changed, writes


def merge_source_sites(current_sites: str | None, new_site: str, max_len: int) -> str:
    """来源站点合并：逗号分隔、保序去重（同一条目被多校 / 多源抓到时逐个追加）。

    `max_len` 为落库列宽（source_site 50 字符）：追加后超宽即停止，保留完整主机名、不截半。
    """
    sites = [s for s in (current_sites or "").split(",") if s]
    if new_site and new_site not in sites:
        sites.append(new_site)
    kept: list[str] = []
    for site in sites:
        candidate = ",".join(kept + [site])
        if len(candidate) > max_len:
            break
        kept.append(site)
    return ",".join(kept)


def _hit_any(field_text: str | None, keywords: list[str]) -> bool:
    """归一化后关键词命中判定：字段为空或关键词为空均不命中。"""
    if not field_text or not keywords:
        return False
    haystack = normalize_text(field_text)
    return any(normalize_text(k) in haystack for k in keywords if k)


def _position_keywords(position: str) -> list[str]:
    """目标岗位 → 匹配关键词：按标点与空白切分出的片段（过滤泛词）再补全串。"""
    segments = [p for p in _MULTI_SPLIT_RE.split(position) if p and p not in _DIRECTION_STOPWORDS]
    segments.append(position)
    return segments


def match_score(item, profile) -> int:
    """画像匹配打分（0~100）：城市 +30 / 方向 +40 / 专业 +30；对应字段缺失不加不减。

    `item` 与 `profile` 均为鸭子类型对象（item 读 title/location/major_req，profile 读
    target_city/target_position/major），CampusEvent 行与 user_profile 行可直接传入。
    """
    score = 0
    city = getattr(profile, "target_city", None)
    if city and _hit_any(getattr(item, "location", None), [p for p in _MULTI_SPLIT_RE.split(city) if p]):
        score += 30
    position = getattr(profile, "target_position", None)
    if position and _hit_any(getattr(item, "title", None), _position_keywords(position)):
        score += 40
    major = getattr(profile, "major", None)
    if major and _hit_any(getattr(item, "major_req", None), [p for p in _MULTI_SPLIT_RE.split(major) if p]):
        score += 30
    return score


def should_expire(event_date: datetime, now: datetime) -> bool:
    """过期判定（自然日口径）：活动所在自然日已过 → 过期；当天活动全天有效。"""
    return event_date.date() < now.date()


def purge_before(now: datetime) -> datetime:
    """物理删除的界线：event_date 早于该时刻的过期条目删除（EXPIRED 超 ARCHIVE_AFTER_DAYS 天）。"""
    return datetime.combine(now.date() - timedelta(days=ARCHIVE_AFTER_DAYS), time.min)
