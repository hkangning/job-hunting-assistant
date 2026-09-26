"""全部场景 prompt 模板（系统设计 5.3）：集中管理便于调优。

统一约束（各场景 system prompt 均含）：角色设定一句 / 输出格式要求（序号标题分隔，便于前端分段渲染）/
长度约束（控制 token 与首字延迟）/ 禁止 markdown 表格（打字机渲染体验差，改用列表）。

各业务链路自步骤 12 起陆续加入：JD 分析（本步）→ 陪练点评 → 模拟面试 → 面经结构化 → Agent → 提醒文案。
"""

from app.models import UserProfile

# JD 分析五段结构与对应 section（接口文档 3.6）：关键词命中即判定该段，与下方模板的标题文案一一对应
JD_ANALYSIS_SECTION_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("综合匹配度", "匹配度评分"), "match_score"),
    (("分项",), "scores"),
    (("优势",), "strengths"),
    (("差距", "不足"), "gaps"),
    (("建议",), "advice"),
)

JD_ANALYSIS_SYSTEM = """你是资深技术招聘顾问，负责帮求职者评估岗位匹配度。

【求职者画像】
{profile}

【输出格式】
严格按下面五段输出，标题行**原样照抄**（保留 `## ` 与序号，不改写、不增删段落、不写开场白与结束语）：

## 1. 综合匹配度评分
第一行给出「综合匹配度：XX 分」（XX 为 0~100 的整数），随后用 1~2 句说明总体判断。

## 2. 分项评分
逐项给出三项评分，每项 0~100 分并各附一句理由：技能匹配 / 经验匹配 / 学历与硬性门槛。

## 3. 优势清单
3~5 条，每条对应画像中的具体经历、技能或背景。

## 4. 差距清单
3~5 条 JD 要求但画像缺失或不足的点，每条给出补齐建议。

## 5. 投递与准备建议
3~5 条：简历怎么改、面试重点准备什么。

【约束】
- 全文 600~1000 字；
- 禁止使用 markdown 表格，列表统一用「- 」开头；
- 只输出报告本身，不要任何前后缀说明。"""

# 画像摘要字段与中文标签（顺序即输出顺序）
_PROFILE_LABELS: tuple[tuple[str, str], ...] = (
    ("name", "姓名"),
    ("school", "学校"),
    ("major", "专业"),
    ("degree", "学历"),
    ("gpa", "GPA"),
    ("english_level", "英语水平"),
    ("target_position", "目标岗位"),
    ("target_city", "目标城市"),
    ("skills", "技能栈"),
    ("weaknesses", "自述短板"),
)

# 简历全文截断上限（字符）：画像注入控制在 500 token 口径（系统设计 5.3），防超长简历拖慢首字
RESUME_LIMIT = 2000


def build_profile_digest(profile: UserProfile | None) -> str:
    """把画像压成结构化摘要文本（FR-006：JD 分析注入画像摘要，控制 token）。"""
    lines = [
        f"{label}：{value}" for field, label in _PROFILE_LABELS if (value := getattr(profile, field, None))
    ]
    resume = (profile.resume_text or "").strip() if profile is not None else ""
    if resume:
        lines.append(f"简历全文：\n{resume[:RESUME_LIMIT]}")
    if not lines:
        return "（求职者尚未填写画像；请基于 JD 本身给出通用分析，并提示其补充画像可提升准确度。）"
    return "\n".join(lines)


def build_jd_analysis_messages(profile: UserProfile | None, jd_text: str) -> list[dict]:
    """组装 JD 分析对话：画像摘要（system）+ JD 原文（user），强制五段结构（FR-006）。"""
    system = JD_ANALYSIS_SYSTEM.format(profile=build_profile_digest(profile))
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"【JD 原文】\n{jd_text}"},
    ]
