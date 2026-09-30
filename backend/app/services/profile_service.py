"""用户画像业务：每账号一份，JD 分析与 Agent 记忆的输入（FR-012，系统设计 3.6）。"""

import json
import logging
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UserProfile
from app.schemas.system import ProfileDTO, ProfileExperience

logger = logging.getLogger(__name__)

# 画像业务字段（不含 id / user_id / updated_at）：PUT 时按此白名单更新，请求体里的其他键一律忽略
PROFILE_FIELDS = (
    "name",
    "school",
    "major",
    "degree",
    "gpa",
    "english_level",
    "experiences",
    "target_position",
    "target_city",
    "skills",
    "weaknesses",
    "note",
)


def get_profile(db: Session, user_id: int) -> ProfileDTO:
    """取当前账号画像（GET /profile）：记录缺失时补建（注册流程已建，此处兜底老库数据）。"""
    return _to_dto(_get_or_create(db, user_id))


def update_profile(db: Session, user_id: int, values: dict) -> ProfileDTO:
    """更新画像（PUT /profile）：仅更新传入的字段，未传保持原值、显式传 null 即清空。

    经历条目以 JSON 数组落库（数据库设计 3.15）：空数组与 null 等价，都落 NULL（即清空）。
    """
    profile = _get_or_create(db, user_id)
    if "experiences" in values:
        values["experiences"] = _dump_experiences(values["experiences"])
    for field in PROFILE_FIELDS:
        if field in values:
            setattr(profile, field, values[field])
    profile.updated_at = datetime.now()
    db.commit()
    db.refresh(profile)
    return _to_dto(profile)


def _get_or_create(db: Session, user_id: int) -> UserProfile:
    """按账号取画像；不存在则补建空记录（每账号唯一，数据库设计 3.15）。"""
    profile = db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    if profile is None:
        profile = UserProfile(user_id=user_id, updated_at=datetime.now())
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def _dump_experiences(items: list[dict] | None) -> str | None:
    """经历条目列表 → 落库 JSON 字符串；空列表 / null 落 NULL（清空）。"""
    if not items:
        return None
    return json.dumps(items, ensure_ascii=False)


def _load_experiences(raw: str | None) -> list[ProfileExperience] | None:
    """落库 JSON 字符串 → DTO 经历条目；脏数据（解析失败 / 元素不合规）跳过，不因历史脏值打挂画像接口。"""
    if not raw:
        return None
    try:
        items = json.loads(raw)
    except ValueError:
        logger.warning("画像经历 JSON 解析失败，按未填写处理")
        return None
    if not isinstance(items, list):
        return None
    loaded: list[ProfileExperience] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            loaded.append(ProfileExperience(**item))
        except ValidationError:
            continue
    return loaded or None


def _to_dto(profile: UserProfile) -> ProfileDTO:
    """ORM → 画像 DTO（经历条目由落库 JSON 反序列化）。"""
    values = {field: getattr(profile, field) for field in PROFILE_FIELDS}
    values["experiences"] = _load_experiences(profile.experiences)
    return ProfileDTO(**values, updated_at=profile.updated_at)
