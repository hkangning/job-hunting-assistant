"""数据库引擎与会话：MySQL 8.0（InnoDB，连接池探活/回收，数据库设计文档 §1），并提供一键初始化。"""

import json
import logging
from collections.abc import Generator
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

SEED_FILE = Path(__file__).resolve().parent.parent / "seed" / "questions.json"

logger = logging.getLogger(__name__)

# 系统级数据的账号标识（数据库设计 §3.14）：不建外键，全站共用。
# `config` 的系统默认项与 `llm_provider_config` 的平台共享配置（免费模型 Key）都用它。
SYSTEM_USER_ID = 0

# config 表默认配置项：键名与接口文档 GET /settings 响应字段一一对应，值统一以文本存储
# 系统级（user_id=0）在建表时插入；账号级在注册时按账号插入（见 init_account_data）
SYSTEM_CONFIG: dict[str, str] = {
    "crawl_enabled": "false",
}

ACCOUNT_CONFIG: dict[str, str] = {
    "tts_enabled": "false",
    "voice_enabled": "false",
    "default_question_count": "8",
    "asr_provider": "funasr",
    "tts_voice": "zh-CN-XiaoxiaoNeural",
    "guide_done": "false",
}


class Base(DeclarativeBase):
    """全部 ORM 模型的声明基类。"""


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # 取连接前探活，防 MySQL 空闲断连（wait_timeout）
    pool_recycle=3600,  # 连接最长复用 1 小时，早于 MySQL 默认 wait_timeout
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """SQLite 专用：每个新连接开启 WAL 与外键（SQLite 外键默认关闭，且为连接级设置）。

    MySQL/InnoDB 原生支持事务与外键，无需此步。保留该分支是为了让测试库迁移与代码
    换库解耦——测试侧迁移完成前，SQLite 测试库仍有外键强制保护（数据库切换设计 3.1）。
    """
    if engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每请求一个会话，请求结束关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> int:
    """一键初始化：建表 + 初始行 + 种子题库幂等导入（由 main.lifespan 调用）；返回种子新增题数。"""
    from app import models  # noqa: F401  导入以注册全部模型到 Base.metadata

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        _init_default_rows(db)
        _sync_shared_providers(db)
        added = _load_seed_questions(db)
        db.commit()
    return added


def _init_default_rows(db: Session) -> None:
    """插入系统级 config 默认项（user_id=0），已存在则跳过；账号级配置与画像在注册时按账号建。"""
    from app.models import Config

    for key, value in SYSTEM_CONFIG.items():
        if db.get(Config, (SYSTEM_USER_ID, key)) is None:
            db.add(
                Config(user_id=SYSTEM_USER_ID, key=key, value=value, updated_at=datetime.now())
            )


def _sync_shared_providers(db: Session) -> None:
    """把 .env 的平台共享 Key（`SHARED_KEY_<供应商标识>`）同步进 `user_id=0` 的平台配置行。

    **以 .env 为准**：配了的 upsert（Key 重新加密、模型取注册表默认值），没配的删除平台行。
    标识不在注册表内的跳过并记警告，不中断启动。
    """
    from app.clients import llm_provider as registry
    from app.models import LlmProviderConfig
    from app.utils.security import encrypt_text

    shared = settings.shared_provider_keys()
    existing = {
        row.provider: row
        for row in db.scalars(
            select(LlmProviderConfig).where(LlmProviderConfig.user_id == SYSTEM_USER_ID)
        ).all()
    }
    for provider, api_key in shared.items():
        meta = registry.get_provider(provider)
        if meta is None:
            logger.warning("SHARED_KEY_%s 的供应商不在注册表中，已跳过", provider.upper())
            continue
        row = existing.pop(provider, None)
        if row is None:
            row = LlmProviderConfig(user_id=SYSTEM_USER_ID, provider=provider)
            db.add(row)
        row.api_key = encrypt_text(api_key)
        row.base_url = None  # 端点用注册表默认值
        row.model = meta.default_model
        row.updated_at = datetime.now()
    for row in existing.values():  # .env 里已移除的供应商：对应平台行一并删除
        db.delete(row)


def init_account_data(db: Session, user_id: int) -> None:
    """注册时为新账号预置数据：一条空画像 + 账号级 config 默认项（数据库设计 §4），幂等。"""
    from app.models import Config, UserProfile

    if db.scalar(select(UserProfile).where(UserProfile.user_id == user_id)) is None:
        db.add(UserProfile(user_id=user_id, updated_at=datetime.now()))

    for key, value in ACCOUNT_CONFIG.items():
        if db.get(Config, (user_id, key)) is None:
            db.add(Config(user_id=user_id, key=key, value=value, updated_at=datetime.now()))


def _load_seed_questions(db: Session) -> int:
    """种子题库 upsert（以题干 content 为匹配键），返回新增题数（数据库设计 §4）。

    内置题的五项分类字段（stack / direction / answer / qtype / rubric）以种子文件为准原地
    回填；AI 生成题不归种子文件管，题干撞车也不覆盖。不做物理删除——wrong_question 与
    practice_record 的外键指向 question.id，删题会破坏用户错题本与陪练历史。
    """
    from app.models import Direction, Question, QuestionSource, QuestionType, Stack

    if not SEED_FILE.exists():
        return 0

    items = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    existing = {q.content: q for q in db.scalars(select(Question)).all()}
    added = 0
    for item in items:
        stack = Stack(item.get("stack", Stack.COMMON))
        direction = Direction(item["direction"])
        qtype = QuestionType(item.get("qtype", QuestionType.SUBJECTIVE))
        rubric_obj = item.get("rubric")  # 种子文件里是嵌套对象，入库转 JSON 字符串
        rubric = json.dumps(rubric_obj, ensure_ascii=False) if rubric_obj else None
        question = existing.get(item["content"])
        if question is None:
            question = Question(
                stack=stack,
                direction=direction,
                content=item["content"],
                answer=item["answer"],
                rubric=rubric,
                qtype=qtype,
                source=QuestionSource.BUILTIN,
                created_at=datetime.now(),
            )
            db.add(question)
            existing[item["content"]] = question
            added += 1
        elif question.source == QuestionSource.BUILTIN:
            question.stack = stack
            question.direction = direction
            question.answer = item["answer"]
            question.qtype = qtype
            question.rubric = rubric
    return added
