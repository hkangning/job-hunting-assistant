"""八股陪练模块传输模型：训练系统（接口文档 3.8；表结构见数据库设计 3.8 / 3.23 / 3.24）。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_serializer

from app.models.enums import Direction, PracticeMode, QuestionType, Stack
from app.utils.datetime_utils import format_datetime


# ---- 元数据（GET /practice/meta）----


class DomainOption(BaseModel):
    """领域选项（栈下辖）。"""

    value: str = Field(description="领域枚举值，如 JVM / REDIS")
    label: str = Field(description="领域中文名")


class StackOption(BaseModel):
    """技术栈选项（两级筛选的第一级）。"""

    value: str = Field(description="技术栈枚举值，如 JAVA_BACKEND")
    label: str = Field(description="技术栈中文名")
    domains: list[DomainOption] = Field(description="该栈下辖的领域清单")


class PositionOption(BaseModel):
    """岗位视角：若干技术栈的并集，供前端一键展开成 stacks 数组。"""

    value: str = Field(description="岗位枚举值，如 JAVA")
    label: str = Field(description="岗位中文名")
    stacks: list[str] = Field(description="该岗位覆盖的技术栈枚举值数组")


class QtypeOption(BaseModel):
    """题型选项。"""

    value: str = Field(description="题型枚举值：SUBJECTIVE / CHOICE / SCENARIO")
    label: str = Field(description="题型中文名")


class ModeOption(BaseModel):
    """训练模式选项（模式选择卡片的数据源）。"""

    value: str = Field(description="模式枚举值，如 INTERVIEWER")
    label: str = Field(description="模式中文名")
    description: str = Field(description="一句话玩法说明，直接展示在卡片上")
    max_rounds: int = Field(description="作答轮数上限，供前端显示「第 2/5 轮」的进度")


class FaceOption(BaseModel):
    """追问攻击面选项（供前端渲染「第 2 层 · 边界」的追问进度）。"""

    value: str = Field(description="攻击面枚举值：BASIS / BOUNDARY / TRADEOFF / LANDING")
    label: str = Field(description="攻击面中文名")
    layer: int = Field(description="层号 1~4，与攻击面固定一一对应")
    hint: str = Field(description="该层追什么，一句话说明")


class PracticeMetaDTO(BaseModel):
    """抽题筛选面板与模式选择的元数据（GET /practice/meta）。"""

    stacks: list[StackOption] = Field(description="技术栈清单（含下辖领域）")
    positions: list[PositionOption] = Field(description="岗位视角清单")
    qtypes: list[QtypeOption] = Field(description="题型清单")
    modes: list[ModeOption] = Field(description="五种训练模式清单")
    faces: list[FaceOption] = Field(description="四层追问攻击面清单")
    time_limits: list[int] = Field(description="每轮限时档位（秒），不传限时即不限时")


# ---- 抽题（POST /practice/questions）----


class QuestionPickRequest(BaseModel):
    """抽题请求体。"""

    stacks: list[Stack] | None = Field(
        default=None, description="技术栈数组（可多选），元素为 Stack 枚举值；不传 = 不限栈；非法值返回 10001"
    )
    directions: list[Direction] | None = Field(
        default=None, description="领域数组（可多选），元素为 Direction 枚举值；不传 = 不限领域；非法值返回 10001"
    )
    qtypes: list[QuestionType] | None = Field(
        default=None, description="题型数组，元素 SUBJECTIVE / CHOICE / SCENARIO；不传 = 不限题型；非法值返回 10001"
    )
    count: int = Field(default=1, ge=1, le=5, description="抽题数，默认 1，最大 5")
    strategy: Literal["SMART", "RANDOM"] = Field(
        default="SMART", description="选题策略：SMART 薄弱优先（默认）/ RANDOM 纯随机；非法值返回 10001"
    )


class QuestionItem(BaseModel):
    """抽到的题目（不含 answer 与 rubric，防先看答案）。"""

    id: int = Field(description="题目 id")
    stack: str = Field(description="技术栈枚举值")
    direction: str = Field(description="领域枚举值")
    content: str = Field(description="题干")
    qtype: str = Field(description="题型枚举值")
    mastery: int = Field(description="该题所属领域的当前掌握度 0~100（无记录为 0），供前端标注弱项")


class QuestionListData(BaseModel):
    """抽题响应数据。"""

    items: list[QuestionItem] = Field(description="抽到的题目列表；命中不足 count 时按实际数量返回")


# ---- 开一场训练（POST /practice/sessions）----


class SessionCreateRequest(BaseModel):
    """开一场训练的请求体。"""

    question_id: int = Field(description="题目 id（来自抽题接口）")
    mode: PracticeMode = Field(
        description="训练模式：QUICK 快练 / INTERVIEWER 面试官深挖 / COACH 教练引导 / DEBUG 挑错纠错 / FEYNMAN 费曼复述；非法值返回 10001"
    )
    time_limit: int | None = Field(
        default=None, description="每轮限时秒数，取值 30 / 60 / 90 / 120；不传 = 不限时；非档位值返回 10001"
    )


class SessionCreateData(BaseModel):
    """开一场训练的响应数据。"""

    session_id: int = Field(description="训练会话 id，后续每轮与结算都带它")
    question_id: int = Field(description="题目 id")
    mode: str = Field(description="训练模式枚举值")
    status: str = Field(description="会话状态，恒为 RUNNING")
    time_limit: int | None = Field(description="每轮限时秒数，null = 不限时")
    round_index: int = Field(description="下一轮轮次号，恒为 1（第一轮尚未作答）")
    started_at: datetime = Field(description="开始时间 YYYY-MM-DD HH:mm:ss")

    @field_serializer("started_at")
    def _serialize_datetime(self, value: datetime) -> str | None:
        """时间字段按接口口径输出 `YYYY-MM-DD HH:mm:ss`。"""
        return format_datetime(value)


# ---- 每轮推进（POST /stream/practice-turn）----


class PracticeTurnRequest(BaseModel):
    """每轮统一入口的请求体（首次调用即初始作答）。"""

    session_id: int = Field(description="训练会话 id")
    user_input: str | None = Field(
        default=None, description="本轮作答内容；action=HINT 与 DEBUG 取材料时不需要"
    )
    action: Literal["SUBMIT", "HINT", "END"] = Field(
        default="SUBMIT", description="SUBMIT 提交作答（默认）/ HINT 求提示 / END 主动结束本场；非法值返回 10001"
    )
    elapsed_ms: int | None = Field(default=None, ge=0, description="本轮耗时毫秒（限时模式由前端计时上报，供复盘）")
    timed_out: bool = Field(default=False, description="是否超时自动提交，默认 false")


# ---- 结算（POST /practice/sessions/{id}/finish）----


class RoundBrief(BaseModel):
    """结算响应里的单轮摘要。"""

    index: int = Field(description="轮次号（1 起）")
    kind: str = Field(description="轮次类型，枚举 RoundKind")
    score: int | None = Field(description="该轮评分 0~10；提示轮与材料轮为 null")
    is_break: bool = Field(description="该轮是否记为断点（答不上 / 提示后仍答不出 / 限时内一字未写）")


class MasteryDelta(BaseModel):
    """本场训练对该题所属领域掌握度的影响。"""

    direction: str = Field(description="领域枚举值")
    before: int = Field(description="本场之前的掌握度 0~100")
    after: int = Field(description="本场之后的掌握度 0~100")


class SessionFinishData(BaseModel):
    """结算响应数据。"""

    session_id: int = Field(description="训练会话 id")
    mode: str = Field(description="训练模式枚举值")
    question_id: int = Field(description="题目 id")
    overall_score: int | None = Field(description="整场综合分 0~10，由各轮评分聚合（不含提示轮与材料轮）")
    passed: bool = Field(description="是否通过：按各模式的通过判据判定")
    rounds: list[RoundBrief] = Field(description="逐轮摘要（按轮次升序）")
    break_face: str | None = Field(description="首个断点所在攻击面（层号由它唯一确定）；全程无断点为 null")
    hint_count: int = Field(description="本场求提示次数")
    reference_answer: str = Field(description="完整参考答案（追问模式在此才给，防泄题）")
    gaps: list[str] = Field(description="相对参考答案的缺口清单，由各轮点评累积（服务端汇总，不额外调 LLM）")
    mastery_delta: MasteryDelta | None = Field(description="掌握度变化；无记录时为 null")
    wrong_question_id: int | None = Field(
        description="未通过时自动入本产生的错题条目 id；该题已在错题本则更新复习档位并返回原 id；通过或未入本为 null"
    )


# ---- 训练历史（GET /practice/sessions）----


class SessionListItem(BaseModel):
    """训练历史列表项。"""

    id: int = Field(description="训练会话 id")
    question_id: int = Field(description="题目 id")
    question_content: str = Field(description="题干预览（截断），供列表直接展示")
    mode: str = Field(description="训练模式枚举值")
    status: str = Field(description="会话状态，枚举 PracticeSessionStatus")
    time_limit: int | None = Field(description="每轮限时秒数；null = 开一场时未设限时")
    overall_score: int | None = Field(description="整场综合分；未结算为 null")
    passed: bool | None = Field(description="是否通过；未结算为 null")
    break_face: str | None = Field(description="首个断点所在攻击面；未结算或全程无断点为 null")
    round_count: int = Field(description="本场已完成的轮数（含提示轮与材料轮）")
    started_at: datetime = Field(description="开始时间")
    finished_at: datetime | None = Field(description="结算时间；未结算为 null")

    @field_serializer("started_at", "finished_at")
    def _serialize_datetime(self, value: datetime | None) -> str | None:
        """时间字段按接口口径输出 `YYYY-MM-DD HH:mm:ss`。"""
        return format_datetime(value)


# ---- 单场回看（GET /practice/sessions/{id}）----


class QuestionBrief(BaseModel):
    """回看页的题目信息。"""

    id: int = Field(description="题目 id")
    content: str = Field(description="题干全文")
    qtype: str = Field(description="题型枚举值")
    stack: str = Field(description="技术栈枚举值")
    direction: str = Field(description="领域枚举值")


class SessionRoundItem(BaseModel):
    """回看页的单轮记录。"""

    index: int = Field(description="轮次号（1 起）")
    kind: str = Field(description="轮次类型，枚举 RoundKind")
    user_answer: str | None = Field(description="该轮作答；提示轮没有作答为 null")
    score: int | None = Field(description="该轮评分 0~10；提示轮与材料轮为 null")
    review: str | None = Field(description="该轮 AI 点评全文；DEBUG 的材料轮存的是材料全文")
    elapsed_ms: int | None = Field(description="本轮耗时毫秒（限时模式）")
    timed_out: bool = Field(description="本轮是否超时提交")
    created_at: datetime = Field(description="该轮落库时间")

    @field_serializer("created_at")
    def _serialize_datetime(self, value: datetime) -> str | None:
        """时间字段按接口口径输出 `YYYY-MM-DD HH:mm:ss`。"""
        return format_datetime(value)


class SessionDetailData(BaseModel):
    """单场回看数据。"""

    id: int = Field(description="训练会话 id")
    mode: str = Field(description="训练模式枚举值")
    status: str = Field(description="会话状态，枚举 PracticeSessionStatus")
    time_limit: int | None = Field(description="每轮限时秒数；null = 开一场时未设限时（续练按此恢复倒计时）")
    question: QuestionBrief = Field(description="题目信息")
    overall_score: int | None = Field(description="整场综合分；未结算为 null")
    passed: bool | None = Field(description="是否通过；未结算为 null")
    break_face: str | None = Field(description="首个断点所在攻击面；未结算或全程无断点为 null")
    hint_count: int = Field(description="本场求提示次数")
    rounds: list[SessionRoundItem] = Field(description="逐轮记录（按轮次升序）")
    reference_answer: str | None = Field(description="完整参考答案；仅会话已结算时返回，追问中为 null（防泄题）")


# ---- 领域掌握度（GET /practice/mastery）----


class MasteryDomainItem(BaseModel):
    """单个领域的掌握度。"""

    direction: str = Field(description="领域枚举值")
    label: str = Field(description="领域中文名")
    mastery: int = Field(description="掌握度 0~100（公式见 SRS §3.6）")
    answered_count: int = Field(description="累计作答轮次（含追问轮，不含提示轮）")
    covered_count: int = Field(description="该领域练过的不同题目数")
    last_practiced_at: datetime | None = Field(description="最近练习时间；从未练过为 null")

    @field_serializer("last_practiced_at")
    def _serialize_datetime(self, value: datetime | None) -> str | None:
        """时间字段按接口口径输出 `YYYY-MM-DD HH:mm:ss`。"""
        return format_datetime(value)


class MasteryGroup(BaseModel):
    """按技术栈分组的掌握度。"""

    stack: str = Field(description="技术栈枚举值")
    label: str = Field(description="技术栈中文名")
    average: int = Field(description="该栈下有记录领域的掌握度均值（整数）")
    domains: list[MasteryDomainItem] = Field(description="该栈下有练习记录的领域清单")


class MasteryData(BaseModel):
    """掌握度列表数据（只含练过的领域，没练过的不出现）。"""

    groups: list[MasteryGroup] = Field(description="按技术栈分组的掌握度；全无记录时为空数组")
