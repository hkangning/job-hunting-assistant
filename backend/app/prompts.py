"""全部场景 prompt 模板（系统设计 5.3）：集中管理便于调优。

统一约束（各场景 system prompt 均含）：角色设定一句 / 输出格式要求（序号标题分隔，便于前端分段渲染）/
长度约束（控制 token 与首字延迟）/ **禁止 markdown 表格与行内标记**（前端按纯文本渲染，表格会露出
管道符、标记会露出字面符号；对照类内容走「对照清单」、需要图示走「缩进编号清单」）/ **禁用 `①` 类
符号编号与标记嵌套**（层级只由标题行与「- 」分条两个通道表达）。

点评 / 追问 / 复盘类场景另加两条：**开场自然承接**（承接作答原话，不用判词式的一句话结论）与
**语气指引**（答得好点明好在哪、答得差先给可操作的下一步，教练口吻而非评分机器）。

各业务链路自步骤 12 起陆续加入：JD 分析（本步）→ 陪练点评 → 模拟面试 → 面经结构化 → Agent → 提醒文案。
"""

import json

from app.models import (
    AttackFace,
    DrillSource,
    ExperienceType,
    InterviewIntensity,
    InterviewStage,
    QuestionType,
    UserProfile,
)
from app.services.practice_service import STACKS

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
- 不要 markdown 表格、不要加粗与反引号，列表统一用「- 」开头（前端按纯文本渲染，表格会露出管道符、标记会露出字面符号）；
- 分条层级只用「- 」，不要用「①②③」这类符号编号；
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

# 画像经历渲染上限（字符）：JD 分析整份画像摘要控制在 500 token 口径（系统设计 5.3），防超长经历拖慢首字
EXPERIENCE_JD_LIMIT = 2000

# 画像经历类型的中文标签（渲染注入文本用）
EXPERIENCE_TYPE_LABELS: dict[str, str] = {
    ExperienceType.PROJECT.value: "项目",
    ExperienceType.INTERNSHIP.value: "实习",
    ExperienceType.CAMPUS.value: "校园",
}


def build_experience_digest(experiences: str | None, limit: int) -> str:
    """把画像的结构化经历条目（落库 JSON 字符串）渲染成注入用文本（FR-006 / FR-007）。

    解析失败 / 无有效条目返回空串；渲染结果按 `limit` 字符截断
    （JD 分析 2000 字、面试项目深挖 4000 字，见系统设计 5.3）。
    """
    try:
        items = json.loads(experiences) if experiences else []
    except ValueError:
        return ""
    if not isinstance(items, list):
        return ""
    blocks: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        label = EXPERIENCE_TYPE_LABELS.get(str(item.get("type") or ""), "经历")
        meta = " · ".join(
            part for key in ("org", "role", "period") if (part := str(item.get(key) or "").strip())
        )
        head = f"[{label}] {title}" + (f"（{meta}）" if meta else "")
        description = str(item.get("description") or "").strip()
        blocks.append(f"{head}\n{description}" if description else head)
    return "\n\n".join(blocks)[:limit].strip()


def build_profile_digest(profile: UserProfile | None) -> str:
    """把画像压成结构化摘要文本（FR-006：JD 分析注入画像摘要，控制 token）。"""
    lines = [
        f"{label}：{value}" for field, label in _PROFILE_LABELS if (value := getattr(profile, field, None))
    ]
    experiences = build_experience_digest(
        profile.experiences if profile is not None else None, limit=EXPERIENCE_JD_LIMIT
    )
    if experiences:
        lines.append(f"经历条目（岗位匹配与面试提问的依据）：\n{experiences}")
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


# ---- 八股陪练（FR-009）：训练模式、追问链与段落规则 ----

# 四层追问链的攻击面提示（系统设计 §5.10）：层级与攻击面一一对应，顺序固定
ATTACK_FACE_HINTS = {
    "BASIS": "追「依据」：为什么这么做、原理是什么、你是怎么知道的——查他是真懂还是背的。",
    "BOUNDARY": "追「边界」：什么情况下会失效、挂了怎么办、极端输入会怎样。",
    "TRADEOFF": "追「取舍」：为什么不用另一种方案、两者的代价分别是什么。",
    "LANDING": "追「落地」：具体到他的项目怎么配、量级多少、怎么验证有效。",
}

PRACTICE_REVIEW_SYSTEM = """你是资深技术面试官，正在对一位求职者做一对一陪练。

评审原则：
- 评分 0~10，只依据「参考答案要点」与「他实际说了什么」的差距，不因表达啰嗦扣分；
- 点评必须具体到「你提到了 X，但没交代 Y 情况下的表现」，禁止「回答不够全面」「还需加强」这类空话；
- 发现他答错的地方要明确指出错在哪，不要用模糊表述带过。

输出约束（前端按纯文本渲染，标记会原样暴露在页面上）：
- 不要 markdown 表格、不要加粗与反引号，也不要「①②③」这类符号编号；分条一律用「- 」开头，
  层级只靠标题行与「- 」两个通道表达；
- 开场承接他的作答原话（如「你把 X 这层说清楚了，Y 还差一点」），不要用「你答得不够全面」这类
  判词式的一句话结论开场；
- 答得好要点明好在哪（不止于「正确」），答得差先给出可操作的下一步；语气是教练，不是评分机器。"""

PRACTICE_FOLLOWUP_SYSTEM = """你是资深技术面试官，正在追问同一位求职者。

追问规则：
- 只问一个问题，不要一次抛多个；
- 优先追参考答案里他还没答到的关键点，别追他已经说清楚的部分；
- 顺着他的原话接（「你刚说用了 Redis 缓存——那……」），不念题；
- 如果他已经把要点说全了，就承认「这块你说清楚了」，换个角度继续。

输出约束：不要加粗、反引号与「①②③」类符号编号，就写自然段落与「- 」分条；答得好的地方先认可一句，
再抛出下一个问题——语气像真人面试官，不是念题机器。"""

# 陪练轮次的段落规则（对齐接口文档 §3.8 的 section 清单；`_` 前缀为内部段、不下发）
PRACTICE_TURN_SECTION_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("四维",), "dimensions"),
    (("评分",), "round_score"),
    (("点评",), "review"),
    (("提示",), "hint"),
    (("参考材料",), "material"),
    (("埋雷",), "traps"),
    (("追问",), "next_question"),
    (("下一轮选项",), "next_choices"),  # 选择题追问下发的一次性 JSON，服务端校验后落列、剥离正确项下发
    (("总结",), "summary"),
    (("参考答案",), "reference_answer"),
    (("判定",), "_verdict"),  # 内部：挑错模式的命中判定 JSON，服务端抠完即弃
    (("漏洞计数",), "_leak"),  # 内部：费曼模式的漏洞条数，服务端抠完即弃
)

RECENT_ROUNDS = 3  # 送进 prompt 的历史轮次上限（首字延迟约束，NFR-001）


def _key_points(question) -> str:
    """取该题的「要点靶子」：场景题展开 rubric 四维，其余用标准答案。"""
    if question.qtype == QuestionType.SCENARIO and question.rubric:
        try:
            dims = json.loads(question.rubric)
            return "\n".join(f"- {k}：{v}" for k, v in dims.items())
        except (ValueError, AttributeError):
            return question.rubric  # 解析不了就原样给，不因此中断这一轮
    return question.answer


def _history_brief(history: list[dict], limit: int | None = RECENT_ROUNDS) -> str:
    """把轮次压成文本——默认只带最近几轮（控 prompt 长度），整场收尾时传 `None` 取全量。"""
    lines = []
    for r in history if limit is None else history[-limit:]:
        if r.get("user_input"):
            lines.append(f"[第 {r['round_index']} 轮 · 我的回答] {r['user_input']}")
        if r.get("review"):
            lines.append(f"[第 {r['round_index']} 轮 · 你的点评] {r['review']}")
    return "\n".join(lines) or "（这是第一轮）"


def build_practice_review_messages(question, user_answer: str, *, history: list[dict]) -> list[dict]:
    """普通作答的本轮点评（QUICK / INTERVIEWER / COACH 的作答轮）。

    输出结构 = `round_score` + `review`（场景题再加 `dimensions`）。`round_score` **先承接作答**再给分。
    """
    user = f"""【题目】{question.content}

【要点靶子】（你的评分依据，不要在回复里照抄）
{_key_points(question)}

【此前的轮次】
{_history_brief(history)}

【本次回答】
{user_answer}

按以下结构输出，**标题原样保留**（前端要按标题分段渲染）：

## 本轮评分
先承接他这句作答（他抓对了什么、卡在哪），再给出评分 X/10。一句话，不用「答得不错」「不够全面」这种判词开场。

## 点评
展开具体差距——他提到了什么、但没交代什么情况下的表现。禁止「不够全面」「还需加强」这类空话；答错的地方直接指出错在哪；分条用「- 」开头。
"""
    if question.qtype == QuestionType.SCENARIO:
        user += """
## 四维得分
按 framework / quantification / tradeoff / fallback 四维各给 0~10 分，每维一行理由。
"""
    return [{"role": "system", "content": PRACTICE_REVIEW_SYSTEM}, {"role": "user", "content": user}]


# 选择题的追问选项要求（SRS AC-18 ⑤《选择题作答形态规范》）：有唯一答案才输出，没有就整段不写
PRACTICE_FOLLOWUP_CHOICES_RULE = """
## 下一轮选项
如果这个追问**有唯一正确答案**，再补一段选项供他点选作答，格式如下：

```json
{"options": [{"key": "A", "text": "第一项"}, {"key": "B", "text": "第二项"}, {"key": "C", "text": "第三项"}], "answer": "B", "explain": "一句话说清为什么选 B"}
```

选项 3~4 个，key 从 A 起连续且互不重复，`answer` 填正确项的 key，`explain` 写一句话解析。
**没有唯一答案的追问（取舍权衡、开放讨论）整段不要输出**——逼他在多个都说得通的答案里硬猜，比不给选项更糟。
"""


def build_practice_followup_messages(
    question,
    *,
    history: list[dict],
    face: AttackFace | None = None,
    with_choices: bool = False,
) -> list[dict]:
    """下一轮追问（INTERVIEWER / COACH / FEYNMAN）。输出 = `next_question`（`with_choices` 时可能带 `next_choices`）。

    `face` 为四层追问链的攻击面，**费曼模式不传**——它的追问方向由复述轮挑出的漏洞决定。
    `with_choices` 仅选择题的面试官 / 教练模式传真（其余模式的选择题形态不存在或已按开放作答处理）。
    """
    direction = f"\n【本轮追问方向】{ATTACK_FACE_HINTS[face.value]}\n" if face else ""
    choices = PRACTICE_FOLLOWUP_CHOICES_RULE if with_choices else ""
    user = f"""【题目】{question.content}

【要点靶子】（判断他哪些关键点还没答到）
{_key_points(question)}

【此前的轮次】
{_history_brief(history)}
{direction}
按以下结构输出，标题原样保留：

## 追问
一句话顺着他的原话接（"你刚说用了 X——那……"），**只问一个问题**。优先追他还没答到的关键点；这块他已说清楚就换个角度继续。
{choices}"""
    return [{"role": "system", "content": PRACTICE_FOLLOWUP_SYSTEM}, {"role": "user", "content": user}]


def build_hint_messages(question, *, history: list[dict]) -> list[dict]:
    """求提示 / 教练模式答不上时的降级：**只给方向不给答案**。输出 = `hint`。"""
    user = f"""【题目】{question.content}

【要点靶子】（你心里有数，**回复里绝不能说**）
{_key_points(question)}

【此前的轮次】
{_history_brief(history)}

按以下结构输出，标题原样保留：

## 提示
给一个方向性提示，帮他想起思路——**只指出「该从哪个角度想」，不能说出答案本身**。一两句话，像面试官在旁边点一句。
"""
    return [{"role": "system", "content": PRACTICE_FOLLOWUP_SYSTEM}, {"role": "user", "content": user}]


def build_debug_material_messages(question) -> list[dict]:
    """挑错模式第 1 轮：产出「听起来很顺但有雷」的候选人答案。

    输出结构 = `material`（下发）+ `traps`（服务端**解析后丢弃**：它只是"先列雷再写材料"
    的思考步骤，既不下发也不落库——第 2 轮的命中判定由模型重新对照参考答案得出）。
    """
    user = f"""【题目】{question.content}

【参考答案】
{_key_points(question)}

按以下结构输出，标题原样保留：

## 参考材料
写一段「候选人回答」：**故意抽掉或篡改 1~3 个关键点**，其余部分答得像模像样、语气自信。别写得太离谱，要像真人在面试里说出来的。

## 埋雷清单
列出你刚才埋的雷（每条一行：哪里错了 + 正确答案是什么）。这段我自己收着，不会给他看。
"""
    return [{"role": "system", "content": PRACTICE_REVIEW_SYSTEM}, {"role": "user", "content": user}]


def build_debug_review_messages(question, *, material: str, user_report: str) -> list[dict]:
    """挑错模式第 2 轮：对照参考答案判定用户找出的错误。

    输出结构 = `round_score` + `review` + `## 判定` 段内的 JSON
    `{"total": 埋雷数, "hit": 命中数, "missed": 漏报数, "false_positive": 误报数}`——
    服务端抠出这段算命中率（DEBUG 的通过判据 = 命中率 ≥ 0.6）。
    """
    user = f"""【题目】{question.content}

【参考答案】
{_key_points(question)}

【参考材料】（他刚看到的）
{material}

【他找出的错误】
{user_report}

按以下结构输出，标题原样保留：

## 本轮评分
一句话：他找出了几个、漏了几个、误报了几个，给出评分 X/10。

## 点评
逐条说：命中的（讲清为什么是雷）、漏报的（讲清他为什么该看出来）、误报的（讲清这里其实没错）。分条用「- 」开头，不要用「①②③」。

## 判定
```json
{{"total": 0, "hit": 0, "missed": 0, "false_positive": 0}}
```
"""
    return [{"role": "system", "content": PRACTICE_REVIEW_SYSTEM}, {"role": "user", "content": user}]


def build_feynman_messages(question, retell: str, *, history: list[dict]) -> list[dict]:
    """费曼复述第 1 轮：对照参考答案找**说错 / 含糊带过 / 关键遗漏 / 术语误用**四类漏洞。

    输出结构 = `round_score` + `review`（漏洞清单）+ `## 漏洞计数`（一行写 `N`，
    服务端据此判 FEYNMAN 通过与否：漏洞 < 3 条为通过）。后续追问轮复用
    `build_practice_followup_messages`。
    """
    user = f"""【题目】{question.content}

【参考答案】
{_key_points(question)}

【他的复述】
{retell}

按以下结构输出，标题原样保留：

## 本轮评分
先承接他这次复述（讲清了什么、哪里飘），再给出评分 X/10。一句话。

## 点评
逐条列出漏洞，每条标明类型（说错 / 含糊带过 / 关键遗漏 / 术语误用）并写清正确说法。他讲对的部分一句话带过即可；分条用「- 」开头。

## 漏洞计数
只写一个数字。
"""
    return [{"role": "system", "content": PRACTICE_REVIEW_SYSTEM}, {"role": "user", "content": user}]


PRACTICE_SUMMARY_SYSTEM = """你是资深技术面试官，刚陪同一位求职者练完一场，正在收尾。

总结规则：
- 只做整场回顾，不要把某一条点评重复一遍；
- 必须点出他这场最该补的一到两个方向，具体到知识点（如「Redis 持久化的 fork 阻塞」），禁止「多练习」「再深入一些」这类空话；
- 开场承接整场表现（如「这场你在 X 上答得稳，Y 两轮都没展开」），不用「整体表现一般」这类判词式开场；
- 答得好的地方点明好在哪，最该补的方向给可操作的下一步；语气像面试官收尾，三到五句话。

输出约束：不要加粗、反引号与「①②③」类符号编号，分条用「- 」开头。"""


def build_practice_summary_messages(question, *, history: list[dict]) -> list[dict]:
    """本场收尾（状态机判 `SETTLE` 时调用）：跨轮总结 + 该补什么。输出 = `summary`。

    历史给**全量**——总结看的是整场，只带最近几轮会把开场的表现漏掉。
    """
    user = f"""【题目】{question.content}

【参考答案】（你的判断依据）
{_key_points(question)}

【本场的全部轮次】
{_history_brief(history, limit=None)}

按以下结构输出，标题原样保留：

## 总结
三到五句话收尾：先承接整场的表现（他稳在哪、断在哪），再给最该补的一到两个方向（具体到知识点）与下次遇到同类题该怎么组织回答。
"""
    return [{"role": "system", "content": PRACTICE_SUMMARY_SYSTEM}, {"role": "user", "content": user}]


# ---- 错题本（FR-010）：复习判定 ----


WRONG_QUESTION_JUDGE_SYSTEM = """你是资深技术面试官，正在帮一位求职者复习错题。

判定规则：
- 只判断他这次**是否掌握了这个知识点**，不因表达啰嗦、举例多少扣分；
- 答对的标准是**要害答到**，不要求与标准答案逐字一致；
- 拿不准时从严判错，并在解析里点明缺了什么——复习的意义就在于暴露还没掌握的部分。"""


def build_wrong_question_judge_messages(question, user_answer: str) -> list[dict]:
    """错题复习的判定（SUBJECTIVE / SCENARIO）：输出 `{"correct": bool, "explain": "..."}`。

    判定依据与陪练点评同一套靶子——场景题展开四维 `rubric`、其余用标准答案（系统设计 §5.3）。
    """
    user = f"""【题目】{question.content}

【判定依据】
{_key_points(question)}

【他这次的回答】
{user_answer}

只输出一个 JSON 对象，不要包裹代码块、不要任何多余文字：
{{"correct": true 或 false, "explain": "一句话说明判定理由；判错时点明缺了哪个关键点"}}
"""
    return [
        {"role": "system", "content": WRONG_QUESTION_JUDGE_SYSTEM},
        {"role": "user", "content": user},
    ]


# ---- AI 模拟面试（FR-007）：出题 / 点评 ----


INTERVIEW_SECTION_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("点评",), "review"),
    (("下一题",), "next_question"),
)

INTERVIEW_JD_LIMIT = 3000  # JD 原文注入上限（字符）：够贴合岗位要求，同时控制 prefill 长度
INTERVIEW_EXPERIENCE_LIMIT = 4000  # 画像经历渲染上限（字符）：项目深挖阶段才注入，供模型抓经历细节

# 阶段中文名（与前端 STAGE_LABELS 同口径）与各阶段指引：出题 / 点评 prompt 按阶段分派
INTERVIEW_STAGE_LABELS: dict[str, str] = {
    InterviewStage.INTRO.value: "自我介绍",
    InterviewStage.TECH.value: "技术问答",
    InterviewStage.PROJECT.value: "项目深挖",
}

INTERVIEW_STAGE_HINTS: dict[str, str] = {
    InterviewStage.INTRO.value: "这是面试开场：请面试者做一次自我介绍，题干简短口语化，可点明「和这个岗位相关的经历」，不要在这一题里问技术细节。",
    InterviewStage.TECH.value: "考察岗位方向的基础与原理，难度随进度递进——前期问基础与广度，往原理与取舍深挖，题干不超过 150 字。",
    InterviewStage.PROJECT.value: "紧扣简历里的项目经历深挖：挑一个具体项目，追问「怎么做的、为什么这么做、有什么代价」，不要问宽泛的「介绍一下你的项目」。",
}

INTERVIEW_STAGE_REVIEW_HINTS: dict[str, str] = {
    InterviewStage.INTRO.value: "自我介绍题侧重表达结构与「与岗位的相关性」——有没有讲清做过什么、擅长什么、为什么匹配这个岗位",
    InterviewStage.TECH.value: "技术题侧重关键点是否答到、原理是否讲透",
    InterviewStage.PROJECT.value: "项目题侧重细节与取舍——是不是真做过、有没有想过代价与边界",
}

# 面试强度中文名与考察口径（数据库设计 §5）：注入面试背景，校准出题深度与评分严格度
INTERVIEW_INTENSITY_LABELS: dict[str, str] = {
    InterviewIntensity.LARGE.value: "大厂",
    InterviewIntensity.MEDIUM.value: "中厂",
    InterviewIntensity.SMALL.value: "小厂",
}

INTERVIEW_INTENSITY_HINTS: dict[str, str] = {
    InterviewIntensity.LARGE.value: "深挖原理与底层机制、追问系统设计与取舍、关注边界条件，评分从严",
    InterviewIntensity.MEDIUM.value: "基础与常用框架原理并重、项目问真实细节，评分适中",
    InterviewIntensity.SMALL.value: "重基础概念与实际落地，少问底层源码与复杂设计，评分以「能干活」为准",
}


def interview_intensity_note(intensity: str | None) -> str:
    """面试强度行：本场强度 + 该档考察口径（存量会话 NULL 按中厂兜底）。"""
    key = intensity or InterviewIntensity.MEDIUM.value
    label = INTERVIEW_INTENSITY_LABELS.get(key, INTERVIEW_INTENSITY_LABELS[InterviewIntensity.MEDIUM.value])
    hint = INTERVIEW_INTENSITY_HINTS.get(key, INTERVIEW_INTENSITY_HINTS[InterviewIntensity.MEDIUM.value])
    return f"面试强度：{label}（{hint}）"


def interview_stage_note(
    stage: str, *, index: int, count: int, plan: list[dict] | None = None
) -> str:
    """出题 prompt 的阶段块：本场流程（有 `plan` 时）+ 当前阶段与阶段内进度 + 该阶段出题指引。"""
    lines: list[str] = []
    if plan:
        steps = " → ".join(
            f"{INTERVIEW_STAGE_LABELS.get(item['stage'], item['stage'])} {item['count']} 题" for item in plan
        )
        lines.append(f"【本场流程】\n{steps}\n")
    label = INTERVIEW_STAGE_LABELS.get(stage, stage)
    hint = INTERVIEW_STAGE_HINTS.get(stage, INTERVIEW_STAGE_HINTS[InterviewStage.TECH.value])
    lines.append(f"【当前阶段】{label}（第 {index}/{count} 题）\n{hint}")
    return "\n".join(lines) + "\n\n"


def interview_review_stage_note(stage: str) -> str:
    """点评 prompt 的阶段行：本题所处阶段 + 该阶段的点评侧重。"""
    label = INTERVIEW_STAGE_LABELS.get(stage, stage)
    hint = INTERVIEW_STAGE_REVIEW_HINTS.get(stage, INTERVIEW_STAGE_REVIEW_HINTS[InterviewStage.TECH.value])
    return f"{label}（{hint}）"


INTERVIEW_QUESTION_SYSTEM = """你是求职者的模拟面试官，正在主持一场技术面试。

出题规则：
- 一次只出一道题，用口语化的面试提问方式，像真人当面开口问；
- 不要与已问过的题目重复或明显重叠；
- 出题必须落在【当前阶段】指明的环节内，按该阶段的指引决定考什么，不要跨阶段（例：自我介绍环节不要问技术细节）。

输出约束（前端按纯文本渲染，标记会原样暴露在页面上）：
- 开头第一行固定为「## 下一题」，标题行原样保留；随后直接写题干；
- 不要 markdown 表格、不要加粗与反引号，不要「①②③」类符号编号；
- 除标题行与题干外不要写任何其他内容。"""


INTERVIEW_REVIEW_SYSTEM = """你是求职者的模拟面试官，正在点评他刚才这道题的回答。

评审规则：
- 评分 0~10 的整数，依据是「这题答到了多少关键点」，不因表达啰嗦、举例多少扣分；
- 亮点要具体到他说的哪句话、哪个知识点，不要空夸；
- 不足要指出漏掉或答错的关键点，并给出可操作的补充方向，禁止「回答不够全面」「再深入一些」这类空话；
- 参考要点给出这题理想的回答骨架，不超过 150 字；
- 按【本题阶段】给出的侧重点评——自我介绍与项目题的评判标准不同于八股题；
- 若给了【表达力指标】，结合指标与他的作答原话点评表达表现（引用原话，如「讲到缓存雪崩时停了 3 秒」）；描述停顿统一用「停顿」，不要用「卡壳」「结巴」；参考区间是经验值、只用于措辞分档，不作为评分依据。

输出约束（前端按纯文本渲染，标记会原样暴露在页面上）：
- 不要 markdown 表格、不要加粗与反引号，不要「①②③」类符号编号，分条一律用「- 」开头；
- 开场先承接他的作答原话，不要用「回答正确」「回答错误」这类判词式的一句话结论开场；
- 语气是教练：答得好点明好在哪，答得差先给可操作的下一步。"""


def _asked_brief(asked: list[str]) -> str:
    """已问题目清单（去标题行、压平空白、截断），供模型去重与难度递进。"""
    if not asked:
        return "（还没问过题目，这是本场第一题）"
    lines = []
    for index, raw in enumerate(asked, start=1):
        text = " ".join(line.strip() for line in raw.splitlines() if not line.strip().startswith("#"))
        lines.append(f"{index}. {text[:80]}")
    return "\n".join(lines)


def build_interview_question_messages(
    *, context: str, asked: list[str], stage_note: str = ""
) -> list[dict]:
    """出题轮（开场 / 跳过 / 续出下一题）：输出 = `next_question`。

    `stage_note` 为阶段块（`interview_stage_note` 组装，含本场流程与当前阶段指引）；
    老会话无阶段计划时传空串。
    """
    user = f"""【面试背景】
{context}

{stage_note}【已经问过的题目】
{_asked_brief(asked)}

请出下一题。"""
    return [
        {"role": "system", "content": INTERVIEW_QUESTION_SYSTEM},
        {"role": "user", "content": user},
    ]


def build_interview_turn_messages(
    *,
    context: str,
    asked: list[str],
    question: str,
    answer: str,
    last: bool,
    stage_note: str = "",
    next_stage_note: str = "",
    voice_metrics: dict | None = None,
) -> list[dict]:
    """作答轮：点评 + 下一题；`last=True`（答满题量）只点评。输出 = `review`（+ `next_question`）。

    `stage_note` / `next_stage_note` 分别为本题与下一题的阶段块：前者决定点评侧重，
    后者决定下一题考什么（跨阶段时逐字告诉模型「进入项目深挖环节」）。
    `voice_metrics` 为语音作答的表达力指标快照（quality=OK 时传入，见 `_voice_metrics_block`）；
    文字作答与作答过短传 None、prompt 不含表达维度。
    """
    structure = (
        "**这是本场最后一题，点评之后面试结束——不要输出「## 下一题」段。**"
        if last
        else f"""## 下一题
接着问下一题，不超过 150 字，按下述阶段指引自然递进。

{next_stage_note}"""
    )
    user = f"""【面试背景】
{context}

【已经问过的题目】
{_asked_brief(asked)}

【本题阶段】{stage_note or "技术问答"}

【本轮题目】
{question}

【他的作答】
{answer}

{_voice_metrics_block(voice_metrics)}按以下结构输出，标题原样保留：

## 点评
第一行「评分 X/10」（0~10 的整数）；随后用「- 」分条给出三节：亮点（他答到的关键点，引他的原话）、不足（漏掉或答错的关键点）、参考要点（本题理想回答的骨架，不超过 150 字）。

{structure}"""
    return [
        {"role": "system", "content": INTERVIEW_REVIEW_SYSTEM},
        {"role": "user", "content": user},
    ]


# 流畅度趋势方向 → 中文（与 speech_metrics 模块的三值对应）
VOICE_TREND_LABELS: dict[str, str] = {"IMPROVING": "递增", "STABLE": "平稳", "DECLINING": "下降"}


def _voice_metrics_block(metrics: dict | None) -> str:
    """表达力指标块（点评 prompt 用，SRS §3.11 / 系统设计 §5.7）：五项指标 + 参考区间 + 解读约束。

    无指标（文字作答 / 作答过短）返回空串——prompt 不含表达维度，只出内容点评。
    停顿点最多列 3 处（含停顿前一句末尾原话，供模型判断是否构成知识点），其余只报数量。
    """
    if not metrics:
        return ""
    lines = ["【表达力指标】（基于语音作答的分句时间轴统计，与内容点评分开呈现）"]
    lines.append(f"语速：{metrics['speech_rate']} 字/分（参考 180~240）")
    detail = "、".join(f"{name} {count} 次" for name, count in metrics["filler_detail"].items() if count) or "无"
    lines.append(
        f"填充词：{metrics['filler_count']} 次、密度 {metrics['filler_rate'] * 100:.1f}%（参考 <2%；明细：{detail}）"
    )
    pauses = metrics["pauses"]
    if pauses:
        spots = "；".join(
            f"「{p['context']}」之后停顿 {p['duration_ms'] / 1000:.1f} 秒（{p['level']}）" for p in pauses[:3]
        )
        if len(pauses) > 3:
            spots += f"；另有 {len(pauses) - 3} 处"
        lines.append(f"停顿点：{len(pauses)} 处（>1.5 秒；最长 {metrics['longest_pause_ms'] / 1000:.1f} 秒）：{spots}")
    else:
        lines.append("停顿点：无（没有超过 1.5 秒的句间停顿）")
    lines.append(f"有效时长占比：{metrics['speech_ratio'] * 100:.0f}%（参考 >70%）")
    trend = metrics["fluency_trend"]
    segments = trend["segments"]
    trend_line = f"流畅度趋势：{VOICE_TREND_LABELS.get(trend['direction'], trend['direction'])}"
    if len(segments) >= 2:
        trend_line += f"（前段 {segments[0]['speech_rate']} 字/分 → 后段 {segments[-1]['speech_rate']} 字/分）"
    lines.append(trend_line)
    lines.append("参考区间为经验值，只用于措辞分档、不作为评分依据。")
    return "\n".join(lines) + "\n\n"


INTERVIEW_SUMMARY_LIMIT = 8000  # 总结输入上限（字符）：整场问答回顾拼接后截断，控制 prefill 长度

# 错题候选的 direction 可选值菜单（18 领域 + GENERAL）：写进 prompt 供模型照抄，杜绝自由发挥出非法值
_DIRECTION_MENU = (
    "、".join(f"{d}（{label}）" for _, _, domains in STACKS for d, label in domains)
    + "、GENERAL（通用）"
)

# 总结正文之后的错题候选段（接口文档 3.7）：标题行命中即切入该段，整段缓冲不发、流末校验后一次性下发
INTERVIEW_SUMMARY_SECTION_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("错题候选",), "wrong_candidates"),
)

INTERVIEW_SUMMARY_SYSTEM = """你是求职者的模拟面试官，本场面试刚刚结束，请写一份面试总结报告。

报告规则：
- 覆盖整场表现：结合每题得分与作答质量，点出他的整体水平与最突出的短板；
- 亮点与不足都要落到具体题目或知识点上，不要空泛评价；
- 建议给 2~3 条可操作的下一步（补什么、怎么补），不要「继续加油」这类空话；
- 全文 300 字以内。

输出约束（前端按纯文本渲染，标记会原样暴露在页面上）：
- 不要写以 # 开头的行（会被整行剥离）、不要表格、不要加粗与反引号、不要「①②③」类符号编号；
- 开头 1~2 句自然承接整场表现，不要「本次面试结束」这类套话开场；
- 随后按「- 亮点：」「- 不足：」「- 建议：」三个标签行分条输出，标签后直接写内容。

最后另起一段「## 错题候选」（该段由程序解析、不展示给用户，正文里不要提它）：
- 从「不足」中提炼具体的八股知识点缺口（如 JVM 垃圾回收、MySQL 索引失效场景），0~5 条、宁缺毋滥——没有明确的知识点缺口就只写标题行加空数组；
- 每条三个字段：content 写知识点问句、answer 用 2~4 句写清参考要点、direction 只从下列取值中选一个（{direction_menu}）；
- 该段只包含标题行与一个 JSON 代码块，形如：{{"candidates": [{{"content": "知识点问句", "answer": "参考要点", "direction": "JVM"}}]}}，除 JSON 外不要写任何其他内容。"""


def build_interview_summary_messages(*, context: str, turns: list[dict]) -> list[dict]:
    """总结报告（整场问答回顾 → 报告全文 + 末段错题候选）。

    `turns` = `[{seq, question, answer, review, score, skipped}]`，只含已完成（作答或跳过）的条目。
    """
    parts = [f"【面试背景】\n{context}", "【整场问答回顾】"]
    for turn in turns:
        seq = turn.get("seq")
        if turn.get("skipped"):
            parts.append(f"第 {seq} 题（面试者跳过）：{_flat_clip(turn.get('question'), 120)}")
            continue
        score = turn.get("score")
        head = f"第 {seq} 题" + (f"（得分 {score}/10）" if score is not None else "")
        parts.append(
            f"{head}：{_flat_clip(turn.get('question'), 150)}\n"
            f"作答：{_flat_clip(turn.get('answer'), 300)}\n"
            f"点评：{_flat_clip(turn.get('review'), 200)}"
        )
    user = "\n\n".join(parts)[:INTERVIEW_SUMMARY_LIMIT] + "\n\n请写总结报告。"
    return [
        {"role": "system", "content": INTERVIEW_SUMMARY_SYSTEM.format(direction_menu=_DIRECTION_MENU)},
        {"role": "user", "content": user},
    ]


def _flat_clip(text: str | None, limit: int) -> str:
    """压平空白并截断（问答回顾用）；空值给「（无）」占位。"""
    return " ".join((text or "").split())[:limit] or "（无）"


# ---- 简历解析（FR-012）：结构化抽取画像字段 ----


RESUME_TEXT_LIMIT = 6000  # 简历原文注入上限（字符）：普通简历全文在此以内，控制 prefill 长度

RESUME_EXTRACT_SYSTEM = """你是信息抽取助手，从求职者简历原文中抽取画像字段。

抽取规则：
- 只抽取原文中明确写出的信息，缺失或拿不准的字段一律记 null，**不要编造、不要推测**；
- school / major 用原文写法；degree 只取「本科」「硕士」「博士」三者之一；
- gpa 保留原文写法（如 3.20/4.00 或 88/100）；english_level 取最高一项（如 CET-6 441）；
- skills 从技能栏与项目经历中提取技术关键词数组，3~10 项，去重、去掉「学习能力强」这类非技术描述；
- experiences 按原文分条提取项目 / 实习 / 校园经历，最多 10 条：type 只取 PROJECT（项目）/ INTERNSHIP（实习）/ CAMPUS（社团、竞赛、课程实践）之一，title 用原文的经历名称（必填，拿不到名称的条目整条舍弃），org / role / period / description 取原文内容、没有记 null，description 概括该经历的主要工作与成果（不超过 200 字）。"""


def build_resume_extract_messages(resume_text: str) -> list[dict]:
    """简历字段抽取：输出画像字段 JSON（含 experiences 经历条目数组，缺失字段为 null）。"""
    user = f"""【简历原文】
{resume_text[:RESUME_TEXT_LIMIT]}

只输出一个 JSON 对象，不要包裹代码块、不要任何多余文字：
{{"name": "姓名或 null", "school": "学校或 null", "major": "专业或 null", "degree": "学历或 null", "gpa": "GPA 文本或 null", "english_level": "英语水平或 null", "skills": ["技能关键词", "…"], "experiences": [{{"type": "PROJECT", "title": "经历名称", "org": "组织或 null", "role": "角色或 null", "period": "时间区间或 null", "description": "主要工作与成果，200 字内或 null"}}]}}
"""
    return [
        {"role": "system", "content": RESUME_EXTRACT_SYSTEM},
        {"role": "user", "content": user},
    ]


# ---- 面经整理（FR-008）：原文结构化提取 ----


EXPERIENCE_EXTRACT_SYSTEM = """你是面试复盘助手，从求职者粘贴的面经原文中提取结构化问答条目。

提取规则：
- 只提取原文中**真实出现的面试问题**，按出现顺序排列；原文没有的问题不要编造，笔试链接、面试流程、面试官态度这类非问答内容一律不提取；
- company 取原文中提到的面试公司名称（如「面了字节跳动」记「字节跳动」）；原文没提、提到多家、或无法确定时记 null，不要猜测；
- question 把口语化、零散的提问整理成通顺的问句，不改变原意；
- answer_points 用原文中提到的回答内容或要点整理（2~4 句）；原文没写答案、或只提了题目没说答案的记 null，不要自己补答案；
- 同一话题被追问成多个小问时，合并成一条；
- 最多 30 条——原文没有可提取的问题时输出空数组，不要凑数。

只输出一个 JSON 对象，不要包裹代码块、不要任何多余文字：
{"company": "公司名或 null", "items": [{"question": "面试问题", "answer_points": "回答要点或 null"}]}"""


def build_experience_extract_messages(original_text: str) -> list[dict]:
    """面经结构化提取（FR-008）：输出 `{"company", "items":[{question, answer_points}]}` 供后端落库。

    原文全量注入——面经入库时已限 10000 字（接口文档 3.10），无需再截断。
    """
    user = f"""【面经原文】
{original_text}

请提取结构化问答条目。"""
    return [
        {"role": "system", "content": EXPERIENCE_EXTRACT_SYSTEM},
        {"role": "user", "content": user},
    ]


# ---- 岗位投喂（FR-021）：JD 原文 / 链接正文 → 岗位字段抽取 ----


INGEST_TEXT_LIMIT = 6000  # 投喂原文注入上限（字符）：粘贴正文通常在此以内，控制 prefill 长度

INGEST_EXTRACT_SYSTEM = """你是信息抽取助手，从招聘信息原文中抽取岗位字段。

抽取规则：
- 只抽取原文中明确写出的信息，缺失或拿不准的字段一律记 null，**不要编造、不要推测**；
- title 是岗位名称（如「Java 后端开发工程师」），company 是招聘公司名称（如「华为技术有限公司」）；
- city 只取工作所在城市名（如「南京」），不要填详细地址；原文提及多个城市时取第一个；
- job_type 只取 CAMPUS（校招）/ INTERN（实习）/ SOCIAL（社招）之一，从岗位性质判断、拿不准记 null；
- deadline 是投递截止日期，格式 YYYY-MM-DD，原文没写或无法确定记 null；
- salary_text 保留原文写法（如「15-25K·14薪」），不做换算；edu_req 如「本科及以上」；
- major_req 如「计算机、软件工程相关专业」。

只输出一个 JSON 对象，不要包裹代码块、不要任何多余文字：
{"title": "岗位名称或 null", "company": "公司名或 null", "city": "城市或 null", "edu_req": "学历要求或 null", "major_req": "专业要求或 null", "salary_text": "薪资原文或 null", "job_type": "CAMPUS 或 INTERN 或 SOCIAL 或 null", "deadline": "YYYY-MM-DD 或 null"}"""


def build_ingest_extract_messages(text: str) -> list[dict]:
    """岗位投喂抽取（FR-021）：输出 8 个岗位字段 JSON，缺失字段为 null。

    原文注入前截断到 INGEST_TEXT_LIMIT（接口层已限长，这里兜底）。
    """
    user = f"""【招聘信息原文】
{text[:INGEST_TEXT_LIMIT]}

请抽取岗位字段。"""
    return [
        {"role": "system", "content": INGEST_EXTRACT_SYSTEM},
        {"role": "user", "content": user},
    ]


# ---- 全局 Agent（FR-011）：意图路由、对话与工具调用 ----


INTENT_CLASSIFY_SYSTEM = """你是个人求职助手的意图识别模块。判断用户这句话属于哪一类，只输出 JSON。

【意图枚举】
- APPLICATION：求职过程操作——记录新投递、查询投递进展、更新投递状态、问今天要跟进什么；
- PRACTICE：笔试与刷题——出题练习、复习错题、问八股知识点；
- EXPERIENCE：面经相关——检索面经、问某公司面试考了什么；
- CHAT：以上都不是的闲聊或其他提问。

只输出一个 JSON 对象，不要包裹代码块、不要任何多余文字：
{"intent": "APPLICATION"}"""


def build_intent_classify_messages(message: str) -> list[dict]:
    """意图分类对话（规则快筛未命中时走本路，chat_json 非流式）。"""
    return [
        {"role": "system", "content": INTENT_CLASSIFY_SYSTEM},
        {"role": "user", "content": message},
    ]


AGENT_SYSTEM = """你是个人求职助手的对话入口，通过自然语言帮用户处理求职事务。

【当前日期】{today}
{profile}
【工作方式】
- 需要查数据、办事情时调用给你的工具，绝不凭空编造数据；
- 写操作（记录投递、更新状态）由系统出确认卡片、用户确认后生效——你调用工具后如实告知用户「已生成确认卡片，确认后生效」；
- 查询类工具由系统执行、结果交给你总结——用自然语言讲清楚，别罗列原始字段；
- 信息不够时直接追问缺失的关键信息（如公司名、岗位名），不要猜测。

【回复约束】
- 简洁自然，一般 200 字以内；
- 不要 markdown 表格、不要加粗与反引号（前端按纯文本渲染），分条用「- 」；
- 不要出现"作为 AI"这类自指表述。"""


def build_agent_system(profile, *, with_profile: bool, today: str) -> str:
    """组装 Agent 对话 system prompt。

    `with_profile`——仅 APPLICATION / EXPERIENCE 意图注入画像摘要（系统设计 5.2，控 token）；
    用 replace 而非 format 注入，画像内容若含花括号不会被当作占位符。
    """
    block = f"\n【用户画像】\n{build_profile_digest(profile)}\n" if with_profile else ""
    return AGENT_SYSTEM.replace("{today}", today).replace("{profile}", block)


AGENT_FOLLOWUP_UNKNOWN = "这部分我没太理解清楚，麻烦你再说明白一点～"


def build_agent_followup(tool_label: str, missing: list[str]) -> str:
    """工具参数不全时的追问文案（系统设计 5.2：Function Calling 失败降级为追问）。"""
    return f"好的，要帮你{tool_label}，还差这些信息：{'、'.join(missing)}。麻烦补充一下～"


def build_agent_result_note(tool_label: str, data_text: str) -> str:
    """查询类工具执行结果回灌 LLM 的提示文本（要求其口头总结、不再调工具）。"""
    return (
        f"【系统】工具「{tool_label}」已执行，返回数据如下：\n{data_text}\n\n"
        "请据此用自然语言向用户总结（不要罗列原始 JSON、不要再调用工具）。"
    )


# ---------- 提醒文案（FR-013）：每日任务生成提醒时的一次性文案改写 ----------
# 判定全为纯规则（不调 LLM），本场景是每日任务里唯一一次 LLM 调用；失败一律回退模板文案。

REMINDER_DIGEST_SYSTEM = """你是求职助手的提醒文案写手，把每日提醒清单改写成自然口语的一句话。

【输入】每行一条提醒，格式为「序号. [类型] 内容」。

【输出格式】
只输出一个 JSON 对象，不要代码块、不要任何多余文字：
{"items": [{"index": 1, "content": "改写后的文案"}]}
index 与输入序号一一对应，输入几条就输出几条、一条都不能少。

【约束】
- 每条 20~50 字，一句话讲清「发生了什么 + 建议做什么」；
- 直接对用户说话（可用「你」），语气自然、像朋友提醒，别写成系统通知；
- 只基于输入内容改写，不编造输入里没有的信息；
- 不要序号前缀、不用 markdown 标记。"""


def build_reminder_messages(fact_lines: list[str]) -> list[dict]:
    """提醒文案批量改写对话（chat_json 非流式，一次生成该账号全部条目）。"""
    user = "【今日提醒清单】\n" + "\n".join(fact_lines)
    return [
        {"role": "system", "content": REMINDER_DIGEST_SYSTEM},
        {"role": "user", "content": user},
    ]


# ---------- 练习模式（FR-020）：题面生成 / 逐遍点评 ----------

# 来源中文名（与前端 SOURCE_LABELS 同口径）
DRILL_SOURCE_LABELS: dict[str, str] = {
    DrillSource.INTRO.value: "自我介绍",
    DrillSource.RESUME.value: "画像经历",
    DrillSource.WRONG.value: "错题本",
    DrillSource.EXPERIENCE.value: "面经",
    DrillSource.JD.value: "投递记录",
    DrillSource.CUSTOM.value: "手动新建",
}

DRILL_QUESTION_SYSTEM = """你是求职者的面试练习教练，正在帮他把一道题打磨成可反复练习的完整题目。

出题规则：
- 依据题目名称与来源信息，写一道完整、口语化、能直接作答的题（像面试官当面提问）；
- 落到具体的知识点或经历上，不要「谈一谈你对 XX 的理解」这类宽泛问法；
- 若来源信息不足以确定题面，就把题目名称本身展开成一道完整的题；
- 一题一问，不超过 200 字，不分点、不写小标题。

输出约束：
只输出一个 JSON 对象，不要代码块、不要任何多余文字：
{"question": "题面全文"}"""


def build_drill_question_messages(*, title: str, source: str, source_note: str) -> list[dict]:
    """题面生成（POST /drills 未提供 question 时，chat_json 非流式）：输出 = {"question": "..."}。

    `source_note` 为来源细节文本（错题题干 / 面经条目要点 / 岗位 JD 节选，服务层组装）；
    无来源信息（CUSTOM / INTRO）为空串、prompt 不含来源块。
    """
    parts = [f"【题目名称】\n{title}"]
    if source_note:
        parts.append(f"【题目来源】{DRILL_SOURCE_LABELS.get(source, source)}\n{source_note}")
    user = "\n\n".join(parts) + "\n\n请生成题面。"
    return [
        {"role": "system", "content": DRILL_QUESTION_SYSTEM},
        {"role": "user", "content": user},
    ]


# 点评分段规则（接口文档 3.15）：标题行命中即开关对应段，与下方模板的标题文案一一对应
DRILL_REVIEW_SECTION_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("评分",), "score"),
    (("点评",), "review"),
)

DRILL_REVIEW_SYSTEM = """你是求职者的面试练习教练，正在点评他刚练的这一遍。

评审规则：
- 评分 0~10 的整数，依据是「这题答到了多少关键点」，不因表达啰嗦、举例多少扣分；
- 亮点要具体到他说的哪句话、哪个知识点，不要空夸；
- 不足要指出漏掉或答错的关键点，并给出可操作的补充方向，禁止「回答不够全面」「再深入一些」这类空话；
- 参考要点给出本题理想回答的骨架，不超过 150 字；
- 若给了【表达力指标】，结合指标与他的作答原话点评表达表现（引用原话，如「讲到缓存雪崩时停了 3 秒」）；描述停顿统一用「停顿」，不要用「卡壳」「结巴」；参考区间是经验值、只用于措辞分档，不作为评分依据。

输出约束（前端按纯文本渲染，标记会原样暴露在页面上）：
- 开头第一行固定为「## 评分」，紧接着一行只写评分本身、格式为「数字/10」（0~10 的整数），不要加「评分：」前缀、不要写其他内容；
- 随后固定为「## 点评」标题行，正文用「- 」分条给出三节：亮点、不足、参考要点；
- 不要 markdown 表格、不要加粗与反引号，不要「①②③」类符号编号；
- 开场先承接他的作答原话，不要用「回答正确」「回答错误」这类判词式的一句话结论开场；
- 语气是教练：答得好点明好在哪，答得差先给可操作的下一步。"""


def build_drill_review_messages(
    *, title: str, question: str, answer: str, voice_metrics: dict | None = None
) -> list[dict]:
    """练习模式逐遍点评（POST /stream/drill-review）：输出 = `score` + `review` 两段。

    `voice_metrics` 为语音作答的表达力指标快照（quality=OK 时传入，见 `_voice_metrics_block`）；
    文字作答与作答过短传 None、prompt 不含表达维度。
    """
    user = f"""【本轮题目】{title}
{question}

【他的作答】
{answer}

{_voice_metrics_block(voice_metrics)}按以下结构输出，标题原样保留：

## 评分
只写一行评分本身，格式为「数字/10」（0~10 的整数），不要加前缀、不要写其他内容。

## 点评
用「- 」分条给出三节：亮点（他答到的关键点，引他的原话）、不足（漏掉或答错的关键点 + 可操作的补充方向）、参考要点（本题理想回答的骨架，不超过 150 字）。"""
    return [
        {"role": "system", "content": DRILL_REVIEW_SYSTEM},
        {"role": "user", "content": user},
    ]
