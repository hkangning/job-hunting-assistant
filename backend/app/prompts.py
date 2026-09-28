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

from app.models import AttackFace, QuestionType, UserProfile

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


def build_practice_followup_messages(
    question, *, history: list[dict], face: AttackFace | None = None
) -> list[dict]:
    """下一轮追问（INTERVIEWER / COACH / FEYNMAN）。输出 = `next_question`。

    `face` 为四层追问链的攻击面，**费曼模式不传**——它的追问方向由复述轮挑出的漏洞决定。
    """
    direction = f"\n【本轮追问方向】{ATTACK_FACE_HINTS[face.value]}\n" if face else ""
    user = f"""【题目】{question.content}

【要点靶子】（判断他哪些关键点还没答到）
{_key_points(question)}

【此前的轮次】
{_history_brief(history)}
{direction}
按以下结构输出，标题原样保留：

## 追问
一句话顺着他的原话接（"你刚说用了 X——那……"），**只问一个问题**。优先追他还没答到的关键点；这块他已说清楚就换个角度继续。
"""
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
