"""适配器注册表：系统类型（CrawlSystemType）→ 解析入口。"""

from app.clients.crawler.adapters import bysjy, job91, jysd

ADAPTERS = {
    "91JOB": job91.fetch,
    "BYSJY": bysjy.fetch,
    "JYSD": jysd.fetch,
}
