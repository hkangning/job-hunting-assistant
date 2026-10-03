"""合规出网组件（NFR-016）：标识 UA、robots 检查、同域限频、状态码与跳转分流。

采集层是唯一的出网口：适配器一律经本模块的 `fetch()` 发请求，不得自建网络调用。
合规红线（NFR-016）：① 请求带固定身份标识；② 抓前查 robots，明确禁止则停止该源；
③ 同域请求间隔 ≥2 秒；④ 429 暂停、403 停止不重试；⑤ 只存元数据与链接，不抓正文。
"""

from __future__ import annotations

import logging
import threading
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

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
