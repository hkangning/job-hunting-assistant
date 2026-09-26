"""设置业务：账号级偏好与系统级抓取配置的读写（接口文档 3.12，数据库设计 3.14）。

两级配置同存 `config` 表：账号级行按登录账号读写，系统级行固定 `user_id=0`（任一账号修改即全局生效）。
LLM 供应商相关字段已全部迁出（见 `llm_provider_service`）。
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import ACCOUNT_CONFIG, SYSTEM_CONFIG, SYSTEM_USER_ID
from app.models import Config
from app.schemas.system import SettingsDTO, SettingsUpdateRequest
from app.utils.security import encrypt_text

ACCOUNT_BOOL_KEYS = ("tts_enabled", "voice_enabled", "guide_done")  # 账号级布尔键
ASR_CREDENTIAL_KEYS = ("asr_app_id", "asr_api_key")  # 讯飞凭据键（**加密存**，传空串不修改）


def get_settings(db: Session, user_id: int) -> SettingsDTO:
    """读取设置：账号级键按当前账号取、系统级键取 `user_id=0` 行；缺失键按默认值兜底（老库兼容）。"""
    account = _load(db, user_id)
    system = _load(db, SYSTEM_USER_ID)
    return SettingsDTO(
        tts_enabled=_as_bool(account.get("tts_enabled", ACCOUNT_CONFIG["tts_enabled"])),
        voice_enabled=_as_bool(account.get("voice_enabled", ACCOUNT_CONFIG["voice_enabled"])),
        default_question_count=int(
            account.get("default_question_count", ACCOUNT_CONFIG["default_question_count"])
        ),
        asr_provider=account.get("asr_provider", ACCOUNT_CONFIG["asr_provider"]),
        tts_voice=account.get("tts_voice", ACCOUNT_CONFIG["tts_voice"]),
        asr_key_set=bool(account.get("asr_api_key")),
        guide_done=_as_bool(account.get("guide_done", ACCOUNT_CONFIG["guide_done"])),
        crawl_enabled=_as_bool(system.get("crawl_enabled", SYSTEM_CONFIG["crawl_enabled"])),
    )


def update_settings(db: Session, user_id: int, payload: SettingsUpdateRequest) -> SettingsDTO:
    """更新设置（PUT /settings）：**只处理请求体中显式传入的字段**，未传的保持原值。

    讯飞凭据（`asr_app_id` / `asr_api_key`）传值则以 Fernet 加密后覆盖，传空串不修改。
    """
    values = payload.model_dump(exclude_unset=True)

    for key in ACCOUNT_BOOL_KEYS:
        if values.get(key) is not None:
            _set(db, user_id, key, "true" if values[key] else "false")
    if values.get("default_question_count") is not None:
        _set(db, user_id, "default_question_count", str(values["default_question_count"]))
    if values.get("asr_provider") is not None:
        _set(db, user_id, "asr_provider", values["asr_provider"])
    if values.get("tts_voice") is not None:
        _set(db, user_id, "tts_voice", values["tts_voice"])

    if values.get("crawl_enabled") is not None:  # 系统级：任一账号修改全局生效
        _set(db, SYSTEM_USER_ID, "crawl_enabled", "true" if values["crawl_enabled"] else "false")

    for key in ASR_CREDENTIAL_KEYS:
        raw = (values.get(key) or "").strip()
        if raw:  # 空串 = 不修改（接口文档 3.12）
            _set(db, user_id, key, encrypt_text(raw))

    db.commit()
    return get_settings(db, user_id)


# ---------- 内部工具 ----------


def _load(db: Session, user_id: int) -> dict[str, str]:
    """取某个 user_id 下的全部配置键值（value 为空的行跳过，走默认值兜底）。"""
    rows = db.scalars(select(Config).where(Config.user_id == user_id)).all()
    return {row.key: row.value for row in rows if row.value is not None}


def _set(db: Session, user_id: int, key: str, value: str) -> None:
    """按 (user_id, key) upsert 一行配置。"""
    row = db.get(Config, (user_id, key))
    if row is None:
        db.add(Config(user_id=user_id, key=key, value=value, updated_at=datetime.now()))
    else:
        row.value = value
        row.updated_at = datetime.now()


def _as_bool(value: str) -> bool:
    """文本开关 → 布尔（仅 `true` 视为真，其余按假处理）。"""
    return str(value).strip().lower() == "true"
