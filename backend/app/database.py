"""数据库引擎与会话：SQLite 单文件 + WAL 模式 + 外键开启（数据库设计文档 §1），并提供一键初始化。"""

import json
from collections.abc import Generator
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

SEED_FILE = Path(__file__).resolve().parent.parent / "seed" / "questions.json"

# config 表默认配置项：键名与接口文档 GET /settings 响应字段一一对应，值统一以文本存储
DEFAULT_CONFIG: dict[str, str] = {
    "llm_provider": "deepseek",
    "llm_model": "deepseek-flash",
    "llm_base_url": "",
    "tts_enabled": "false",
    "voice_enabled": "false",
    "crawl_enabled": "false",
    "crawl_url": "",
    "default_question_count": "8",
}


class Base(DeclarativeBase):
    """全部 ORM 模型的声明基类。"""


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # SQLite 连接跨线程使用（FastAPI 线程池）
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """每个新连接都开启外键（SQLite 默认关闭，连接级设置）。"""
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


def init_db() -> None:
    """一键初始化：建表 + 初始行 + 种子题库幂等导入（由 main.lifespan 调用）。"""
    from app import models  # noqa: F401  导入以注册全部模型到 Base.metadata

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        _init_default_rows(db)
        _load_seed_questions(db)
        db.commit()


def _init_default_rows(db: Session) -> None:
    """插入 user_profile 空记录（id=1）与 config 默认项，已存在则跳过。"""
    from app.models import Config, UserProfile

    if db.get(UserProfile, 1) is None:
        db.add(UserProfile(id=1, updated_at=datetime.now()))

    for key, value in DEFAULT_CONFIG.items():
        if db.get(Config, key) is None:
            db.add(Config(key=key, value=value, updated_at=datetime.now()))


def _load_seed_questions(db: Session) -> int:
    """幂等导入种子题库：按题干 content 去重，返回新增题数（数据库设计 §4）。"""
    from app.models import Direction, Question, QuestionSource, QuestionType

    if not SEED_FILE.exists():
        return 0

    items = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    existing = set(db.scalars(select(Question.content)).all())
    added = 0
    for item in items:
        if item["content"] in existing:
            continue
        db.add(
            Question(
                direction=Direction(item["direction"]),
                content=item["content"],
                answer=item["answer"],
                qtype=QuestionType(item.get("qtype", QuestionType.SUBJECTIVE)),
                source=QuestionSource.BUILTIN,
                created_at=datetime.now(),
            )
        )
        existing.add(item["content"])
        added += 1
    return added
