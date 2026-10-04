"""校招情报服务：源配置 CRUD、多源采集编排、宣讲会/双选会与岗位查询、投喂、订阅与推送（FR-021/022，系统设计 5.9）。

采集编排：逐源独立事务与异常隔离——单源失败不回滚其他源、不中断整体任务（TC-23 手工验收项）；
互斥：手动触发与每日任务共用一把进程内锁，执行中再次触发直接返回 None（不排队）。
订阅匹配：采集落库后逐账号过启用规则（维度间 AND、维度内 OR），命中写 INFO_MATCH 提醒；
候选仅公共信息（campus_event 与 job_posting 的 user_id=0 记录），投喂记录不参与推送。
"""

import json
import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from urllib.parse import urlsplit

from sqlalchemy import ColumnElement, delete, false, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.clients.crawler import compliance, processor
from app.clients.crawler.base import RawItem, SourceError, get_adapter
from app.clients.llm_client import LLMClient, LLMError, resolve_config
from app.database import SYSTEM_USER_ID, SessionLocal
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
    SubscriptionInfoType,
)
from app.prompts import build_ingest_extract_messages
from app.schemas.campus import (
    CalendarEventItem,
    CampusEventBrief,
    CampusEventItem,
    CrawlRunCounts,
    CrawlRunData,
    CrawlRunDetail,
    CrawlSourceCreateRequest,
    CrawlSourceDTO,
    CrawlSourceUpdateRequest,
    JobPostingBrief,
    JobPostingCreateRequest,
    JobPostingIngestData,
    JobPostingIngestRequest,
    JobPostingItem,
    SubscriptionCreateRequest,
    SubscriptionDTO,
    SubscriptionUpdateRequest,
)
from app.schemas.common import PageData

logger = logging.getLogger(__name__)

_CRAWL_LOCK = threading.Lock()  # 采集任务互斥（手动与每日共用）
OVERVIEW_EVENT_LIMIT = 5  # 概览「校招情报」区块返回的宣讲会/双选会条数
OVERVIEW_JOB_LIMIT = 3  # 概览「校招情报」区块返回的岗位条数（按匹配打分降序）
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
            return run_crawl(db, skip_recent=True, with_match=False)
    except BizException:
        logger.info("校招信息采集任务正在执行中，本次触发跳过")
        return None
    except Exception:
        logger.exception("校招信息采集任务异常")
        return None


def run_crawl(
    db: Session, *, source_id: int | None = None, skip_recent: bool = False, with_match: bool = True
) -> CrawlRunData:
    """执行采集：指定 source_id 只跑单个源（手动调试，不受启用开关限制），否则跑全部启用源。

    `skip_recent=True`（每日任务）时跳过今天已抓过的源（每源每日 1 次，NFR-016）；
    `with_match=True`（手动路径）时在任一源成功后触发订阅匹配；每日任务传 False——
    由 run_daily 在采集后统一调 `match_new_items` 并把命中数计入提醒生成数；
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
        crawled_ok = any(detail.status == CrawlStatus.OK.value for detail in details)
        if crawled_ok:
            # 仅当本次存在任一成功源时才归档：源全挂时不算"活动已过期"，避免误标（见系统设计 5.9）
            expired = _archive_expired(db, now)
            db.commit()
            if with_match:
                match_new_items(db, now=now)
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
    source_site: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    include_expired: bool = False,
    sort: str = "time",
    page: int = 1,
    page_size: int = 10,
) -> PageData[CampusEventItem]:
    """宣讲会/双选会分页列表：过滤 → 画像打分 → 排序 → 内存分页（条目量为千级，一次算分可控）。

    source_site 收来源学校名（与下发口径一致）：命中该校任一来源的条目即返回（跨源合并条目命中）；
    未匹配到任何来源学校时返回空集。
    """
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
    if source_site:
        conditions.append(
            _source_site_condition(CampusEvent.source_site, _school_hosts(db, source_site))
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


def _sites_of(rows: Iterable[CampusEvent | JobPosting]) -> set[str]:
    """行集合的 source_site 串 → 站点标识集合（活动与岗位行通用）。"""
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


def _school_hosts(db: Session, school_name: str) -> list[str]:
    """来源学校名 → 站点主机名集合（按 `crawl_source` 反查，一校多源返回多个、去重保序）。"""
    hosts: list[str] = []
    for (domain,) in db.execute(
        select(CrawlSource.domain).where(CrawlSource.school_name == school_name)
    ):
        host = hostname_of(domain)
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def _source_site_condition(column: InstrumentedAttribute, hosts: list[str]) -> ColumnElement[bool]:
    """source_site 串（逗号分隔主机名）精确命中任一所查主机名的条件；无匹配主机名时恒不命中。

    按「整串 / 前缀 / 后缀 / 中段」四式精确匹配，避免域名后缀子串误撞（如 a.edu.cn 撞上 ba.edu.cn）。
    """
    if not hosts:
        return false()
    clauses: list[ColumnElement[bool]] = []
    for host in hosts:
        clauses.extend(
            (
                column == host,
                column.like(f"{host},%"),
                column.like(f"%,{host}"),
                column.like(f"%,{host},%"),
            )
        )
    return or_(*clauses)


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


# ---------- 岗位（/job-postings 与概览） ----------

# 投喂抽取字段顺序（missing 提示按此列出）；列宽上限对齐 job_posting 列宽，job_type / deadline 单独归一
_INGEST_FIELDS = ("title", "company", "city", "edu_req", "major_req", "salary_text", "job_type", "deadline")
_INGEST_FIELD_LIMITS = {"title": 200, "company": 100, "city": 50, "edu_req": 50, "major_req": 300, "salary_text": 100}


def list_job_postings(
    db: Session,
    user_id: int,
    *,
    city: str | None = None,
    company: str | None = None,
    job_type: str | None = None,
    keyword: str | None = None,
    source_site: str | None = None,
    status: str | None = None,
    sort: str = "time",
    page: int = 1,
    page_size: int = 10,
) -> PageData[JobPostingItem]:
    """岗位分页列表：公共岗位（user_id=0）+ 本账号投喂；过滤 → 打分 → 排序 → 内存分页。

    status 口径：不传或传 ACTIVE → ACTIVE + CHANGED（内容变更中的仍可见、前端打角标）；
    传 CHANGED / EXPIRED 精确过滤；其余值 → 10001。
    source_site 收来源学校名（与下发口径一致），语义同宣讲会列表；投喂岗位无来源（source_site 为空），
    不会被任何来源筛选命中。
    """
    if sort not in ("time", "match"):
        raise BizException(ErrorCode.PARAM_INVALID, "sort 仅支持 time / match")
    if job_type is not None and job_type not in {item.value for item in JobType}:
        raise BizException(ErrorCode.PARAM_INVALID, "job_type 仅支持 CAMPUS / INTERN / SOCIAL")
    conditions = [JobPosting.user_id.in_((SYSTEM_USER_ID, user_id))]
    if status in (None, "", InfoStatus.ACTIVE.value):
        conditions.append(JobPosting.status.in_((InfoStatus.ACTIVE.value, InfoStatus.CHANGED.value)))
    elif status in (InfoStatus.CHANGED.value, InfoStatus.EXPIRED.value):
        conditions.append(JobPosting.status == status)
    else:
        raise BizException(ErrorCode.PARAM_INVALID, "status 仅支持 ACTIVE / CHANGED / EXPIRED")
    if city:
        conditions.append(JobPosting.city == city)
    if company:
        conditions.append(JobPosting.company.like(f"%{company}%"))
    if job_type:
        conditions.append(JobPosting.job_type == job_type)
    if keyword:
        conditions.append(
            or_(JobPosting.title.like(f"%{keyword}%"), JobPosting.company.like(f"%{keyword}%"))
        )
    if source_site:
        conditions.append(
            _source_site_condition(JobPosting.source_site, _school_hosts(db, source_site))
        )
    rows = list(db.scalars(select(JobPosting).where(*conditions)))
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    scored = [(row, processor.match_score(row, profile) if profile is not None else 0) for row in rows]
    if sort == "match":
        scored.sort(key=lambda pair: (pair[1], pair[0].first_seen_at, pair[0].id), reverse=True)
    else:
        scored.sort(key=lambda pair: (pair[0].first_seen_at, pair[0].id), reverse=True)
    total = len(scored)
    start = (page - 1) * page_size
    page_rows = scored[start : start + page_size]
    site_map = map_source_sites(db, _sites_of(row for row, _ in page_rows))
    applied = _applied_keys(db, user_id)
    items = [_to_posting_item(row, score, site_map, applied) for row, score in page_rows]
    return PageData[JobPostingItem](total=total, items=items)


def top_job_postings(db: Session, user_id: int, *, limit: int = OVERVIEW_JOB_LIMIT) -> list[JobPostingBrief]:
    """概览「校招情报」区块：匹配打分最高的若干条（公共 + 本账号投喂，过滤已过期）。"""
    rows = list(
        db.scalars(
            select(JobPosting).where(
                JobPosting.user_id.in_((SYSTEM_USER_ID, user_id)),
                JobPosting.status != InfoStatus.EXPIRED.value,
            )
        )
    )
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    scored = [(row, processor.match_score(row, profile) if profile is not None else 0) for row in rows]
    scored.sort(key=lambda pair: (pair[1], pair[0].first_seen_at, pair[0].id), reverse=True)
    top = scored[:limit]
    site_map = map_source_sites(db, _sites_of(row for row, _ in top))
    applied = _applied_keys(db, user_id)
    return [
        JobPostingBrief(
            id=row.id,
            title=row.title,
            company=row.company,
            city=row.city,
            job_type=row.job_type,
            deadline=row.deadline,
            source_site=_display_sites(row.source_site, site_map),
            source_url=row.source_url,
            match_score=score,
            is_applied=_is_applied(row, applied),
        )
        for row, score in top
    ]


def ingest_job_posting(
    db: Session, user_id: int, payload: JobPostingIngestRequest, *, client: LLMClient
) -> JobPostingIngestData:
    """投喂抽取预览（不落库）：text / url 二选一 → 取原文 → LLM 抽取字段 → 返回预览。

    url 通道经合规组件抓正文（SSRF 校验 / robots / 登录墙判定）；链接抓取失败与抽取不可解析
    均 → 70003（message 区分两类原因），前端降级为手动填表；其余 LLM 错误（未配置 / 鉴权）透传。
    """
    text = (payload.text or "").strip()
    url = (payload.url or "").strip()
    if text and url:
        raise BizException(ErrorCode.PARAM_INVALID, "text 与 url 只能二选一")
    if not text and not url:
        raise BizException(ErrorCode.PARAM_INVALID, "请提供 JD 原文或招聘链接")
    if url:
        try:
            source_text = compliance.fetch_article(url)
        except SourceError as exc:
            raise BizException(ErrorCode.INGEST_PARSE_FAILED, f"链接抓取失败：{exc}") from exc
    else:
        source_text = text
    config = resolve_config(db, user_id)
    try:
        extracted = client.chat_json(config, build_ingest_extract_messages(source_text))
    except LLMError as exc:
        if exc.code != ErrorCode.LLM_OUTPUT_INVALID:
            raise
        raise BizException(
            ErrorCode.INGEST_PARSE_FAILED, "AI 未能从原文中解析出岗位信息，请补充说明或手动填写"
        ) from exc
    fields = _clean_ingest_fields(extracted)
    if fields is None:
        raise BizException(ErrorCode.INGEST_PARSE_FAILED, "AI 未能从原文中解析出岗位信息，请补充说明或手动填写")
    missing = [name for name in _INGEST_FIELDS if fields[name] is None]
    return JobPostingIngestData(
        fields=fields,
        missing=missing,
        source=IngestSource.FEED.value,
        fetched_from="url" if url else "text",
    )


def create_job_posting(db: Session, user_id: int, payload: JobPostingCreateRequest) -> JobPostingItem:
    """确认入库（投喂通道）：同账号同指纹已存在则覆盖更新（不报错、不重复入库）；AUTO 记录不受影响。"""
    title = payload.title.strip()
    company = payload.company.strip()
    if not title or not company:
        raise BizException(ErrorCode.PARAM_INVALID, "岗位名称与公司名称不能为空")
    city = _clean_optional(payload.city)
    edu_req = _clean_optional(payload.edu_req)
    major_req = _clean_optional(payload.major_req)
    salary_text = _clean_optional(payload.salary_text)
    source_url = _clean_optional(payload.source_url)
    raw_excerpt = _clean_optional(payload.raw_excerpt)
    job_type = payload.job_type.value if payload.job_type else None
    now = datetime.now()
    dedup_key = processor.posting_dedup_key(company, title, city)
    row = db.scalar(
        select(JobPosting).where(JobPosting.user_id == user_id, JobPosting.dedup_key == dedup_key)
    )
    if row is None:
        row = JobPosting(
            user_id=user_id,
            title=title,
            company=company,
            city=city,
            edu_req=edu_req,
            major_req=major_req,
            salary_text=salary_text,
            job_type=job_type,
            deadline=payload.deadline,
            source_url=source_url,
            raw_excerpt=raw_excerpt,
            ingest_source=IngestSource.FEED.value,
            dedup_key=dedup_key,
            status=InfoStatus.ACTIVE.value,
            first_seen_at=now,
            last_seen_at=now,
        )
        row.content_hash = processor.posting_content_hash(row)
        db.add(row)
    else:
        # 同账号重复投喂同一岗位：以本次提交为准全量覆盖，状态复位为有效
        row.title = title
        row.company = company
        row.city = city
        row.edu_req = edu_req
        row.major_req = major_req
        row.salary_text = salary_text
        row.job_type = job_type
        row.deadline = payload.deadline
        row.source_url = source_url
        row.raw_excerpt = raw_excerpt
        row.status = InfoStatus.ACTIVE.value
        row.changed_at = None
        row.last_seen_at = now
        row.content_hash = processor.posting_content_hash(row)
    db.commit()
    db.refresh(row)
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    score = processor.match_score(row, profile) if profile is not None else 0
    site_map = map_source_sites(db, _sites_of([row]))
    return _to_posting_item(row, score, site_map, _applied_keys(db, user_id))


def delete_job_posting(db: Session, user_id: int, posting_id: int) -> None:
    """删除投喂岗位：自动抓取的公共岗位（user_id=0）不可删除 → 10001；不存在或非本账号 → 10002。"""
    row = db.get(JobPosting, posting_id)
    if row is None or row.user_id not in (SYSTEM_USER_ID, user_id):
        raise BizException(ErrorCode.NOT_FOUND)
    if row.user_id == SYSTEM_USER_ID:
        raise BizException(ErrorCode.PARAM_INVALID, "自动抓取的岗位不可删除")
    db.delete(row)
    db.commit()


def _clean_ingest_fields(data) -> dict | None:
    """抽取结果清洗：字符串裁剪、枚举与日期归一；非对象或全部字段为空视为抽取失败（返回 None）。"""
    if not isinstance(data, dict):
        return None
    fields: dict = {
        name: _clean_str(data.get(name), _INGEST_FIELD_LIMITS[name])
        for name in ("title", "company", "city", "edu_req", "major_req", "salary_text")
    }
    job_type = _clean_str(data.get("job_type"), 20)
    fields["job_type"] = job_type if job_type in {item.value for item in JobType} else None
    fields["deadline"] = _normalize_deadline(_clean_str(data.get("deadline"), 20))
    return fields if any(value is not None for value in fields.values()) else None


def _clean_str(value, limit: int) -> str | None:
    """抽取字段的字符串归一：非字符串与空串一律回 None，超长裁剪。"""
    if not isinstance(value, str):
        return None
    return value.strip()[:limit] or None


def _normalize_deadline(value: str | None) -> str | None:
    """截止时间归一为 YYYY-MM-DD 字符串（预览展示与回传入库共用）；非法格式丢弃。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _clean_optional(value: str | None) -> str | None:
    """可选文本归一：strip 后空串转 None（与库中「未填」同口径）。"""
    if value is None:
        return None
    return value.strip() or None


def _applied_keys(db: Session, user_id: int) -> set[tuple[str, str]]:
    """本账号投递记录的（归一公司, 归一岗位）集合，用于 is_applied 判定。"""
    return {
        (processor.normalize_company(app.company), processor.normalize_text(app.position))
        for app in db.scalars(select(Application).where(Application.user_id == user_id))
    }


def _is_applied(row: JobPosting, applied: set[tuple[str, str]]) -> bool:
    """已投递判定：按归一化公司 + 岗位名比对（与投递记录的展示原文无关）。"""
    return (processor.normalize_company(row.company), processor.normalize_text(row.title)) in applied


def _to_posting_item(
    row: JobPosting, score: int, site_map: dict[str, str], applied: set[tuple[str, str]]
) -> JobPostingItem:
    return JobPostingItem(
        id=row.id,
        title=row.title,
        company=row.company,
        city=row.city,
        edu_req=row.edu_req,
        major_req=row.major_req,
        salary_text=row.salary_text,
        job_type=row.job_type,
        deadline=row.deadline,
        source_site=_display_sites(row.source_site, site_map),
        source_url=row.source_url,
        ingest_source=row.ingest_source,
        status=row.status,
        first_seen_at=row.first_seen_at,
        changed_at=row.changed_at,
        match_score=score,
        is_applied=_is_applied(row, applied),
    )


# ---------- 日历（/calendar） ----------


def list_calendar(db: Session, user_id: int, *, start: date, end: date) -> list[CalendarEventItem]:
    """日历事件聚合（四类）：活动按 event_date 命中区间；投递按 next_event_at 命中且状态为待笔试/面试。

    区间按自然日闭合展开（[start 00:00, end+1 00:00)）；宣讲会/双选会含已过期条目（历史日历可见）；
    排序按事件时间升序，同一时刻按来源表与 id 稳定排列。end 早于 start → 10001。
    """
    if end < start:
        raise BizException(ErrorCode.PARAM_INVALID, "end 不能早于 start")
    begin = datetime.combine(start, time.min)
    finish = datetime.combine(end + timedelta(days=1), time.min)
    events: list[CalendarEventItem] = []
    rows = db.scalars(
        select(CampusEvent).where(CampusEvent.event_date >= begin, CampusEvent.event_date < finish)
    )
    for row in rows:
        events.append(
            CalendarEventItem(
                event_type=row.info_type,
                title=row.title,
                event_at=row.event_date,
                ref_type="campus_event",
                ref_id=row.id,
                company=row.company,
                location=row.location,
                status=row.status,
            )
        )
    applications = db.scalars(
        select(Application).where(
            Application.user_id == user_id,
            Application.next_event_at >= begin,
            Application.next_event_at < finish,
            Application.status.in_((ApplicationStatus.WRITTEN.value, ApplicationStatus.INTERVIEW.value)),
        )
    )
    for app in applications:
        events.append(
            CalendarEventItem(
                event_type="EXAM" if app.status == ApplicationStatus.WRITTEN.value else "INTERVIEW",
                title=app.position,
                event_at=app.next_event_at,
                ref_type="application",
                ref_id=app.id,
                company=app.company,
                location=None,
                status=app.status,
            )
        )
    events.sort(key=lambda event: (event.event_at, event.ref_type, event.ref_id))
    return events


# ---------- 订阅规则（/subscriptions） ----------

_SUBSCRIPTION_ARRAY_LIMIT = 20  # 每个维度的最大条目数
_SUBSCRIPTION_ITEM_LIMIT = 50  # 每个条目的最大长度（JSON 文本存储，防单项超长）


def list_subscriptions(db: Session, user_id: int) -> list[SubscriptionDTO]:
    """本账号订阅规则清单（按创建顺序）。"""
    rows = db.scalars(
        select(Subscription).where(Subscription.user_id == user_id).order_by(Subscription.id)
    ).all()
    return [_to_subscription_dto(row) for row in rows]


def create_subscription(db: Session, user_id: int, payload: SubscriptionCreateRequest) -> SubscriptionDTO:
    """新增订阅规则：数组字段逐项清洗（去空 / 去重 / 截断），空数组存 NULL（= 该维度不限）。"""
    name = payload.name.strip()
    if not name:
        raise BizException(ErrorCode.PARAM_INVALID, "规则名称不能为空")
    row = Subscription(
        user_id=user_id,
        name=name,
        keywords=_dump_array(_clean_array(payload.keywords)),
        companies=_dump_array(_clean_array(payload.companies)),
        cities=_dump_array(_clean_array(payload.cities)),
        info_types=_dump_array(_clean_array([item.value for item in payload.info_types or []])),
        enabled=int(payload.enabled),
        created_at=datetime.now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_subscription_dto(row)


def update_subscription(
    db: Session, user_id: int, subscription_id: int, payload: SubscriptionUpdateRequest
) -> SubscriptionDTO:
    """部分更新订阅规则：未传字段保持原值，传空数组 = 清空该维度；不存在或非本账号 → 10002。"""
    row = db.get(Subscription, subscription_id)
    if row is None or row.user_id != user_id:
        raise BizException(ErrorCode.NOT_FOUND)
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise BizException(ErrorCode.PARAM_INVALID, "规则名称不能为空")
        row.name = name
    if payload.keywords is not None:
        row.keywords = _dump_array(_clean_array(payload.keywords))
    if payload.companies is not None:
        row.companies = _dump_array(_clean_array(payload.companies))
    if payload.cities is not None:
        row.cities = _dump_array(_clean_array(payload.cities))
    if payload.info_types is not None:
        row.info_types = _dump_array(_clean_array([item.value for item in payload.info_types]))
    if payload.enabled is not None:
        row.enabled = int(payload.enabled)
    db.commit()
    db.refresh(row)
    return _to_subscription_dto(row)


def delete_subscription(db: Session, user_id: int, subscription_id: int) -> None:
    """删除订阅规则；不存在或非本账号 → 10002。"""
    row = db.get(Subscription, subscription_id)
    if row is None or row.user_id != user_id:
        raise BizException(ErrorCode.NOT_FOUND)
    db.delete(row)
    db.commit()


def _clean_array(values: list[str] | None) -> list[str]:
    """数组清洗：逐项 strip、去空、保序去重、逐项截断，整组限长。"""
    cleaned: list[str] = []
    for value in values or []:
        item = str(value).strip()[:_SUBSCRIPTION_ITEM_LIMIT]
        if item and item not in cleaned:
            cleaned.append(item)
    return cleaned[:_SUBSCRIPTION_ARRAY_LIMIT]


def _dump_array(values: list[str] | None) -> str | None:
    """数组 → JSON 文本；空列表存 NULL（与「该维度不限」同义）。"""
    return json.dumps(values, ensure_ascii=False) if values else None


def _load_array(raw: str | None) -> list[str]:
    """库中 JSON 文本 → 字符串数组；空 / 非法 / 非数组一律回空列表。"""
    try:
        data = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in data] if isinstance(data, list) else []


def _to_subscription_dto(row: Subscription) -> SubscriptionDTO:
    return SubscriptionDTO(
        id=row.id,
        name=row.name,
        keywords=_load_array(row.keywords),
        companies=_load_array(row.companies),
        cities=_load_array(row.cities),
        info_types=_load_array(row.info_types),
        enabled=bool(row.enabled),
        created_at=row.created_at,
    )


# ---------- 订阅匹配与推送（FR-022） ----------


@dataclass(frozen=True)
class SubscriptionRule:
    """订阅规则解析后的形态（JSON 文本 → 数组元组），供匹配判定使用。"""

    keywords: tuple[str, ...]
    companies: tuple[str, ...]
    cities: tuple[str, ...]
    info_types: tuple[str, ...]


def match_new_items(db: Session, *, now: datetime | None = None) -> int:
    """订阅匹配：今天新入库/变更的公共信息 × 全部账号的启用规则 → 写 INFO_MATCH 提醒。

    候选仅公共信息（campus_event + job_posting 的 user_id=0 记录）——投喂记录不参与推送，
    避免「自己刚录的岗位提醒自己」（数据库设计 3.22 匹配范围补注）；
    重复提醒由 reminder 唯一约束兜底（先查后插 + SAVEPOINT 防并发冲突）。返回新增提醒条数。
    """
    now = now or datetime.now()
    today_start = datetime.combine(now.date(), time.min)
    campus_rows = list(
        db.scalars(
            select(CampusEvent).where(
                CampusEvent.status != InfoStatus.EXPIRED.value,
                or_(CampusEvent.first_seen_at >= today_start, CampusEvent.changed_at >= today_start),
            )
        )
    )
    posting_rows = list(
        db.scalars(
            select(JobPosting).where(
                JobPosting.user_id == SYSTEM_USER_ID,
                JobPosting.status != InfoStatus.EXPIRED.value,
                or_(JobPosting.first_seen_at >= today_start, JobPosting.changed_at >= today_start),
            )
        )
    )
    if not campus_rows and not posting_rows:
        return 0
    generated = 0
    for user_id in db.scalars(select(User.id)).all():
        rules = [
            _parse_rule(row)
            for row in db.scalars(
                select(Subscription).where(Subscription.user_id == user_id, Subscription.enabled == 1)
            )
        ]
        if not rules:
            continue
        for rule in rules:
            for row in campus_rows:
                if _rule_hits(rule, row, row.info_type) and _write_match_reminder(
                    db, user_id, row, "campus_event", now
                ):
                    generated += 1
            for row in posting_rows:
                if _rule_hits(rule, row, SubscriptionInfoType.JOB.value) and _write_match_reminder(
                    db, user_id, row, "job_posting", now
                ):
                    generated += 1
    db.commit()
    return generated


def _parse_rule(row: Subscription) -> SubscriptionRule:
    """订阅规则行 → 匹配用形态（四个维度各自解析为数组元组，空 = 不限）。"""
    return SubscriptionRule(
        keywords=tuple(_load_array(row.keywords)),
        companies=tuple(_load_array(row.companies)),
        cities=tuple(_load_array(row.cities)),
        info_types=tuple(_load_array(row.info_types)),
    )


def _rule_hits(rule: SubscriptionRule, item, kind: str) -> bool:
    """订阅命中判定（纯逻辑）：维度间 AND、维度内 OR、留空不限。

    关键词命中标题或公司名（归一化包含）；公司维度按去括号口径比较；城市维度岗位读 `city`、
    活动回退 `location`；`item` 为鸭子类型（CampusEvent / JobPosting 行均可）。
    """
    if rule.info_types and kind not in rule.info_types:
        return False
    if rule.keywords and not (
        _hit_field(getattr(item, "title", None), rule.keywords)
        or _hit_field(getattr(item, "company", None), rule.keywords)
    ):
        return False
    if rule.companies and not _hit_company(getattr(item, "company", None), rule.companies):
        return False
    if rule.cities:
        city_text = getattr(item, "city", None) or getattr(item, "location", None)
        if not _hit_field(city_text, rule.cities):
            return False
    return True


def _hit_field(field_text: str | None, keywords: tuple[str, ...]) -> bool:
    """归一化包含判定：字段或关键词为空均不命中（与匹配打分的口径同源）。"""
    if not field_text or not keywords:
        return False
    haystack = processor.normalize_text(field_text)
    return any(processor.normalize_text(keyword) in haystack for keyword in keywords if keyword)


def _hit_company(company: str | None, keywords: tuple[str, ...]) -> bool:
    """公司名维度：按去括号口径比较（「字节跳动」可命中「字节跳动（南京）有限公司」）。"""
    if not company or not keywords:
        return False
    haystack = processor.normalize_company(company)
    return any(processor.normalize_company(keyword) in haystack for keyword in keywords if keyword)


def _write_match_reminder(db: Session, user_id: int, item, ref_type: str, now: datetime) -> bool:
    """写一条 INFO_MATCH 提醒；同账号同条目同日已存在 → 跳过（返回 False）。

    唯一约束不含 ref_type（两来源表的 id 可能撞值）——查重同样不区分来源表，命中即视为已有提醒
    （已知边界，数据库设计 3.12）；插入撞唯一约束由 SAVEPOINT 兜底（并发场景，不影响同批其余写入）。
    """
    remind_date = now.date()
    exists = db.scalar(
        select(Reminder.id).where(
            Reminder.user_id == user_id,
            Reminder.reminder_type == ReminderType.INFO_MATCH.value,
            Reminder.ref_id == item.id,
            Reminder.remind_date == remind_date,
        )
    )
    if exists is not None:
        return False
    try:
        with db.begin_nested():
            db.add(
                Reminder(
                    user_id=user_id,
                    reminder_type=ReminderType.INFO_MATCH.value,
                    ref_id=item.id,
                    ref_type=ref_type,
                    content=_match_text(item, ref_type),
                    remind_date=remind_date,
                    checked=0,
                    created_at=now,
                )
            )
        return True
    except IntegrityError:
        logger.info("订阅提醒撞唯一约束（user=%s ref=%s），跳过", user_id, item.id)
        return False


def _match_text(item, ref_type: str) -> str:
    """INFO_MATCH 提醒模板文案（不调 LLM，系统设计 5.9）。"""
    prefix = f"{item.company} 的" if item.company else ""
    if ref_type == "campus_event":
        label = "宣讲会" if item.info_type == InfoType.TALK.value else "双选会"
        when = item.event_date.strftime("%m-%d %H:%M")
        where = f"，地点：{item.location}" if item.location else ""
        return f"订阅命中：{prefix}{label}「{item.title}」将于 {when} 举行{where}，去看看吧"
    city = f"（{item.city}）" if item.city else ""
    tail = f"，{item.deadline.strftime('%m-%d')} 截止，尽快查看" if item.deadline else "，去看看吧"
    return f"订阅命中：{prefix}岗位「{item.title}」{city}{tail}"


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
