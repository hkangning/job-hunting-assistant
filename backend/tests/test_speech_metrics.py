"""TC-71：表达力指标纯函数单测（FR-014；接口文档 v1.50 §3.7、台账 #119 ①）。

`compute_voice_metrics` 零依赖（无 IO / 无 DB / 不触发 LLM），直接调用即可——
边界含：`None`（文字作答）/ 空数组 / 全静音 / 不足 10 秒；正常样例的每一项指标
与**手算常量**逐项比对（判据与 LLM 无关，构造的 segments 即唯一事实来源）。
"""

from app.utils.speech_metrics import METRICS_VERSION, compute_voice_metrics


def _seg(seq: int, start: int, end: int, text: str) -> dict:
    return {"seq": seq, "start_ms": start, "end_ms": end, "text": text}


# 正常样例：3 句 / 总时长 16s / 有效语音 10s / 20 字 / 填充词「然后」「就是」各 1
# 停顿：句1→句2 间隔 2000ms（LOW）、句2→句3 间隔 4000ms（HIGH）
NORMAL = [
    _seg(1, 0, 3000, "第一句话测试"),          # 6 字
    _seg(2, 5000, 9000, "然后第二句话就是测试"),  # 10 字
    _seg(3, 13000, 16000, "第三句话"),          # 4 字
]


def test_none_segments_is_text_only():
    """纯文字作答：仅 version + quality=TEXT_ONLY，不带任何基础量。"""
    result = compute_voice_metrics(None)
    assert result == {"version": METRICS_VERSION, "quality": "TEXT_ONLY"}


def test_empty_segments_is_too_short_with_base_metrics():
    """空数组：TOO_SHORT + 基础量全零。"""
    result = compute_voice_metrics([])
    assert result["quality"] == "TOO_SHORT"
    assert result["version"] == METRICS_VERSION
    assert result["total_ms"] == 0
    assert result["speech_ms"] == 0
    assert result["silence_ms"] == 0
    assert result["char_count"] == 0
    assert "speech_rate" not in result  # 不产出表达维度


def test_silent_segments_is_too_short():
    """全静音（有片段但文本去空白后为空）：字数 0 → TOO_SHORT，不进引擎。"""
    result = compute_voice_metrics([_seg(1, 0, 6000, "  "), _seg(2, 7000, 12000, "")])
    assert result["quality"] == "TOO_SHORT"
    assert result["char_count"] == 0
    assert result["total_ms"] == 12000
    assert "pauses" not in result


def test_under_ten_seconds_is_too_short():
    """总时长不足 10 秒 → TOO_SHORT（边界：9999 不足、10000 达标）。"""
    short = compute_voice_metrics([_seg(1, 0, 9999, "这一句其实说得挺好的呀")])
    assert short["quality"] == "TOO_SHORT"
    assert short["total_ms"] == 9999
    assert "speech_rate" not in short

    boundary = compute_voice_metrics([_seg(1, 0, 10000, "这一句其实说得挺好的呀")])
    assert boundary["quality"] == "OK"


def test_normal_sample_five_metrics_match_manual_constants():
    """正常样例：五项指标与基础量逐项与手算一致。"""
    result = compute_voice_metrics(NORMAL)

    assert result["version"] == METRICS_VERSION
    assert result["quality"] == "OK"
    # 基础量
    assert result["total_ms"] == 16000
    assert result["speech_ms"] == 10000
    assert result["silence_ms"] == 6000
    assert result["char_count"] == 20
    # ① 语速：20 字 ÷ (10000ms / 60000) = 120 字/分
    assert result["speech_rate"] == 120
    # ② 有效时长占比：10000 / 16000 = 0.625 → 0.62（两位小数）
    assert result["speech_ratio"] == 0.62
    # ③ 填充词：五键全量返回、计数与密度
    assert result["filler_detail"] == {"嗯": 0, "呃": 0, "那个": 0, "就是": 1, "然后": 1}
    assert result["filler_count"] == 2
    assert result["filler_rate"] == 0.1
    # ④ 停顿点：>1.5s 起计、context 取前句末尾 10 字、level 分档
    assert result["pauses"] == [
        {"after_seq": 1, "duration_ms": 2000, "context": "第一句话测试", "level": "LOW"},
        {"after_seq": 2, "duration_ms": 4000, "context": "然后第二句话就是测试", "level": "HIGH"},
    ]
    assert result["longest_pause_ms"] == 4000
    # ⑤ 流畅度趋势：三段语速 120 / 150 / 80，首→末 −33% → DECLINING
    assert result["fluency_trend"]["direction"] == "DECLINING"
    assert result["fluency_trend"]["segments"] == [
        {"seg": 1, "speech_rate": 120, "filler_count": 0},
        {"seg": 2, "speech_rate": 150, "filler_count": 2},
        {"seg": 3, "speech_rate": 80, "filler_count": 0},
    ]


def test_pause_context_truncates_to_last_ten_chars():
    """停顿 context 取前句**末尾 10 字**——长句只保留尾部。"""
    long_text = "一二三四五六七八九十甲乙丙丁戊"  # 15 字去空白
    result = compute_voice_metrics([_seg(1, 0, 4000, long_text), _seg(2, 8000, 12000, "收尾一句")])
    assert result["quality"] == "OK"
    assert result["pauses"][0]["context"] == "六七八九十甲乙丙丁戊"  # 末 10 字


def test_pause_levels_three_tiers():
    """停顿分档：LOW ≤3s / HIGH ≤5s / SEVERE >5s（边界给足）。"""
    segments = [
        _seg(1, 0, 2000, "第一句话"),
        _seg(2, 5000, 8000, "第二句话"),    # gap 3000 → LOW（边界）
        _seg(3, 13000, 16000, "第三句话"),  # gap 5000 → HIGH（边界）
        _seg(4, 22000, 26000, "第四句话"),  # gap 6000 → SEVERE
    ]
    result = compute_voice_metrics(segments)
    assert [p["level"] for p in result["pauses"]] == ["LOW", "HIGH", "SEVERE"]


def test_single_segment_trend_is_stable():
    """单句：段数不足 2 → 趋势恒 STABLE（无可比较的两段）。"""
    result = compute_voice_metrics([_seg(1, 0, 12000, "只说了这么一句完整的话")])
    assert result["quality"] == "OK"
    assert result["fluency_trend"]["direction"] == "STABLE"
    assert len(result["fluency_trend"]["segments"]) == 1


def test_whitespace_not_counted_in_chars_or_fillers():
    """空白不计入字数与填充词（口径：去空白后计数）。"""
    result = compute_voice_metrics([_seg(1, 0, 12000, "然后  就是 测试 一下 空白 计数")])
    assert result["quality"] == "OK"
    assert result["char_count"] == 12  # 「然后就是测试一下空白计数」（12 字）
    assert result["filler_count"] == 2
