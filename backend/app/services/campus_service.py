"""校招情报服务：源配置 CRUD、多源采集编排、宣讲会/双选会查询（FR-021，系统设计 5.9）。

采集编排：逐源独立事务与异常隔离——单源失败不回滚其他源、不中断整体任务（TC-23 手工验收项）；
互斥：手动触发与每日任务共用一把进程内锁，执行中再次触发直接返回 None（不排队）。
"""

import json
import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from urllib.parse import urlsplit

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.clients.crawler import compliance, processor
from app.clients.crawler.base import RawItem, SourceError, get_adapter
from app.database import SYSTEM_USER_ID, SessionLocal
from app.exceptions import BizException, ErrorCode
from app.models import CampusEvent, Config, CrawlSource, UserProfile
from app.models.enums import CrawlStatus, InfoStatus, InfoType
from app.schemas.campus import (
    CampusEventBrief,
    CampusEventItem,
    CrawlRunCounts,
    CrawlRunData,
    CrawlRunDetail,
    CrawlSourceCreateRequest,
    CrawlSourceDTO,
    CrawlSourceUpdateRequest,
)
from app.schemas.common import PageData

logger = logging.getLogger(__name__)

_CRAWL_LOCK = threading.Lock()  # 采集任务互斥（手动与每日共用）
OVERVIEW_EVENT_LIMIT = 5  # 概览「校招情报」区块返回的宣讲会/双选会条数
SOURCE_SITE_MAX_LEN = 50  # source_site 列宽（多源合并时的截断保护，对齐数据库设计 3.13）

# 各列表字段的列宽上限（站点原文可能超长，落库前统一裁剪）
_FIELD_LIMITS = {"title": 200, "company": 100, "location": 200, "major_req": 300, "source_url": 500}


# ---------- 总开关与采集入口 ----------


def is_crawl_enabled(db: Session) -> bool:
    """校招信息采集总开关（系统级 config 的 crawl_enabled，默认关闭）。"""
    row = db.get(Config, (SYSTEM_USER_ID, "crawl_enabled"))
    return row is not None and str(row.value).strip().lower() == "true"


def run_scheduled(*, db_factory: Callable[[], Session] | None = None) -> CrawlRunData | None:
    """每日任务入口：总开关关闭时静默跳过；任何异常不外抛（不影响同一任务里的提醒生成）。"""
    factory = db_factory or SessionLocal
    try:
        with factory() as db:
            if not is_crawl_enabled(db):
                logger.info("校招信息采集总开关关闭，跳过本次采集")
                return None
            return run_crawl(db, skip_recent=True)
    except BizException:
        logger.info("校招信息采集任务正在执行中，本次触发跳过")
        return None
    except Exception:
        logger.exception("校招信息采集任务异常")
        return None


def run_crawl(db: Session, *, source_id: int | None = None, skip_recent: bool = False) -> CrawlRunData:
    """执行采集：指定 source_id 只跑单个源（手动调试，不受启用开关限制），否则跑全部启用源。

    `skip_recent=True`（每日任务）时跳过今天已抓过的源（每源每日 1 次，NFR-016）；
    任务执行中再次触发 → 10001；指定单源且该源失败时抛 502+70002（单源粒度才报错，便于调试）。
    """
    if not _CRAWL_LOCK.acquire(blocking=False):
        raise BizException(ErrorCode.PARAM_INVALID, "采集任务正在执行中，请稍后重试")
    try:
        now = datetime.now()
        if source_id is not None:
            source = db.get(CrawlSource, source_id)
            if source is None:
                raise BizException(ErrorCode.NOT_FOUND)
            sources = [source]
        else:
            sources = list(db.scalars(select(CrawlSource).where(CrawlSource.enabled == 1).order_by(CrawlSource.id)))
        details: list[CrawlRunDetail] = []
        for source in sources:
            if skip_recent and _crawled_today(source, now):
                continue
            details.append(_crawl_one(db, source, now))
        expired = 0
        if any(detail.status == CrawlStatus.OK.value for detail in details):
            # 仅当本次存在任一成功源时才归档：源全挂时不算"活动已过期"，避免误标（见系统设计 5.9）
            expired = _archive_expired(db, now)
            db.commit()
        if source_id is not None and details and details[0].status != CrawlStatus.OK.value:
            raise BizException(ErrorCode.CRAWL_PARSE_FAILED, f"源采集失败：{details[0].error or '未知原因'}")
        return _summarize(details, expired)
    finally:
        _CRAWL_LOCK.release()


def _crawled_today(source: CrawlSource, now: datetime) -> bool:
    """每源每日全量 1 次：今天已抓过（无论成败）跳过；源被编辑过（last_status 已清空）视为未抓。"""
    if source.last_crawl_at is None or source.last_crawl_at.date() != now.date():
        return False
    return source.last_status is not None


def _crawl_one(db: Session, source: CrawlSource, now: datetime) -> CrawlRunDetail:
    """抓取单个源：robots 检查 → 适配器抓取解析 → 落库；失败回滚本源数据并重写源状态。"""
    counts = CrawlRunCounts()
    status = CrawlStatus.OK.value
    error = None
    try:
        compliance.check_robots(source.domain)
        adapter = get_adapter(source.system_type)
        items = adapter(source)
        counts = _store_items(db, source, items, now)
    except SourceError as exc:
        db.rollback()
        status = CrawlStatus.BLOCKED.value if exc.blocked else CrawlStatus.FAILED.value
        error = str(exc)[:300]
    except Exception as exc:  # 适配器或落库的内部错误：不外抛，记失败由下次重试
        db.rollback()
        status = CrawlStatus.FAILED.value
        error = f"内部错误：{exc.__class__.__name__}"
        logger.exception("源 #%s 采集异常", source.id)
    source.last_crawl_at = now
    source.last_status = status
    source.last_error = error
    db.commit()
    return CrawlRunDetail(source_id=source.id, school_name=source.school_name, status=status, error=error, counts=counts)


def _store_items(db: Session, source: CrawlSource, items: list[RawItem], now: datetime) -> CrawlRunCounts:
    """条目落库：按指纹去重（同批同源 + 跨源）、新增 / 合并、变更判定与来源合并。"""
    counts = CrawlRunCounts()
    site = hostname_of(source.domain)
    unique: dict[str, RawItem] = {}
    for raw in items:
        fitted = _fit_item(raw)
        unique.setdefault(processor.dedup_key(fitted.company, fitted.title, fitted.event_date), fitted)
    if not unique:
        return counts
    existing = {
        row.dedup_key: row
        for row in db.scalars(select(CampusEvent).where(CampusEvent.dedup_key.in_(list(unique))))
    }
    for key, raw in unique.items():
        row = existing.get(key)
        if row is None:
            db.add(
                CampusEvent(
                    title=raw.title,
                    company=raw.company,
                    event_date=raw.event_date,
                    location=raw.location,
                    source_url=raw.source_url,
                    info_type=raw.info_type,
                    source_site=site,
                    dedup_key=key,
                    content_hash=processor.content_hash(raw),
                    status=InfoStatus.ACTIVE.value,
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
            counts.new += 1
            continue
        changed, writes = processor.merge_fields(row, raw)
        for field, value in writes.items():
            setattr(row, field, value)
        merged_site = processor.merge_source_sites(row.source_site, site, max_len=SOURCE_SITE_MAX_LEN)
        if merged_site != row.source_site:
            row.source_site = merged_site
        row.last_seen_at = now
        row.content_hash = processor.content_hash(row)
        if changed:
            row.status = InfoStatus.CHANGED.value
            row.changed_at = now
            counts.changed += 1
        else:
            counts.updated += 1
    db.flush()
    return counts


def _archive_expired(db: Session, now: datetime) -> int:
    """归档：未过期但活动日已过（自然日口径）→ 标 EXPIRED；EXPIRED 超 90 天 → 物理删除。"""
    today_start = datetime.combine(now.date(), time.min)
    result = db.execute(
        update(CampusEvent)
        .where(CampusEvent.status != InfoStatus.EXPIRED.value, CampusEvent.event_date < today_start)
        .values(status=InfoStatus.EXPIRED.value)
    )
    db.execute(
        delete(CampusEvent).where(
            CampusEvent.status == InfoStatus.EXPIRED.value,
            CampusEvent.event_date < processor.purge_before(now),
        )
    )
    return result.rowcount or 0


def _fit_item(raw: RawItem) -> RawItem:
    """字段长度保护：按列宽裁剪超长原文（站点标题 / 地点可能超出列宽）。"""
    clipped = {field: _clip(getattr(raw, field), limit) for field, limit in _FIELD_LIMITS.items()}
    return replace(raw, **clipped)


def _clip(value: str | None, limit: int) -> str | None:
    if not value:
        return None
    return value[:limit]


def _summarize(details: list[CrawlRunDetail], expired: int) -> CrawlRunData:
    """逐源结果汇总为整体响应。"""
    return CrawlRunData(
        total=len(details),
        ok=sum(1 for d in details if d.status == CrawlStatus.OK.value),
        failed=sum(1 for d in details if d.status == CrawlStatus.FAILED.value),
        blocked=sum(1 for d in details if d.status == CrawlStatus.BLOCKED.value),
        items_new=sum(d.counts.new for d in details),
        items_updated=sum(d.counts.updated for d in details),
        items_changed=sum(d.counts.changed for d in details),
        expired=expired,
        details=details,
    )


# ---------- 宣讲会 / 双选会查询 ----------


def list_campus_events(
    db: Session,
    user_id: int,
    *,
    info_type: str | None = None,
    city: str | None = None,
    keyword: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    include_expired: bool = False,
    sort: str = "time",
    page: int = 1,
    page_size: int = 10,
) -> PageData[CampusEventItem]:
    """宣讲会/双选会分页列表：过滤 → 画像打分 → 排序 → 内存分页（条目量为千级，一次算分可控）。"""
    if sort not in ("time", "match"):
        raise BizException(ErrorCode.PARAM_INVALID, "sort 仅支持 time / match")
    if info_type is not None and info_type not in {item.value for item in InfoType}:
        raise BizException(ErrorCode.PARAM_INVALID, "info_type 仅支持 TALK / FAIR")
    today_start = datetime.combine(date.today(), time.min)
    conditions = []
    if info_type:
        conditions.append(CampusEvent.info_type == info_type)
    if city:
        conditions.append(CampusEvent.location.like(f"%{city}%"))
    if keyword:
        conditions.append(
            or_(CampusEvent.title.like(f"%{keyword}%"), CampusEvent.company.like(f"%{keyword}%"))
        )
    if date_from:
        conditions.append(CampusEvent.event_date >= datetime.combine(date_from, time.min))
    if date_to:
        conditions.append(CampusEvent.event_date < datetime.combine(date_to + timedelta(days=1), time.min))
    if not include_expired:
        conditions.append(CampusEvent.status != InfoStatus.EXPIRED.value)
        conditions.append(CampusEvent.event_date >= today_start)
    rows = list(db.scalars(select(CampusEvent).where(*conditions)))
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    scored = [(row, processor.match_score(row, profile) if profile is not None else 0) for row in rows]
    if sort == "match":
        scored.sort(key=lambda pair: (-pair[1], pair[0].event_date, pair[0].id))
    else:
        scored.sort(key=lambda pair: (pair[0].event_date, pair[0].id))
    total = len(scored)
    start = (page - 1) * page_size
    page_rows = scored[start : start + page_size]
    site_map = map_source_sites(db, _sites_of(row for row, _ in page_rows))
    items = [_to_event_item(row, score, site_map) for row, score in page_rows]
    return PageData[CampusEventItem](total=total, items=items)


def overview_campus(db: Session) -> tuple[list[CampusEventBrief], datetime | None]:
    """概览「校招情报」区块：近期未过期的前若干条（按时间升序）+ 多源中最近一次采集时间。"""
    today_start = datetime.combine(date.today(), time.min)
    rows = list(
        db.scalars(
            select(CampusEvent)
            .where(CampusEvent.status != InfoStatus.EXPIRED.value, CampusEvent.event_date >= today_start)
            .order_by(CampusEvent.event_date.asc(), CampusEvent.id.asc())
            .limit(OVERVIEW_EVENT_LIMIT)
        )
    )
    site_map = map_source_sites(db, _sites_of(rows))
    briefs = [
        CampusEventBrief(
            id=row.id,
            title=row.title,
            company=row.company,
            event_date=row.event_date,
            location=row.location,
            source_url=row.source_url,
            source_site=_display_sites(row.source_site, site_map),
            info_type=row.info_type,
            status=row.status,
        )
        for row in rows
    ]
    last_crawl_at = db.scalar(select(func.max(CrawlSource.last_crawl_at)))
    return briefs, last_crawl_at


def hostname_of(url: str) -> str:
    """从完整地址取主机名——来源站点标识的存储形态（如 njust.91job.org.cn）。"""
    return (urlsplit(url).hostname or url).strip().rstrip("/")


def map_source_sites(db: Session, hosts: Iterable[str]) -> dict[str, str]:
    """站点标识（主机名）→ 下发名映射：取源配置的学校名；源已删除等映射不到时回退标识本身。"""
    unique_hosts = {host for host in hosts if host}
    site_map = {host: host for host in unique_hosts}
    if not unique_hosts:
        return site_map
    for domain, school_name in db.execute(select(CrawlSource.domain, CrawlSource.school_name)):
        host = hostname_of(domain)
        if host in unique_hosts:
            site_map[host] = school_name
    return site_map


def _sites_of(rows: Iterable[CampusEvent]) -> set[str]:
    """行集合的 source_site 串 → 站点标识集合。"""
    return {site for row in rows for site in (row.source_site or "").split(",") if site}


def _display_sites(raw: str | None, site_map: dict[str, str]) -> str | None:
    """站点标识串 → 下发名串：逐个映射、映射后同名去重（保序）。"""
    names: list[str] = []
    for host in (raw or "").split(","):
        if not host:
            continue
        name = site_map.get(host, host)
        if name not in names:
            names.append(name)
    return ",".join(names) or None


def _to_event_item(row: CampusEvent, score: int, site_map: dict[str, str]) -> CampusEventItem:
    return CampusEventItem(
        id=row.id,
        title=row.title,
        company=row.company,
        event_date=row.event_date,
        location=row.location,
        major_req=row.major_req,
        source_url=row.source_url,
        source_site=_display_sites(row.source_site, site_map),
        info_type=row.info_type,
        status=row.status,
        changed_at=row.changed_at,
        match_score=score,
    )


# ---------- 源配置 CRUD ----------


def list_sources(db: Session) -> list[CrawlSourceDTO]:
    """源清单（按 id 升序），含上次抓取状态。"""
    rows = db.scalars(select(CrawlSource).order_by(CrawlSource.id)).all()
    return [_to_source_dto(row) for row in rows]


def create_source(db: Session, payload: CrawlSourceCreateRequest) -> CrawlSourceDTO:
    """新增源：同一系统 + 同一域名重复登记 → 10003。"""
    school_name = payload.school_name.strip()
    if not school_name:
        raise BizException(ErrorCode.PARAM_INVALID, "学校名称不能为空")
    exists = db.scalar(
        select(CrawlSource).where(
            CrawlSource.system_type == payload.system_type.value, CrawlSource.domain == payload.domain
        )
    )
    if exists is not None:
        raise BizException(ErrorCode.CONFLICT, "同一系统下该域名已登记")
    row = CrawlSource(
        school_name=school_name,
        system_type=payload.system_type.value,
        domain=payload.domain,
        params=_dump_params(payload.params),
        enabled=1,
        created_at=datetime.now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_source_dto(row)


def update_source(db: Session, source_id: int, payload: CrawlSourceUpdateRequest) -> CrawlSourceDTO:
    """部分更新源：改 system_type（值不一致）→ 10001；编辑后重置最近采集状态（可即时重试）。"""
    row = db.get(CrawlSource, source_id)
    if row is None:
        raise BizException(ErrorCode.NOT_FOUND)
    if payload.system_type is not None and payload.system_type.value != row.system_type:
        raise BizException(ErrorCode.PARAM_INVALID, "不支持修改系统类型，请删除后重建")
    if payload.school_name is not None:
        school_name = payload.school_name.strip()
        if not school_name:
            raise BizException(ErrorCode.PARAM_INVALID, "学校名称不能为空")
        row.school_name = school_name
    if payload.domain is not None and payload.domain != row.domain:
        duplicate = db.scalar(
            select(CrawlSource).where(
                CrawlSource.system_type == row.system_type,
                CrawlSource.domain == payload.domain,
                CrawlSource.id != row.id,
            )
        )
        if duplicate is not None:
            raise BizException(ErrorCode.CONFLICT, "同一系统下该域名已登记")
        row.domain = payload.domain
    if payload.params is not None:
        row.params = _dump_params(payload.params)
    if payload.enabled is not None:
        row.enabled = int(payload.enabled)
    row.last_status = None
    row.last_error = None
    db.commit()
    db.refresh(row)
    return _to_source_dto(row)


def delete_source(db: Session, source_id: int) -> None:
    """删除源；已抓到的条目保留（无外键关联，不连带删除）。"""
    row = db.get(CrawlSource, source_id)
    if row is None:
        raise BizException(ErrorCode.NOT_FOUND)
    db.delete(row)
    db.commit()


def _to_source_dto(row: CrawlSource) -> CrawlSourceDTO:
    return CrawlSourceDTO(
        id=row.id,
        school_name=row.school_name,
        system_type=row.system_type,
        domain=row.domain,
        params=_load_params(row.params),
        enabled=bool(row.enabled),
        last_crawl_at=row.last_crawl_at,
        last_status=row.last_status,
        last_error=row.last_error,
    )


def _load_params(raw: str | None) -> dict | None:
    """库中 params JSON 文本 → 对象；空 / 非法 / 空对象一律回 null。"""
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) and data else None


def _dump_params(params: dict | None) -> str | None:
    """对象 → JSON 文本；空对象存 NULL（与"未配置"同义）。"""
    return json.dumps(params, ensure_ascii=False) if params else None
