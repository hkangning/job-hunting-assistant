"""面经整理：面经 CRUD、条目检索与结构化提取（接口文档 3.10；FR-008）。

面经分两步入库：先存原文（不调 AI），再由用户触发一次流式提取把原文拆成问答条目。
提取口径（系统设计 5.3）：LLM 输出 `{"items":[{question, answer_points}]}` 一次性 JSON，
**提取即替换**——同事务清掉该面经旧条目再插新条目并更新冗余计数，重试 / 重复提取不翻倍；
流正常结束才落库，断连或中途失败不落库（原文仍在，重试即重新提取）。
"""

import json
import logging
from collections.abc import Iterator

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.clients.llm_client import LLMClient, parse_json_block, resolve_config
from app.exceptions import BizException, ErrorCode
from app.models import Experience, ExperienceItem
from app.models.enums import ExperienceItemSource
from app.prompts import build_experience_extract_messages
from app.schemas.common import PageData
from app.schemas.experience import (
    ExperienceCreateRequest,
    ExperienceDTO,
    ExperienceItemDTO,
    ExperienceItemSearchItem,
    ExperienceListItem,
)
from app.utils.sse import SSE

logger = logging.getLogger(__name__)

MAX_ITEMS = 50  # 单篇面经条目硬上限（超出截尾）；prompt 侧引导模型最多 30 条
MAX_QUESTION_LEN = 2000  # 题干长度上限，超长截断
MAX_ANSWER_LEN = 5000  # 回答要点长度上限，超长截断

_ITEM_KEY = '"question"'  # 进度计数识别的条目键名
_PROGRESS_TAIL = len(_ITEM_KEY) - 1  # 跨块边界的键名尾巴：留不足一个键的长度，既拼得回又不重复计数


# ---------- 面经 CRUD ----------


def create_experience(
    db: Session, *, user_id: int, payload: ExperienceCreateRequest
) -> ExperienceDTO:
    """新增面经：只存原文、不触发提取（提取走 /stream/experience-extract）。"""
    experience = Experience(
        user_id=user_id,
        company=_clean_optional(payload.company),
        position=_clean_optional(payload.position),
        source=_clean_optional(payload.source),
        original_text=payload.original_text,
        item_count=0,
    )
    db.add(experience)
    db.commit()
    db.refresh(experience)
    return _to_dto(experience, [])


def list_experiences(
    db: Session, *, user_id: int, page: int, page_size: int
) -> PageData[ExperienceListItem]:
    """面经列表（不含原文，列表精简）：创建时间倒序，同秒按 id 倒序。"""
    total = db.execute(
        select(func.count()).select_from(Experience).where(Experience.user_id == user_id)
    ).scalar_one()
    rows = (
        db.execute(
            select(Experience)
            .where(Experience.user_id == user_id)
            .order_by(Experience.created_at.desc(), Experience.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return PageData(total=total, items=[_to_list_item(row) for row in rows])


def get_experience(db: Session, *, user_id: int, experience_id: int) -> ExperienceDTO:
    """面经详情：原文全文 + 结构化条目（按 id 升序即提取顺序）。"""
    experience = _get_owned(db, user_id, experience_id)
    items = _load_items(db, experience.id)
    return _to_dto(experience, items)


def delete_experience(db: Session, *, user_id: int, experience_id: int) -> None:
    """删除面经：条目无级联外键，先清条目再删主记录（同事务）。"""
    experience = _get_owned(db, user_id, experience_id)
    db.execute(delete(ExperienceItem).where(ExperienceItem.experience_id == experience.id))
    db.delete(experience)
    db.commit()


def search_items(
    db: Session, *, user_id: int, keyword: str, page: int, page_size: int
) -> PageData[ExperienceItemSearchItem]:
    """条目检索：按题干模糊匹配本账号全部面经，`company` 联表带出（接口文档 3.10）。

    keyword 只含空白视同未填 → 10001（避免全表命中）。
    """
    keyword = keyword.strip()
    if not keyword:
        raise BizException(ErrorCode.PARAM_INVALID, "检索关键词不能为空")
    conditions = [Experience.user_id == user_id, ExperienceItem.question.like(f"%{keyword}%")]
    total = db.execute(
        select(func.count())
        .select_from(ExperienceItem)
        .join(Experience, Experience.id == ExperienceItem.experience_id)
        .where(*conditions)
    ).scalar_one()
    rows = db.execute(
        select(ExperienceItem, Experience.company)
        .join(Experience, Experience.id == ExperienceItem.experience_id)
        .where(*conditions)
        .order_by(ExperienceItem.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return PageData(
        total=total,
        items=[
            ExperienceItemSearchItem(
                id=item.id,
                experience_id=item.experience_id,
                company=company,
                question=item.question,
                answer_points=item.answer_points,
            )
            for item, company in rows
        ],
    )


# ---------- 结构化提取（SSE）----------


def ensure_extractable(db: Session, *, user_id: int, experience_id: int) -> Experience:
    """提取前校验（在 SSE 建立之前执行，接口文档 3.10）：面经不存在 / 不属当前账号 → 404 + 10002。"""
    return _get_owned(db, user_id, experience_id)


def run_extract(
    db: Session, *, user_id: int, experience_id: int, client: LLMClient
) -> Iterator[str]:
    """面经结构化提取（业务生成器）：`yield` SSE 事件、`return` done 载荷（接口文档 3.10）。

    事件流：`start → delta(section=progress)×N → done`。进度 delta 是**整句状态文案**
    （`逐步` 覆盖式渲染，不能拆碎，故该段在协议层豁免输出节奏器）；模型原文全程不外发。
    条目**提取即替换**：流正常结束后同事务清旧插新并更新 `item_count`；断连或中途失败
    直接上抛（`GeneratorExit` 穿过本函数、commit 不执行）——原文仍在，重试即重新提取。
    解析失败、条目为空、提取条数为 0 一律报 40002；LLM 调用失败沿用四档错误码（10010~10012）。
    """
    experience = _get_owned(db, user_id, experience_id)
    config = resolve_config(db, user_id)
    messages = build_experience_extract_messages(experience.original_text)

    yield SSE.delta("正在阅读原文…", "progress")
    counter = _ProgressCounter()
    chunks: list[str] = []
    for chunk in client.stream_chat(config, messages):
        chunks.append(chunk)
        if counter.feed(chunk) > counter.reported:
            counter.reported = counter.count
            yield SSE.delta(f"已提炼 {counter.count} 条…", "progress")

    items = _parse_items("".join(chunks))
    if not items:
        raise BizException(
            ErrorCode.EXPERIENCE_EXTRACT_FAILED,
            "未能从原文中提取到问答条目，请确认原文包含面试问答内容",
        )
    rows = _replace_items(db, experience, items)
    db.commit()
    extra = {
        "items": [
            {"id": row.id, "question": row.question, "answer_points": row.answer_points}
            for row in rows
        ]
    }
    return {"record_id": experience.id, "extra": extra}


class _ProgressCounter:
    """统计模型输出里条目键的出现次数（「已提炼 N 条…」进度文案用）。

    只留 `键长 - 1` 个字符的尾巴参与下一块匹配：跨块边界的关键字能拼回来，又不重复计数。
    模型不按约定格式输出时计数停滞，进度只剩首条「正在阅读原文…」——静默降级，不影响主流程。
    """

    def __init__(self) -> None:
        self.count = 0  # 当前累计识别到的条目键数
        self.reported = 0  # 已下发过的计数（仅增长时下发进度）
        self._tail = ""

    def feed(self, chunk: str) -> int:
        text = self._tail + chunk
        self.count += text.count(_ITEM_KEY)
        self._tail = text[-_PROGRESS_TAIL:]
        return self.count


def _parse_items(raw: str) -> list[dict]:
    """模型输出原文 → 合法条目列表（容错解析 → 逐条校验 → 截断上限）。

    `{"items":[...]}` 对象包裹（复用 `parse_json_block` 的围栏 / 前后文字容错）；
    题干非字符串、去空白后为空、条目不是对象的**单独丢弃**，一条不剩由调用方报 40002。
    题干与回答要点超长截断（不丢弃——截断仍可用，丢弃等于白花 token）。
    """
    if not raw.strip():
        logger.info("面经提取：模型未输出任何内容")
        return []
    try:
        payload = parse_json_block(raw)
    except ValueError:
        logger.info("面经提取：模型输出不是可解析的 JSON 对象")
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        logger.info("面经提取：模型输出缺少 items 数组")
        return []
    result: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        question = item.get("question")
        if not isinstance(question, str) or not question.strip():
            continue
        answer = item.get("answer_points")
        answer = answer.strip() if isinstance(answer, str) else ""
        result.append(
            {
                "question": question.strip()[:MAX_QUESTION_LEN],
                "answer_points": answer[:MAX_ANSWER_LEN] or None,
            }
        )
        if len(result) >= MAX_ITEMS:
            break
    return result


def _replace_items(db: Session, experience: Experience, items: list[dict]) -> list[ExperienceItem]:
    """提取即替换：同事务清旧插新、更新冗余计数，重复提取不翻倍（接口文档 3.10）。"""
    db.execute(delete(ExperienceItem).where(ExperienceItem.experience_id == experience.id))
    rows = [
        ExperienceItem(
            experience_id=experience.id,
            question=item["question"],
            answer_points=item["answer_points"],
            source_type=ExperienceItemSource.LLM_EXTRACT,
        )
        for item in items
    ]
    db.add_all(rows)
    experience.item_count = len(rows)
    db.flush()
    return rows


# ---------- 内部工具 ----------


def _get_owned(db: Session, user_id: int, experience_id: int) -> Experience:
    """取本账号的面经；不存在与越权同码（404 + 10002），与既有不可区分口径一致。"""
    experience = db.get(Experience, experience_id)
    if experience is None or experience.user_id != user_id:
        raise BizException(ErrorCode.NOT_FOUND, "面经不存在")
    return experience


def _load_items(db: Session, experience_id: int) -> list[ExperienceItem]:
    """面经下的条目，按 id 升序（即提取顺序）。"""
    return (
        db.execute(
            select(ExperienceItem)
            .where(ExperienceItem.experience_id == experience_id)
            .order_by(ExperienceItem.id)
        )
        .scalars()
        .all()
    )


def _clean_optional(value: str | None) -> str | None:
    """可选的短文本字段：去空白，空串存 null。"""
    if value is None:
        return None
    return value.strip() or None


def _to_list_item(row: Experience) -> ExperienceListItem:
    return ExperienceListItem(
        id=row.id,
        company=row.company,
        position=row.position,
        source=row.source,
        item_count=row.item_count,
        created_at=row.created_at,
    )


def _to_item_dto(row: ExperienceItem) -> ExperienceItemDTO:
    return ExperienceItemDTO(
        id=row.id,
        question=row.question,
        answer_points=row.answer_points,
        source_type=row.source_type,
    )


def _to_dto(row: Experience, items: list[ExperienceItem]) -> ExperienceDTO:
    return ExperienceDTO(
        id=row.id,
        company=row.company,
        position=row.position,
        source=row.source,
        original_text=row.original_text,
        item_count=row.item_count,
        created_at=row.created_at,
        items=[_to_item_dto(item) for item in items],
    )
