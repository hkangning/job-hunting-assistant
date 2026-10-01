"""全局 Agent：意图路由 + 工具注册表 + 流式 Function Calling 编排（系统设计 5.2，接口文档 3.11）。

四条结构约定：

1. **写操作类工具只出确认卡片**——LLM 发起的写调用不执行、不落库，发 `tool_call` 事件由前端
   渲染确认卡片，用户确认后走 `POST /agent/tools/{tool}/execute`（步骤 19 挂路由，执行函数
   `execute_tool` 本步交付）；
2. **查询类工具由本模块直接执行**，结果回灌 LLM 生成流式总结，末尾附一条 `section="result"`
   的结构化 JSON 块（节奏器整块直通，`_PACE_EXEMPT_SECTIONS`）；
3. **参数不全降级为追问**（系统设计 5.2）——缺失字段以 `delta` 文字追问、正常结束，
   不发 `tool_call`、不报错；参数能从上下文补齐的自动补（如按公司名匹配投递）；
4. **落库统一发生在流正常结束后**（会话与消息同一事务）——断连 / 中途失败不落任何消息，
   重试即整轮重发；新建会话延迟到落库时创建，失败场景零残留。
"""

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clients.llm_client import LLMClient, LLMConfig, TextDelta, ToolCallDelta, resolve_config
from app.exceptions import BizException, ErrorCode
from app.models import AgentConversation, AgentMessage, Application, UserProfile
from app.models.enums import ApplicationStatus, CloseReason, Direction, MessageRole
from app.prompts import (
    AGENT_FOLLOWUP_UNKNOWN,
    build_agent_followup,
    build_agent_result_note,
    build_agent_system,
    build_intent_classify_messages,
)
from app.schemas.agent import ConversationItem, ConversationMessageItem
from app.schemas.application import ApplicationStatusUpdate
from app.schemas.common import PageData
from app.services import (
    application_service,
    experience_service,
    overview_service,
    practice_service,
    wrong_question_service,
)
from app.utils.datetime_utils import format_datetime
from app.utils.sse import SSE

VALID_INTENTS = frozenset({"APPLICATION", "PRACTICE", "EXPERIENCE", "CHAT"})
INTENT_CHAT = "CHAT"

# 规则快筛关键词（系统设计 5.2：先规则、不命中再 LLM 分类）。有序——命中即返回；
# 宁可漏判（走 LLM 分类兜底）不可错判，故只收较明确的词面
_RULE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("APPLICATION", ("投递", "投了", "记一笔", "offer", "标记为", "状态改", "进行到哪", "进度怎么样")),
    ("PRACTICE", ("出题", "来几道", "来三道", "刷题", "练一练", "陪练", "错题", "八股", "复习")),
    ("EXPERIENCE", ("面经", "面试问了", "面试考了", "面试题")),
)

# 意图 → 可下发工具子集（CHAT 不带工具直接闲聊；控 token 与误调用）
_INTENT_TOOLS: dict[str, tuple[str, ...]] = {
    "APPLICATION": (
        "create_application",
        "update_application_status",
        "list_applications",
        "get_today_summary",
    ),
    "PRACTICE": ("generate_questions", "quiz_wrong_questions"),
    "EXPERIENCE": ("search_experience",),
}

# 对话历史：最近轮数与单条截断（系统设计 5.2「最近 10 轮，超长截断」）
_HISTORY_TURNS = 10
_HISTORY_ITEM_LIMIT = 400

# 查询结果回灌总结时的助手占位（模型已吐前置文字时用原文，未吐时给个不突兀的过桥）
_QUERY_BRIDGE = "（正在查询数据…）"


# ---------- 工具注册表 ----------


@dataclass(frozen=True)
class ToolSpec:
    """工具元数据：一份定义同时供 LLM（function schema）与执行侧（kind / required）使用。"""

    name: str  # 工具名（与 TOOLS 键一致）
    label: str  # 中文动作短语（追问文案用）
    kind: str  # write 写操作（出确认卡片）/ query 查询（后端直接执行）
    description: str  # 给模型的能力说明
    properties: dict  # JSON Schema 参数定义（description 兼作追问时的字段中文名）
    required: tuple[tuple[str, str], ...] = ()  # 必填参数：(字段名, 中文名)
    handler: Callable[[Session, int, dict], dict] | None = None  # 查询类执行函数；写操作类为 None


def _h_list_applications(db: Session, user_id: int, args: dict) -> dict:
    """查投递：按状态 / 公司名筛本账号记录（列表口径与 GET /applications 一致，取前 10 条）。"""
    page = application_service.list_applications(
        db,
        user_id=user_id,
        status=_as_enum(args.get("status"), ApplicationStatus),
        company=_clean_optional(args.get("company")),
        page=1,
        page_size=10,
    )
    return {
        "total": page.total,
        "items": [
            {
                "id": item.id,
                "company": item.company,
                "position": item.position,
                "status": item.status,
                "status_label": application_service.STATUS_LABELS.get(item.status, item.status),
                "city": item.city,
                "applied_at": str(item.applied_at),
            }
            for item in page.items
        ],
    }


def _h_generate_questions(db: Session, user_id: int, args: dict) -> dict:
    """出题：从题库抽取（SMART 薄弱优先），题目带 id 供前端跳转陪练。"""
    direction = _as_enum(args.get("direction"), Direction)
    count = _clamp_int(args.get("count"), default=3, lo=1, hi=10)
    questions = practice_service.pick_questions(
        db, user_id=user_id, directions=[direction] if direction else None, count=count
    )
    return {
        "questions": [
            {"id": q.id, "direction": q.direction, "qtype": q.qtype, "content": q.content}
            for q in questions
        ]
    }


def _h_quiz_wrong_questions(db: Session, user_id: int, args: dict) -> dict:
    """抽错题：按到期优先的列表口径取前 N 条（与 GET /wrong-questions 一致）。"""
    direction = _as_enum(args.get("direction"), Direction)
    count = _clamp_int(args.get("count"), default=5, lo=1, hi=20)
    page = wrong_question_service.list_wrong_questions(
        db,
        user_id=user_id,
        status=None,
        keyword=None,
        direction=direction.value if direction else None,
        page=1,
        page_size=count,
    )
    return {
        "total": page.total,
        "items": [
            {"id": item.id, "direction": item.direction, "qtype": item.qtype, "content": item.content}
            for item in page.items
        ],
    }


def _h_search_experience(db: Session, user_id: int, args: dict) -> dict:
    """搜面经：按关键词模糊匹配本账号面经条目（与 GET /experience-items/search 一致）。"""
    page = experience_service.search_items(
        db, user_id=user_id, keyword=str(args.get("keyword") or ""), page=1, page_size=10
    )
    return {
        "total": page.total,
        "items": [
            {
                "id": item.id,
                "experience_id": item.experience_id,
                "company": item.company,
                "question": item.question,
                "answer_points": item.answer_points,
            }
            for item in page.items
        ],
    }


def _h_today_summary(db: Session, user_id: int, args: dict) -> dict:
    """今日概览：近期待办（笔试/面试）、需跟进的投递、到期错题与投递计数（GET /overview 子集）。"""
    overview = overview_service.build_overview(db, user_id)
    return {
        "date": date.today().isoformat(),
        "upcoming_events": [
            {
                "company": event.company,
                "position": event.position,
                "event_at": format_datetime(event.event_at),
                "status": event.status,
            }
            for event in overview.upcoming_events
        ],
        "follow_ups": [
            {"company": item.company, "position": item.position, "days": item.days}
            for item in overview.follow_ups
        ],
        "due_wrong_questions": overview.wrong_question_count,
        "application_stats": overview.application_stats.model_dump(),
    }


TOOLS: dict[str, ToolSpec] = {
    "create_application": ToolSpec(
        name="create_application",
        label="记录一条投递",
        kind="write",
        description="新增一条投递记录（写操作：系统会出确认卡片，用户确认后入库）",
        properties={
            "company": {"type": "string", "description": "公司名称"},
            "position": {"type": "string", "description": "岗位名称"},
            "city": {"type": "string", "description": "工作城市"},
            "applied_at": {"type": "string", "description": "投递日期 YYYY-MM-DD；用户没提就省略（默认今天）"},
            "channel": {"type": "string", "description": "投递渠道（官网 / BOSS直聘 / 内推等）"},
            "jd_text": {"type": "string", "description": "岗位 JD 原文；用户粘贴了 JD 就带上，没有就省略"},
        },
        required=(("company", "公司名称"), ("position", "岗位名称")),
    ),
    "update_application_status": ToolSpec(
        name="update_application_status",
        label="更新投递进度",
        kind="write",
        description="更新某条投递的进度状态（写操作：系统会出确认卡片，用户确认后生效）",
        properties={
            "application_id": {"type": "integer", "description": "投递记录 id；用户没提供就省略，系统会按公司名自动匹配"},
            "company": {"type": "string", "description": "公司名称（用户说的是某家公司的投递时提供，用于定位记录）"},
            "status": {
                "type": "string",
                "enum": [status.value for status in ApplicationStatus],
                "description": "目标状态：APPLIED 已投递 / WRITTEN 待笔试 / INTERVIEW 面试中 / OFFER 已获offer / CLOSED 已结束",
            },
            "close_reason": {
                "type": "string",
                "enum": [reason.value for reason in CloseReason],
                "description": "结束原因，仅 status=CLOSED 时必填：FAILED 未通过 / DECLINED 主动放弃 / EXPIRED 无消息",
            },
            "remark": {"type": "string", "description": "备注（可选，如面试时间等补充信息）"},
        },
        required=(("status", "目标状态"),),
    ),
    "list_applications": ToolSpec(
        name="list_applications",
        label="查询投递记录",
        kind="query",
        description="查询用户的投递记录（查询类，系统直接执行）",
        properties={
            "status": {
                "type": "string",
                "enum": [status.value for status in ApplicationStatus],
                "description": "按状态筛选（可选）：APPLIED 已投递 / WRITTEN 待笔试 / INTERVIEW 面试中 / OFFER 已获offer / CLOSED 已结束",
            },
            "company": {"type": "string", "description": "按公司名关键词筛选（可选）"},
        },
        handler=_h_list_applications,
    ),
    "generate_questions": ToolSpec(
        name="generate_questions",
        label="出题练习",
        kind="query",
        description="从题库抽题给用户练习（查询类，用户可去陪练页作答）",
        properties={
            "count": {"type": "integer", "description": "抽题数量，默认 3，最多 10"},
            "direction": {
                "type": "string",
                "description": "知识领域（可选）：JAVA / JVM / CONCURRENCY / SPRING / MYSQL / REDIS / MQ / NETWORK / OS / ALGO / DESIGN / PY_BASIC / PY_ASYNC / PY_WEB / LLM_BASIC / PROMPT / RAG / AGENT",
            },
        },
        handler=_h_generate_questions,
    ),
    "quiz_wrong_questions": ToolSpec(
        name="quiz_wrong_questions",
        label="抽错题复习",
        kind="query",
        description="查询用户的错题（查询类，按到期优先返回）",
        properties={
            "count": {"type": "integer", "description": "返回数量，默认 5，最多 20"},
            "direction": {"type": "string", "description": "按知识领域筛选（可选，取值同 generate_questions）"},
        },
        handler=_h_quiz_wrong_questions,
    ),
    "search_experience": ToolSpec(
        name="search_experience",
        label="检索面经",
        kind="query",
        description="按关键词检索用户收集的面经条目（查询类）",
        properties={"keyword": {"type": "string", "description": "检索关键词（公司名 / 技术点等）"}},
        required=(("keyword", "检索关键词"),),
        handler=_h_search_experience,
    ),
    "get_today_summary": ToolSpec(
        name="get_today_summary",
        label="查今日待办",
        kind="query",
        description="查用户今天要跟进的事项：待笔试/面试、需要跟进的投递、到期错题（查询类）",
        properties={},
        handler=_h_today_summary,
    ),
}


def _tools_payload(intent: str) -> list[dict]:
    """按意图取工具子集并转 openai Function Calling 的 `tools` 载荷。"""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": {
                    "type": "object",
                    "properties": spec.properties,
                    "required": [field for field, _ in spec.required],
                },
            },
        }
        for name in _INTENT_TOOLS.get(intent, ())
        if (spec := TOOLS.get(name))
    ]


# ---------- 意图路由 ----------


def route_intent(client: LLMClient, config: LLMConfig, message: str) -> str:
    """四类意图路由：规则快筛（关键词）→ 未命中走 LLM 分类（系统设计 5.2）。

    分类结果非法 → 归 CHAT；LLM 调用失败（LLMError）**原样抛出**——不静默降级，
    错误与提示由流式层统一下发（用户可重试）。
    """
    matched = _route_by_rules(message)
    if matched:
        return matched
    data = client.chat_json(config, build_intent_classify_messages(message))
    intent = str(data.get("intent") or "").strip().upper()
    return intent if intent in VALID_INTENTS else INTENT_CHAT


def _route_by_rules(message: str) -> str | None:
    """关键词快筛：命中返回意图，未命中返回 None（交 LLM 分类）。"""
    text = message.lower()
    for intent, keywords in _RULE_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return intent
    return None


# ---------- 写操作执行（步骤 19 的 execute 端点复用）----------


def execute_tool(db: Session, *, user_id: int, tool_name: str, args: dict) -> dict:
    """执行写操作类工具：入库并返回投递 DTO（接口文档 3.11 的确认卡片执行入口）。

    参数缺失 / 非法 → 50001；工具不是写操作类 → 10001；投递不存在或不属当前账号 → 404+10002。
    """
    if tool_name == "create_application":
        missing = _missing_fields(TOOLS[tool_name], args)
        if missing:
            raise BizException(ErrorCode.AGENT_TOOL_ARGS_MISSING, f"缺少：{'、'.join(missing)}")
        dto = application_service.create_from_fields(
            db,
            user_id,
            company=str(args["company"]).strip(),
            position=str(args["position"]).strip(),
            jd_text=_clean_optional(args.get("jd_text")),
            city=_clean_optional(args.get("city")),
            applied_at=_parse_date(args.get("applied_at")),
            channel=_clean_optional(args.get("channel")),
        )
        return dto.model_dump()

    if tool_name == "update_application_status":
        status = _as_status(args.get("status"))
        if status is None:
            raise BizException(ErrorCode.AGENT_TOOL_ARGS_MISSING, "缺少：目标状态")
        application_id = _as_int(args.get("application_id"))
        if application_id is None:
            raise BizException(ErrorCode.AGENT_TOOL_ARGS_MISSING, "缺少：投递记录 id")
        close_reason = _as_close_reason(args.get("close_reason"))
        if status == ApplicationStatus.CLOSED and close_reason is None:
            raise BizException(
                ErrorCode.AGENT_TOOL_ARGS_MISSING, "标记为已结束需要指明原因：FAILED / DECLINED / EXPIRED"
            )
        payload = ApplicationStatusUpdate(
            status=status,
            close_reason=close_reason,
            remark=_clean_optional(args.get("remark")),
        )
        dto = application_service.change_status(db, user_id, application_id, payload)
        return dto.model_dump()

    raise BizException(ErrorCode.PARAM_INVALID, f"工具 {tool_name} 不支持执行")


# ---------- 会话与消息查询（routers/agent.py 用）----------


def get_conversation(db: Session, *, user_id: int, conversation_id: int) -> AgentConversation:
    """取本账号会话；不存在或不属当前账号一律 404 + 10002（不暴露资源存在性）。"""
    conv = db.scalar(
        select(AgentConversation).where(
            AgentConversation.id == conversation_id, AgentConversation.user_id == user_id
        )
    )
    if conv is None:
        raise BizException(ErrorCode.NOT_FOUND, "会话不存在")
    return conv


def list_conversations(
    db: Session, *, user_id: int, page: int, page_size: int
) -> PageData[ConversationItem]:
    """会话列表：按最近活动时间倒序（同秒按 id 倒序）。"""
    total = (
        db.scalar(
            select(func.count()).select_from(AgentConversation).where(AgentConversation.user_id == user_id)
        )
        or 0
    )
    rows = db.scalars(
        select(AgentConversation)
        .where(AgentConversation.user_id == user_id)
        .order_by(AgentConversation.updated_at.desc(), AgentConversation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PageData[ConversationItem](
        total=total,
        items=[ConversationItem(id=row.id, title=row.title, updated_at=row.updated_at) for row in rows],
    )


def list_messages(
    db: Session, *, user_id: int, conversation_id: int
) -> list[ConversationMessageItem]:
    """会话消息：按时间正序（同秒按 id 正序）；会话归属校验同上。"""
    conv = get_conversation(db, user_id=user_id, conversation_id=conversation_id)
    rows = db.scalars(
        select(AgentMessage)
        .where(AgentMessage.conversation_id == conv.id)
        .order_by(AgentMessage.created_at.asc(), AgentMessage.id.asc())
    ).all()
    return [
        ConversationMessageItem(
            id=row.id,
            role=row.role,
            content=row.content,
            tool_name=row.tool_name,
            created_at=row.created_at,
        )
        for row in rows
    ]


# ---------- 流式编排 ----------


def run_agent_chat(
    db: Session,
    *,
    user_id: int,
    conversation_id: int | None,
    message: str,
    client: LLMClient,
) -> Iterator[str]:
    """Agent 对话流式编排：yield SSE 事件、`return` done 载荷（utils/sse.py 的业务生成器约定）。

    与面试 / 陪练链路同口径：**流正常结束才落库**，断连与中途失败不落任何消息（重试即整轮重发）；
    新建会话延迟到落库时创建——失败场景不留空会话。
    """
    conv: AgentConversation | None = None
    history: list[dict] = []
    if conversation_id is not None:
        conv = get_conversation(db, user_id=user_id, conversation_id=conversation_id)
        history = _history_messages(db, conv.id)

    config = resolve_config(db, user_id)
    intent = route_intent(client, config, message)
    with_profile = intent in ("APPLICATION", "EXPERIENCE")
    profile = (
        db.scalar(select(UserProfile).where(UserProfile.user_id == user_id)) if with_profile else None
    )
    messages = [
        {"role": "system", "content": build_agent_system(profile, with_profile=with_profile, today=date.today().isoformat())},
        *history,
        {"role": "user", "content": message},
    ]

    # 第一段：文本增量即时上屏；首个完整工具调用即中断循环（后续增量不再消费）
    text_parts: list[str] = []
    call: ToolCallDelta | None = None
    stream = client.stream_tool_chat(config, messages, _tools_payload(intent))
    try:
        for item in stream:
            if isinstance(item, TextDelta):
                text_parts.append(item.text)
                yield SSE.delta(item.text)
                continue
            call = item
            break
    finally:
        stream.close()  # 幂等：正常耗尽的生成器再关无副作用；中断时释放上游连接

    if call is None:  # 纯文本回复（闲聊 / 直接回答）
        return _finish(db, user_id=user_id, conv=conv, message=message, entries=[
            _entry(MessageRole.ASSISTANT, "".join(text_parts)),
        ])

    spec = TOOLS.get(call.tool_name)
    args = _parse_args(call.arguments)
    if spec is None or args is None:  # 未知工具 / 参数 JSON 不可解析 → 降级追问
        return (yield from _followup(db, user_id=user_id, conv=conv, message=message,
                                     text_parts=text_parts, note=AGENT_FOLLOWUP_UNKNOWN))

    if spec.kind == "write":
        complete, followup = _prepare_write_call(db, user_id=user_id, spec=spec, args=args)
        if complete is None:
            return (yield from _followup(db, user_id=user_id, conv=conv, message=message,
                                         text_parts=text_parts, note=followup))
        # 确认卡片：参数以服务端补全后的为准；不执行、不落库（用户确认后走 execute 端点）
        yield SSE.tool_call(spec.name, complete)
        return _finish(db, user_id=user_id, conv=conv, message=message, entries=[
            _entry(MessageRole.ASSISTANT, "".join(text_parts), tool_name=spec.name,
                   tool_args=json.dumps(complete, ensure_ascii=False)),
        ])

    # 查询类：参数不全先追问；否则直接执行并把结果回灌 LLM 流式总结
    missing = _missing_fields(spec, args)
    if missing:
        return (yield from _followup(db, user_id=user_id, conv=conv, message=message,
                                     text_parts=text_parts,
                                     note=build_agent_followup(spec.label, missing)))

    data = spec.handler(db, user_id, args)
    data_text = json.dumps(data, ensure_ascii=False)
    summary_messages = [
        *messages,
        {"role": "assistant", "content": "".join(text_parts) or _QUERY_BRIDGE},
        {"role": "user", "content": build_agent_result_note(spec.label, data_text)},
    ]
    summary_parts: list[str] = []
    for piece in client.stream_chat(config, summary_messages):
        summary_parts.append(piece)
        yield SSE.delta(piece)
    # 结构化结果块：一次性 JSON、节奏豁免（utils/sse.py 的 result 段），前端据此渲染卡片/跳转
    yield SSE.delta(json.dumps({"type": spec.name, "data": data}, ensure_ascii=False), section="result")
    return _finish(db, user_id=user_id, conv=conv, message=message, entries=[
        _entry(MessageRole.TOOL, data_text, tool_name=spec.name),
        _entry(MessageRole.ASSISTANT, "".join(text_parts) + "".join(summary_parts), tool_name=spec.name),
    ])


def _followup(
    db: Session, *, user_id: int, conv: AgentConversation | None, message: str,
    text_parts: list[str], note: str,
) -> Iterator[str]:
    """降级追问：把追问文案以普通 delta 下发并落库（不报错、不出卡片），done 载荷随返回值透传。"""
    yield SSE.delta(note)
    return _finish(
        db, user_id=user_id, conv=conv, message=message,
        entries=[_entry(MessageRole.ASSISTANT, "".join(text_parts) + note)],
    )


# ---------- 落库 ----------


def _finish(
    db: Session, *, user_id: int, conv: AgentConversation | None, message: str, entries: list[dict]
) -> dict:
    """本轮落库（流正常结束才调用）：会话缺则新建、写用户消息与各条目，返回 done 载荷。

    `record_id` 取本轮最后一条消息 id（接口文档 3.11：`agent_message.id`）；
    新会话在此才创建——失败 / 断连场景不走本函数，零残留（系统设计 5.2）。
    """
    now = datetime.now()
    if conv is None:
        conv = AgentConversation(user_id=user_id, title=_make_title(message))
        db.add(conv)
        db.flush()  # 取会话 id
    db.add(AgentMessage(conversation_id=conv.id, role=MessageRole.USER.value, content=message))
    record_id: int | None = None
    for entry in entries:
        row = AgentMessage(conversation_id=conv.id, **entry)
        db.add(row)
        db.flush()
        record_id = row.id
    conv.updated_at = now  # 只加消息不 UPDATE 会话行时 onupdate 不触发，手动刷新列表排序依据
    db.commit()
    return {"record_id": record_id, "conversation_id": conv.id}


def _entry(
    role: MessageRole, content: str, *, tool_name: str | None = None, tool_args: str | None = None
) -> dict:
    """构造一条待落库消息（键与 AgentMessage 列一一对应）。"""
    return {"role": role.value, "content": content, "tool_name": tool_name, "tool_args": tool_args}


def _make_title(message: str) -> str:
    """会话标题：取首条用户输入前 30 字（不调模型，避免为取标题多花一次请求）。"""
    return " ".join(message.split())[:30] or "新对话"


def _history_messages(db: Session, conversation_id: int) -> list[dict]:
    """取最近 10 轮（USER + ASSISTANT）转 LLM 上下文。

    TOOL 行不进上下文——工具结果已在紧随的助手回复里被消化，重复投喂只会挤占窗口；
    单条截断 400 字（系统设计 5.2「超长截断」）。
    """
    rows = db.scalars(
        select(AgentMessage)
        .where(
            AgentMessage.conversation_id == conversation_id,
            AgentMessage.role.in_((MessageRole.USER.value, MessageRole.ASSISTANT.value)),
        )
        .order_by(AgentMessage.id.desc())
        .limit(_HISTORY_TURNS * 2)
    ).all()
    history: list[dict] = []
    for row in reversed(rows):
        content = (row.content or "").strip()
        if content:
            history.append({"role": row.role.lower(), "content": content[:_HISTORY_ITEM_LIMIT]})
    return history


# ---------- 写操作参数预处理与辅助 ----------


def _prepare_write_call(
    db: Session, *, user_id: int, spec: ToolSpec, args: dict
) -> tuple[dict | None, str | None]:
    """写操作参数预处理：返回 `(完整参数, None)` 或 `(None, 追问文案)`。

    能做就做、缺什么问什么：`update_application_status` 缺 `application_id` 时按公司名
    在本账号投递里模糊匹配最近一条（模型从对话里通常只拿到公司名）；
    转 `CLOSED` 缺 `close_reason` 也要问——否则确认卡片点下去才报错，体验更差。
    """
    if spec.name == "create_application":
        missing = _missing_fields(spec, args)
        if missing:
            return None, build_agent_followup(spec.label, missing)
        complete: dict = {
            "company": str(args["company"]).strip(),
            "position": str(args["position"]).strip(),
        }
        for field in ("city", "applied_at", "channel", "jd_text"):
            if value := _clean_optional(args.get(field)):
                complete[field] = value
        return complete, None

    if spec.name != "update_application_status":
        return None, AGENT_FOLLOWUP_UNKNOWN

    status = _as_status(args.get("status"))
    if status is None:
        return None, build_agent_followup(spec.label, ["目标状态"])
    application_id = _as_int(args.get("application_id"))
    if application_id is None:
        company = _clean_optional(args.get("company"))
        if not company:
            return None, build_agent_followup(spec.label, ["公司名称或投递记录 id"])
        application_id = _match_application_id(db, user_id, company)
        if application_id is None:
            return None, f"没找到「{company}」的投递记录，确认下公司名，或到投递管理页核对后再说一声～"
    complete = {"application_id": application_id, "status": status.value}
    if status == ApplicationStatus.CLOSED:
        close_reason = _as_close_reason(args.get("close_reason"))
        if close_reason is None:
            return None, "标记为已结束需要说一下原因：未通过 / 主动放弃 / 无消息，麻烦补一下～"
        complete["close_reason"] = close_reason.value
    if remark := _clean_optional(args.get("remark")):
        complete["remark"] = remark
    return complete, None


def _match_application_id(db: Session, user_id: int, company: str) -> int | None:
    """按公司名模糊匹配本账号最近一条投递（模型只报公司名时用于自动定位）。"""
    return db.scalar(
        select(Application.id)
        .where(Application.user_id == user_id, Application.company.like(f"%{company.strip()}%"))
        .order_by(Application.id.desc())
        .limit(1)
    )


_CLOSE_REASON_BY_LABEL: dict[str, CloseReason] = {
    label: reason for reason, label in application_service.CLOSE_REASON_LABELS.items()
}


def _as_status(value: object) -> ApplicationStatus | None:
    """目标状态宽转：英文枚举值（忽略大小写 / 空白）与中文标签都收（模型偶尔回中文）。"""
    status = _as_enum(value, ApplicationStatus)
    if status is not None:
        return status
    return application_service.STATUS_BY_LABEL.get(str(value).strip() if value is not None else "")


def _as_close_reason(value: object) -> CloseReason | None:
    """结束原因宽转：口径同 `_as_status`。"""
    reason = _as_enum(value, CloseReason)
    if reason is not None:
        return reason
    return _CLOSE_REASON_BY_LABEL.get(str(value).strip() if value is not None else "")


def _missing_fields(spec: ToolSpec, args: dict) -> list[str]:
    """必填参数检查：返回缺失字段的中文名列表（空列表 = 齐全）。"""
    return [label for field, label in spec.required if not str(args.get(field) or "").strip()]


def _parse_args(raw: str) -> dict | None:
    """解析工具调用参数 JSON：空串按无参处理，坏 JSON / 非对象 → None（走降级追问）。"""
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _as_enum(value: object, enum_cls):
    """宽松转枚举：去空白、忽略大小写；空值或非法值返回 None（由调用方决定追问 / 报错）。"""
    text = str(value).strip().upper() if value is not None else ""
    if not text:
        return None
    try:
        return enum_cls(text)
    except ValueError:
        return None


def _as_int(value: object) -> int | None:
    """宽松取整：模型可能给字符串数字；取不到返回 None。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clamp_int(value: object, *, default: int, lo: int, hi: int) -> int:
    """宽松取整并夹到区间：非法 / 缺失取默认值，越界夹取（模型给 100 个也不打爆）。"""
    number = _as_int(value)
    if number is None:
        return default
    return max(lo, min(hi, number))


def _clean_optional(value: object) -> str | None:
    """可选文本：去首尾空白，空串归 None（不把空白写进库）。"""
    text = str(value).strip() if value is not None else ""
    return text or None


def _parse_date(value: object) -> date | None:
    """解析 `YYYY-MM-DD`；解析不了返回 None（服务层按当天处理）。"""
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
