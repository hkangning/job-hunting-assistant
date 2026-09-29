"""训练相关的纯函数层（系统设计 §5.10）：轮次状态机 + 选择题规则判定。

状态机：给定「模式 + 已发生的轮次 + 本轮结果」，输出下一步动作，由服务层负责执行。
把"该不该继续追"从 LLM 手里拿回来，避免硬凑层数。

判定：把选择题的选项标识（如 `"B"`）展开为选项文本，与正确答案归一化后精确比对、不调
LLM（零 token）。陪练作答与错题复习共用同一套比对，不各写一套。
"""

import json
import re
from dataclasses import dataclass

from app.models.enums import AttackFace, PracticeMode

MAX_LAYERS = 4  # 追问链最大层数
ATTACK_FACE_ORDER = (AttackFace.BASIS, AttackFace.BOUNDARY, AttackFace.TRADEOFF, AttackFace.LANDING)
DEBUG_MAX_MATERIALS = 2  # 挑错模式最多给几轮材料
FEYNMAN_MAX_FOLLOW_UPS = 2  # 费曼模式最多追问几轮

STUCK_MAX_LEN = 30  # 只有这么短的作答才可能是在认输，长作答里出现同款措辞多半是展开论述
STUCK_PHRASES = (
    "不知道",
    "不会",
    "不懂",
    "不清楚",
    "不了解",
    "没了解",
    "没做过",
    "没接触过",
    "没学过",
    "想不起来",
    "记不清",
    "答不上",
    "没思路",
)


def is_stuck(text: str | None) -> bool:
    """作答是否属于「答不上来」——字符串匹配，不调 LLM（系统设计 §5.10）。

    驱动两件事：追问链的终止判定，以及结算时的断点识别（`break_face`）。
    长作答里出现「不清楚」往往是在展开（「这块我不清楚，但我知道 X」），故只认短作答。
    """
    content = (text or "").strip()
    if not content:
        return True
    if len(content) > STUCK_MAX_LEN:
        return False
    return any(phrase in content for phrase in STUCK_PHRASES)


@dataclass(frozen=True)
class TurnDecision:
    """下一步动作：`action` 取值 `FOLLOW_UP` / `HINT` / `SETTLE`。"""

    action: str
    layer: int | None = None  # 追问层号（1~4），仅 FOLLOW_UP 有值
    face: AttackFace | None = None  # 该层攻击面，仅 FOLLOW_UP 有值
    reason: str = ""  # 判定理由（写日志用）


def next_turn(
    *,
    mode: PracticeMode,
    round_index: int,  # 已完成的总轮数（含初始作答）
    follow_up_count: int,  # 已发生的追问轮数
    last_result: str,  # `OK` | `STUCK`（答不上来）| `HINT_USED`（提示后仍答不出）
    exhausted: bool = False,  # 模型判定「已挖到底」
) -> TurnDecision:
    """按模式分派下一步。`round_index` 从 1 起算（1 = 初始作答已完成）。"""
    if mode is PracticeMode.QUICK:
        return TurnDecision("SETTLE", reason="快练无追问")

    if mode in (PracticeMode.INTERVIEWER, PracticeMode.COACH):
        if last_result == "STUCK" and mode is PracticeMode.COACH:
            return TurnDecision("HINT", reason="教练模式：答不上先给提示")
        if follow_up_count >= MAX_LAYERS or exhausted:
            return TurnDecision("SETTLE", reason="追满或已挖到底")
        layer = follow_up_count + 1
        return TurnDecision("FOLLOW_UP", layer=layer, face=ATTACK_FACE_ORDER[layer - 1])

    if mode is PracticeMode.DEBUG:
        # 一轮材料 + 一轮找错各占一轮，第 N 轮材料的找错轮轮号为 2N：给满 2 轮材料后收尾
        if last_result == "STUCK" or round_index >= DEBUG_MAX_MATERIALS * 2:
            return TurnDecision("SETTLE", reason="找错结束")
        return TurnDecision("FOLLOW_UP", reason="再来一轮材料")

    if mode is PracticeMode.FEYNMAN:
        if last_result == "STUCK" or follow_up_count >= FEYNMAN_MAX_FOLLOW_UPS:
            return TurnDecision("SETTLE", reason="复述追问结束")
        return TurnDecision("FOLLOW_UP", reason="针对讲错或含糊处追问")

    return TurnDecision("SETTLE", reason="未知模式按结算处理")


def is_break(last_result: str) -> bool:
    """本轮是否记为断点（面试官模式答不上；教练模式提示后仍答不出）。"""
    return last_result in ("STUCK", "HINT_USED")


def judge_passed(
    *,
    mode: PracticeMode,
    overall_score: int | None,
    break_count: int,
    hit_rate: float | None = None,
    leak_count: int | None = None,
) -> bool:
    """各模式的通过判据（系统设计 §5.10）。"""
    if mode is PracticeMode.QUICK:
        return (overall_score or 0) >= 6
    if mode in (PracticeMode.INTERVIEWER, PracticeMode.COACH):
        return (overall_score or 0) >= 6 and break_count < 2
    if mode is PracticeMode.DEBUG:
        return (hit_rate or 0.0) >= 0.6
    if mode is PracticeMode.FEYNMAN:
        return (leak_count if leak_count is not None else 99) < 3
    return False


# ---- 客观题规则判定（陪练作答与错题复习共用）----

_PUNCT_RE = re.compile(r"[\s，。、；：？！,.;:?!（）()\[\]【】\"'“”‘’]+")


def normalize_text(text: str) -> str:
    """归一化：去空白与标点、转小写——两侧同口径之后才能比对。"""
    return _PUNCT_RE.sub("", text).lower()


def parse_options(raw: str | None) -> list[dict]:
    """把库里的 `options`（JSON 字符串）解析为选项数组；空值或串损坏一律当没有选项。"""
    if not raw:
        return []
    try:
        options = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return options if isinstance(options, list) else []


def expand_choice_input(user_input: str, options: list[dict] | None) -> str:
    """把选择题的选项标识（如 `"B"`）展开为选项文本；展开不到则原样返回。

    先按标识匹配（忽略大小写与首尾空白）；匹配不到时再容错比一次选项文本本身——
    前端若误传了文本、或旧版前端仍按开放作答提交，也能正常判定而非一律判错。
    """
    raw = (user_input or "").strip()
    groups = options or []
    if not raw or not groups:
        return raw
    for item in groups:
        key = str(item.get("key", "")).strip()
        if key and raw.upper() == key.upper():
            return str(item.get("text", ""))
    got = normalize_text(raw)
    for item in groups:
        text = str(item.get("text", ""))
        if got and normalize_text(text) == got:
            return text
    return raw


def judge_choice(answer: str, user_input: str, options: list[dict] | None = None) -> bool:
    """选择题规则比对：两侧都展开为选项文本后归一化**精确相等**（不调 LLM）。

    两侧同口径展开——首轮的正确答案来自题库、是文本，追问轮的正确项由模型给出（如 `"B"`）是
    标识，不做展开就会拿标识去比选项文本、必然判错。

    不用包含匹配——单字符的选项标识会被 `"AB"` 这类组合误判。
    """
    expected = normalize_text(expand_choice_input(answer, options))
    got = normalize_text(expand_choice_input(user_input, options))
    return bool(expected) and expected == got
