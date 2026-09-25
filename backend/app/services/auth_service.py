"""账号与鉴权业务：注册/登录/账号信息/改资料/改密码/头像（FR-016、FR-017，系统设计 3.5）。

分层规则（系统设计 3.1）：本层负责业务逻辑与事务边界，出口一律为 schemas 层 DTO。
"""

import math
import re
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import init_account_data
from app.exceptions import BizException, ErrorCode
from app.models import LlmProviderConfig, User
from app.models.enums import UserPlan, UserRole
from app.schemas.auth import (
    AuthData,
    AvatarData,
    LoginRequest,
    PasswordUpdateRequest,
    ProfileUpdateRequest,
    RegisterRequest,
    UserBrief,
    UserInfo,
)
from app.utils.security import (
    create_token,
    delete_avatar_file,
    hash_password,
    password_version,
    save_avatar,
    verify_password,
)

PASSWORD_MIN_LENGTH = 6  # 密码最短长度（接口文档 3.2）
MAX_LOGIN_FAILURES = 5  # 连续失败达此次数即锁定
LOCK_MINUTES = 5  # 锁定时长（分钟）
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")  # 邮箱格式，应用层校验（数据库设计 3.16：email 无库层唯一约束）
OLLAMA_PROVIDER = "ollama"  # 本地部署无需 Key，有激活行即视为已配置


# ---------- 注册与登录 ----------


def register(db: Session, payload: RegisterRequest) -> AuthData:
    """注册并自动登录：查重 → 建账号 → 建画像与账号级配置 → 签发 1 天 Token（接口文档 3.2）。"""
    _validate_password(payload.password)
    _ensure_username_free(db, payload.username)
    email = _normalize_email(db, payload.email)
    now = datetime.now()

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        nickname=(payload.nickname or "").strip() or payload.username,
        email=email,
        # 首个注册账号为管理员（本期无权限差异，预留）
        role=UserRole.ADMIN if _is_first_account(db) else UserRole.USER,
        plan=UserPlan.FREE,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    db.flush()  # 先取到 user.id，再建该账号的画像与账号级配置
    init_account_data(db, user.id)
    db.commit()
    db.refresh(user)

    token, expires_at = create_token(
        user.id, user.username, remember_me=False, pwd_ver=password_version(user.password_changed_at)
    )
    return AuthData(token=token, expires_at=expires_at, user=_to_brief(user))


def login(db: Session, payload: LoginRequest) -> AuthData:
    """登录：锁定校验 → 验密 → 清失败计数 → 按 remember_me 签发 Token（接口文档 3.2）。"""
    now = datetime.now()
    user = _find_by_username(db, payload.username)
    if user is not None and user.locked_until and user.locked_until > now:
        raise BizException(ErrorCode.ACCOUNT_LOCKED, _locked_message(user.locked_until, now))
    if user is None or not verify_password(payload.password, user.password_hash):
        if user is not None:
            _record_login_failure(db, user, now)
        raise BizException(ErrorCode.LOGIN_FAILED)  # 统一文案，不区分账号是否存在（防枚举）

    user.login_fail_count = 0
    user.locked_until = None
    user.last_login_at = now
    user.updated_at = now
    db.commit()
    db.refresh(user)

    token, expires_at = create_token(
        user.id,
        user.username,
        remember_me=payload.remember_me,
        pwd_ver=password_version(user.password_changed_at),
    )
    return AuthData(token=token, expires_at=expires_at, user=_to_brief(user))


# ---------- 账号信息 ----------


def get_account(db: Session, user: User) -> UserInfo:
    """当前账号信息（GET /auth/me，前端启动校验 Token 是否有效的入口）。"""
    return _to_info(db, user)


def update_account(db: Session, user: User, payload: ProfileUpdateRequest) -> UserInfo:
    """修改昵称/邮箱（PUT /auth/profile）：用户名不可改；未提交的字段保持原值。"""
    if "nickname" in payload.model_fields_set:
        user.nickname = (payload.nickname or "").strip() or user.username
    if "email" in payload.model_fields_set:
        user.email = _normalize_email(db, payload.email, user_id=user.id)
    user.updated_at = datetime.now()
    db.commit()
    db.refresh(user)
    return _to_info(db, user)


def change_password(db: Session, user: User, payload: PasswordUpdateRequest) -> None:
    """修改密码（PUT /auth/password）：校验原密码 → 更新哈希与改密时间 → 旧 Token 全部作废。"""
    if not verify_password(payload.old_password, user.password_hash):
        raise BizException(ErrorCode.OLD_PASSWORD_WRONG)
    _validate_password(payload.new_password)
    now = datetime.now()
    user.password_hash = hash_password(payload.new_password)
    user.password_changed_at = now  # get_current_user 据此把旧 Token（含 30 天免登录）判失效
    user.updated_at = now
    db.commit()


# ---------- 头像 ----------


def upload_avatar(db: Session, user: User, *, filename: str, content: bytes) -> AvatarData:
    """上传头像（POST /auth/avatar）：校验并落盘新文件 → 更新库 → 删除旧文件。"""
    old_avatar = user.avatar
    relative_path = save_avatar(user.id, filename, content)  # 校验失败抛 10001，此时原头像不动
    user.avatar = relative_path
    user.updated_at = datetime.now()
    db.commit()
    db.refresh(user)
    delete_avatar_file(old_avatar)
    return AvatarData(avatar=user.avatar)


def reset_avatar(db: Session, user: User) -> AvatarData:
    """恢复默认头像（DELETE /auth/avatar）：删除自定义文件并把字段置空。"""
    old_avatar = user.avatar
    user.avatar = None
    user.updated_at = datetime.now()
    db.commit()
    delete_avatar_file(old_avatar)
    return AvatarData(avatar=None)


# ---------- 内部工具 ----------


def _validate_password(password: str) -> None:
    """密码强度：≥6 位，不强制字符类型（接口文档 3.2）。"""
    if len(password or "") < PASSWORD_MIN_LENGTH:
        raise BizException(ErrorCode.PASSWORD_WEAK)


def _find_by_username(db: Session, username: str) -> User | None:
    """按登录名查账号，**不区分大小写**（接口文档 3.2）；库层 UNIQUE 区分大小写，故用 lower 比对。"""
    return db.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))


def _ensure_username_free(db: Session, username: str) -> None:
    if _find_by_username(db, username) is not None:
        raise BizException(ErrorCode.USERNAME_EXISTS)


def _normalize_email(db: Session, email: str | None, *, user_id: int | None = None) -> str | None:
    """邮箱规范化与查重：空值/空串视为未填；格式非法 10001；被其他账号占用 10003。"""
    value = (email or "").strip()
    if not value:
        return None
    if not EMAIL_PATTERN.match(value):
        raise BizException(ErrorCode.PARAM_INVALID, "邮箱格式不正确")
    conditions = [func.lower(User.email) == value.lower()]
    if user_id is not None:
        conditions.append(User.id != user_id)
    if db.scalar(select(User).where(*conditions)) is not None:
        raise BizException(ErrorCode.CONFLICT, "该邮箱已被其他账号使用")
    return value


def _record_login_failure(db: Session, user: User, now: datetime) -> None:
    """累计失败次数，达上限写入锁定截止时间。

    上一轮锁定已过期时先把计数清零：否则解锁后第一次失败就再次触发锁定。
    """
    if user.locked_until is not None and user.locked_until <= now:
        user.login_fail_count = 0
        user.locked_until = None
    user.login_fail_count += 1
    if user.login_fail_count >= MAX_LOGIN_FAILURES:
        user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
    user.updated_at = now
    db.commit()


def _locked_message(locked_until: datetime, now: datetime) -> str:
    """锁定提示带剩余时间（接口文档 3.2：message 含剩余锁定时间，前端做倒计时）。"""
    remain = max(1, math.ceil((locked_until - now).total_seconds() / 60))
    return f"账号已锁定，请 {remain} 分钟后重试"


def _is_first_account(db: Session) -> bool:
    """是否尚无任何账号：首个注册账号为 ADMIN（接口文档 3.2）。"""
    return (db.scalar(select(func.count()).select_from(User)) or 0) == 0


def _llm_configured(db: Session, user_id: int) -> bool:
    """是否已有生效的 AI 供应商配置：存在激活行且（本地 ollama 或已填 Key）（FR-018）。"""
    row = db.scalar(
        select(LlmProviderConfig).where(
            LlmProviderConfig.user_id == user_id, LlmProviderConfig.is_active == 1
        )
    )
    return row is not None and (row.provider == OLLAMA_PROVIDER or bool(row.api_key))


def _to_brief(user: User) -> UserBrief:
    """ORM → 账号简要信息 DTO（注册/登录响应用）。"""
    return UserBrief(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        avatar=user.avatar,
        role=user.role,
        plan=user.plan,
        created_at=user.created_at,
    )


def _to_info(db: Session, user: User) -> UserInfo:
    """ORM → 账号完整信息 DTO（含邮箱、上次登录时间与 AI 配置状态）。"""
    return UserInfo(
        **_to_brief(user).model_dump(),
        email=user.email,
        last_login_at=user.last_login_at,
        llm_configured=_llm_configured(db, user.id),
    )
