"""合规出网组件（NFR-016）：标识 UA、robots 检查、同域限频、状态码与跳转分流。

采集层是唯一的出网口：适配器与投喂链接抓取一律经本模块的 `fetch()` 发请求，不得自建网络调用。
合规红线（NFR-016）：① 请求带固定身份标识；② 抓前查 robots，明确禁止则停止该源；
③ 同域请求间隔 ≥2 秒；④ 429 暂停、403 停止不重试；⑤ 定时采集只存元数据与链接、不抓正文
（投喂通道为用户主动提供链接，抓正文以完成字段抽取，同样受本模块约束并经 SSRF 校验）。
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import threading
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from lxml import etree, html as lxml_html

from app.clients.crawler.base import SourceError

logger = logging.getLogger(__name__)

# 身份标识（NFR-016 ①）：HTTP 头值按 ASCII 编码，标识串必须纯 ASCII（含中文会致 httpx 直接编码失败）
USER_AGENT = "JobHunterBot/1.0 (+personal job-hunting assistant; non-commercial use)"
DOMAIN_INTERVAL = 2.0  # 同域（按主机名）最小请求间隔，秒
REQUEST_TIMEOUT = 10.0  # 单次请求超时，秒

_RATE_LOCK = threading.Lock()
_last_request_at: dict[str, float] = {}  # 主机名 → 上次请求时刻（单调钟）


def _wait_turn(host: str) -> None:
    """同域限频：距上次请求不足 DOMAIN_INTERVAL 则等待补足（含 robots 请求，同算一次出网）。"""
    with _RATE_LOCK:
        now = time.monotonic()
        last = _last_request_at.get(host)
        if last is not None:
            delay = DOMAIN_INTERVAL - (now - last)
            if delay > 0:
                time.sleep(delay)
                now = time.monotonic()
        _last_request_at[host] = now


def _new_client() -> httpx.Client:
    """自建客户端：不跟随环境代理（代理软件残留设置会导致请求全部 SSL 失败）。"""
    return httpx.Client(timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}, trust_env=False)


def _require_http(url: str) -> None:
    if urlsplit(url).scheme not in ("http", "https"):
        raise SourceError(f"仅支持 http/https 地址：{url}")


def _check_same_host(request_url: str, final_url: str) -> None:
    """跳转后仍须同主机：跨域跳转说明地址已失效或被劫持，终止该源。"""
    if (urlsplit(request_url).hostname or "") != (urlsplit(final_url).hostname or ""):
        raise SourceError("响应发生跨域跳转，已终止采集")


def fetch(url: str, *, method: str = "GET", json_body: dict | None = None) -> httpx.Response:
    """合规请求：带 UA → 同域限频 → 状态码分流。

    403 → SourceError(blocked)（停止该源不重试）；429 → SourceError（限流，本次采集暂停）；
    其余非 200 → SourceError；跨域跳转 → SourceError。返回值为 200 的响应。
    """
    _require_http(url)
    host = urlsplit(url).hostname or ""
    _wait_turn(host)
    try:
        with _new_client() as client:
            resp = client.request(method, url, json=json_body)
    except httpx.HTTPError as exc:
        raise SourceError(f"请求失败：{exc.__class__.__name__}") from exc
    if resp.status_code == 403:
        raise SourceError("站点拒绝访问（HTTP 403），按合规要求停止该源", blocked=True)
    if resp.status_code == 429:
        raise SourceError("站点限流（HTTP 429），本次采集暂停")
    if resp.status_code != 200:
        raise SourceError(f"请求返回 HTTP {resp.status_code}")
    _check_same_host(url, str(resp.url))
    return resp


def check_robots(domain: str) -> None:
    """抓取前的 robots 检查：明确禁止 → SourceError(blocked)；读不到（404 / 403 / 超时）按未声明处理。"""
    _require_http(domain)
    parts = urlsplit(domain)
    root = f"{parts.scheme}://{parts.netloc}/"
    _wait_turn(parts.hostname or "")
    try:
        with _new_client() as client:
            resp = client.get(f"{root}robots.txt")
    except httpx.HTTPError:
        return  # 网络异常按未声明处理，不阻塞采集
    if resp.status_code != 200:
        return  # 无 robots.txt 或拒绝提供，均按未声明处理
    parser = RobotFileParser()
    parser.parse(resp.text.splitlines())
    if not parser.can_fetch("JobHunterBot", root):
        raise SourceError("robots.txt 明确禁止抓取，按合规要求停止该源", blocked=True)


# ---------- 投喂链接抓取（POST /job-postings/ingest 的 url 通道） ----------

MIN_ARTICLE_LEN = 100  # 正文长度下限（低于此判为登录墙 / 空页面）
ARTICLE_MAX_LEN = 20000  # 提取正文限长（字符；送 LLM 前按 prompt 上限再截断）
# 登录墙提示词（在正文开头小范围内探测；命中即判需登录）
_LOGIN_HINTS = (
    "请先登录",
    "登录后查看",
    "登录后可见",
    "登录后继续",
    "登录以继续",
    "登录查看",
    "请登录",
    "需要登录",
    "log in",
    "login to",
    "sign in",
)


def check_public_url(url: str) -> None:
    """SSRF 防护（系统设计第 6 章）：仅 http/https，且主机解析出的全部 IP 均为公网地址。

    域名先解析再判定（IPv4 / IPv6 全量解析、IPv4-mapped 地址按其 IPv4 判定）；
    私网 / 环回 / 链路本地 / 保留 / 组播 / 未指定地址一律拒绝，解析失败同样拒绝。
    """
    _require_http(url)
    host = urlsplit(url).hostname
    if not host:
        raise SourceError("地址缺少主机名")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SourceError("域名无法解析") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.version == 6 and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise SourceError("仅支持公开网站链接，内网地址已拒绝")


def extract_article(html_text: str) -> str:
    """从 HTML 提取正文纯文本：剔除脚本 / 样式与页面框架（nav / header / footer），逐行压缩空行。"""
    try:
        doc = lxml_html.fromstring(html_text)
    except (etree.ParserError, ValueError) as exc:
        raise SourceError("页面内容无法解析") from exc
    for node in doc.xpath("//script|//style|//noscript|//template|//nav|//header|//footer"):
        node.drop_tree()
    lines = [" ".join(line.split()) for line in (doc.text_content() or "").splitlines()]
    return "\n".join(line for line in lines if line)[:ARTICLE_MAX_LEN]


def ensure_article(text: str) -> None:
    """登录墙 / 空页面启发式判定：正文过短或开头含登录提示词 → 拒绝（转 70003 降级手动填表）。"""
    if len(text) < MIN_ARTICLE_LEN:
        raise SourceError("页面正文过短，可能需要登录后查看")
    head = text[:500].lower()
    if any(hint in head for hint in _LOGIN_HINTS):
        raise SourceError("页面要求登录后查看")


def fetch_article(url: str) -> str:
    """投喂链接抓正文：SSRF 校验 → robots 检查 → 合规请求 → 正文提取与登录墙判定。

    任一步失败抛 SourceError，由服务层转 70003（message 区分原因），前端降级为手动填表。
    """
    check_public_url(url)
    parts = urlsplit(url)
    check_robots(f"{parts.scheme}://{parts.netloc}")
    resp = fetch(url)
    text = extract_article(resp.text)
    ensure_article(text)
    return text
