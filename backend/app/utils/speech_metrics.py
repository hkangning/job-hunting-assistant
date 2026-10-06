"""表达力指标计算（FR-014；系统设计 §5.6/§5.7、数据库设计 §3.19）。纯函数：无 IO、无 DB、不触发 LLM。

输入前端 VAD 分句时间轴 `segments`（`[{seq, start_ms, end_ms, text}]`，句间停顿仅前端可得），
输出 voice_metrics 快照字典（模拟面试与练习模式共用同一结构）；数值口径与阈值集中在本模块常量，
改参数不改调用方（与 mastery.py 同型）。
"""

from app.models.enums import VoiceQuality

METRICS_VERSION = 1  # 指标算法版本：口径调整后旧数据据此识别（跨版本不并列对比，数据库设计 §3.19）

MIN_DURATION_MS = 10_000  # 作答不足 10 秒不产出表达维度（SRS §3.11）
PAUSE_MIN_MS = 1_500  # 句间间隔 > 1.5s 记为停顿点
PAUSE_LOW_MS = 3_000  # 停顿分档：1.5~3 秒 LOW
PAUSE_HIGH_MS = 5_000  # 3~5 秒 HIGH；超过 SEVERE
PAUSE_CONTEXT_CHARS = 10  # 停顿点 context 取前一句末尾字数（供 LLM 判断是否构成知识点）

FILLERS = ("嗯", "呃", "那个", "就是", "然后")  # 填充词清单（SRS §3.11 明列五项）

TREND_IMPROVING, TREND_STABLE, TREND_DECLINING = "IMPROVING", "STABLE", "DECLINING"  # 流畅度趋势方向
TREND_BAND = 0.10  # 趋势判定带：首末段语速变化在 ±10% 内视为平稳


def compute_voice_metrics(segments: list[dict] | None) -> dict:
    """分句时间轴 → voice_metrics 快照（结构见数据库设计 §3.19）。

    质量分流（不产出表达维度的两种原因只做标记、不下发不落库）：
    - `segments is None`（纯文字作答）→ 仅 `{version, quality: TEXT_ONLY}`；
    - 传入数组但无有效内容（空数组 / 全静音）或作答不足 10 秒 → 基础量 + `TOO_SHORT`；
    - 其余 → 基础量 + 五项指标 + `OK`。

    基础量口径：总时长 = 末句结束 − 首句开始；有效语音时长 = 各句时长之和；字数 = 各句文本
    去空白后字符数（含标点）；字数为 0（全静音）与总时长不足均归 `TOO_SHORT`。
    """
    if segments is None:
        return {"version": METRICS_VERSION, "quality": VoiceQuality.TEXT_ONLY.value}

    texts = [_flat(item["text"]) for item in segments]
    total_ms = segments[-1]["end_ms"] - segments[0]["start_ms"] if segments else 0
    speech_ms = sum(max(0, item["end_ms"] - item["start_ms"]) for item in segments)
    char_count = sum(len(text) for text in texts)
    metrics = {
        "version": METRICS_VERSION,
        "quality": VoiceQuality.TOO_SHORT.value,
        "total_ms": total_ms,
        "speech_ms": speech_ms,
        "silence_ms": max(0, total_ms - speech_ms),
        "char_count": char_count,
    }
    if char_count == 0 or total_ms < MIN_DURATION_MS:
        return metrics

    metrics["quality"] = VoiceQuality.OK.value
    metrics["speech_rate"] = _speech_rate(char_count, speech_ms)
    metrics["speech_ratio"] = round(speech_ms / total_ms, 2)
    filler_detail = dict(zip(FILLERS, _filler_counts(texts)))
    filler_count = sum(filler_detail.values())
    metrics["filler_count"] = filler_count
    metrics["filler_rate"] = round(filler_count / char_count, 3)
    metrics["filler_detail"] = filler_detail
    metrics["pauses"] = _pauses(segments, texts)
    metrics["longest_pause_ms"] = max((p["duration_ms"] for p in metrics["pauses"]), default=0)
    metrics["fluency_trend"] = _fluency_trend(segments, texts)
    return metrics


def _flat(text: str) -> str:
    """去空白（指标口径按字符计，空白不计入字数与填充词匹配）。"""
    return "".join(text.split())


def _filler_counts(texts: list[str]) -> list[int]:
    """每个填充词的总出现次数（按 SRS §3.11 明列清单依次计数）。"""
    return [sum(text.count(filler) for text in texts) for filler in FILLERS]


def _speech_rate(char_count: int, speech_ms: int) -> int:
    """语速 = 字数 ÷ 有效语音时长（字/分钟），四舍五入取整。"""
    return round(char_count / (speech_ms / 60_000)) if speech_ms > 0 else 0


def _pauses(segments: list[dict], texts: list[str]) -> list[dict]:
    """停顿点：相邻句间隔 > 1.5s 的位置（`after_seq` 为前一句序号、`context` 为前一句末尾若干字）。"""
    pauses: list[dict] = []
    for prev, cur, prev_text in zip(segments, segments[1:], texts):
        gap = cur["start_ms"] - prev["end_ms"]
        if gap > PAUSE_MIN_MS:
            pauses.append(
                {
                    "after_seq": prev["seq"],
                    "duration_ms": gap,
                    "context": prev_text[-PAUSE_CONTEXT_CHARS:],
                    "level": _pause_level(gap),
                }
            )
    return pauses


def _pause_level(duration_ms: int) -> str:
    """停顿分档：LOW（1.5~3 秒）/ HIGH（3~5 秒）/ SEVERE（>5 秒）。"""
    if duration_ms <= PAUSE_LOW_MS:
        return "LOW"
    return "HIGH" if duration_ms <= PAUSE_HIGH_MS else "SEVERE"


def _fluency_trend(segments: list[dict], texts: list[str]) -> dict:
    """流畅度趋势：按句序均分前 / 中 / 后三段，各段语速与填充词数；方向按首末段语速变化判定。

    段数不足 2 段（单句等）或首段语速为 0 时无法比较，恒 `STABLE`。
    """
    groups = _split_segments(segments, texts)
    reports = []
    for index, group in enumerate(groups, start=1):
        group_chars = sum(len(text) for _, text in group)
        group_speech = sum(max(0, item["end_ms"] - item["start_ms"]) for item, _ in group)
        reports.append(
            {
                "seg": index,
                "speech_rate": _speech_rate(group_chars, group_speech),
                "filler_count": sum(text.count(filler) for _, text in group for filler in FILLERS),
            }
        )
    return {"direction": _trend_direction(reports), "segments": reports}


def _split_segments(segments: list[dict], texts: list[str]) -> list[list[tuple[dict, str]]]:
    """按句序均分三段（余数分给靠前的段），空段剔除；单句时仅一段。"""
    count = len(segments)
    sizes = [count // 3 + (1 if index < count % 3 else 0) for index in range(3)]
    groups: list[list[tuple[dict, str]]] = []
    start = 0
    for size in sizes:
        if size:
            groups.append(list(zip(segments[start : start + size], texts[start : start + size])))
        start += size
    return groups


def _trend_direction(reports: list[dict]) -> str:
    """首末段语速变化 > +10% 递增、< −10% 下降、带内平稳（段数不足或首段为 0 恒平稳）。"""
    if len(reports) < 2 or reports[0]["speech_rate"] == 0:
        return TREND_STABLE
    change = (reports[-1]["speech_rate"] - reports[0]["speech_rate"]) / reports[0]["speech_rate"]
    if change > TREND_BAND:
        return TREND_IMPROVING
    return TREND_DECLINING if change < -TREND_BAND else TREND_STABLE
