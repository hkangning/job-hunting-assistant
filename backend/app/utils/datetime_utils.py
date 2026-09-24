"""时间格式化与日期序列工具：接口口径为时间 `YYYY-MM-DD HH:mm:ss`、日期 `YYYY-MM-DD`，一律本地时间（接口文档 1.1）。"""

from datetime import date, datetime, time, timedelta

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"


def format_datetime(value: datetime | None) -> str | None:
    """datetime → `YYYY-MM-DD HH:mm:ss`；None 原样返回（供 DTO 可选字段序列化）。"""
    return value.strftime(DATETIME_FORMAT) if value else None


def format_date(value: date | None) -> str | None:
    """date → `YYYY-MM-DD`；None 原样返回。"""
    return value.strftime(DATE_FORMAT) if value else None


def to_datetime(value: date) -> datetime:
    """日期 → 当天 00:00:00（库内时间字段统一存 datetime，数据库设计 §1）。"""
    return datetime.combine(value, time.min)


def date_range(end: date, days: int) -> list[date]:
    """以 end 结尾、长度 days 的连续日期列表（趋势统计补齐 0 值日期用）。"""
    return [end - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
