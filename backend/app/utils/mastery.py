"""领域掌握度计算（系统设计 §5.10）。纯函数：无 IO、无 DB，可离线单测。

mastery = 100 × (0.6×近期表现 + 0.25×覆盖度 + 0.15×错题健康度) × 时间衰减
数值口径的调整集中在本模块常量，改参数不改调用方。
"""

from datetime import datetime

RECENT_WINDOW = 10  # 近期表现取最近多少次作答
COVERAGE_TARGET = 15  # 覆盖度饱和所需的不同题数（不要求练完整个领域）
DECAY_WEEKLY = 0.98  # 每周衰减系数
DECAY_FLOOR = 0.5  # 衰减下限（避免荒废领域直接归零、失去调度意义）
W_RECENT, W_COVERAGE, W_RETENTION = 0.6, 0.25, 0.15


def recent_score(scores: list[int | None]) -> float:
    """最近若干次作答的加权均值（越新权重越高），归一化到 0~1。"""
    recent = [s for s in scores[-RECENT_WINDOW:] if s is not None]
    if not recent:
        return 0.0
    weights = list(range(1, len(recent) + 1))  # 最旧权重 1，最新权重 n
    return sum(s * w for s, w in zip(recent, weights)) / (10 * sum(weights))


def coverage(covered_count: int, domain_total: int) -> float:
    """覆盖度：该领域练过的不同题数 / 目标题数，封顶 1。"""
    if domain_total <= 0:
        return 0.0
    return min(1.0, covered_count / min(domain_total, COVERAGE_TARGET))


def retention(mastered: int, ever_wrong: int) -> float:
    """错题健康度：已掌握 / 曾入本总数；从未入本视为 1。"""
    if ever_wrong <= 0:
        return 1.0
    return min(1.0, mastered / ever_wrong)


def decay(last_practiced_at: datetime | None, now: datetime) -> float:
    """时间衰减：每满一周乘 0.98，下限 DECAY_FLOOR。"""
    if last_practiced_at is None:
        return DECAY_FLOOR
    days = max(0.0, (now - last_practiced_at).total_seconds() / 86400)
    return max(DECAY_FLOOR, DECAY_WEEKLY ** (days / 7))


def compute_mastery(
    *,
    scores: list[int | None],
    covered_count: int,
    domain_total: int,
    mastered_count: int,
    ever_wrong_count: int,
    last_practiced_at: datetime | None,
    now: datetime,
) -> int:
    """算出 0~100 的掌握度（四舍五入）。"""
    base = (
        W_RECENT * recent_score(scores)
        + W_COVERAGE * coverage(covered_count, domain_total)
        + W_RETENTION * retention(mastered_count, ever_wrong_count)
    )
    return round(100 * base * decay(last_practiced_at, now))
