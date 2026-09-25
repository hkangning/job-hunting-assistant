"""安全工具：JWT 签发与校验、bcrypt 密码哈希、Fernet 对称加解密、头像校验与落盘（系统设计 3.5 / 6）。"""

import base64
import hashlib
import uuid
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken
from PIL import Image, UnidentifiedImageError

from app.config import settings
from app.exceptions import BizException, ErrorCode

JWT_ALGORITHM = "HS256"  # 对称签名算法（系统设计 3.5）
TOKEN_DAYS_REMEMBER = 30  # 勾选「30 天免登录」的有效期
TOKEN_DAYS_DEFAULT = 1  # 未勾选时的有效期

AVATAR_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "avatars"  # backend/uploads/avatars
AVATAR_MAX_BYTES = 2 * 1024 * 1024  # 上传体积上限 2MB（接口文档 3.2）
AVATAR_SIZE = 256  # 头像边长（前端已压缩，后端兜底再缩一次）
AVATAR_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}  # 允许的图片格式


# ---------- JWT ----------


def create_token(user_id: int, username: str, *, remember_me: bool, pwd_ver: int) -> tuple[str, datetime]:
    """签发 JWT，返回 (token, 过期时间)。

    `pwd_ver` 为签发时刻的密码版本（`password_changed_at` 的秒级时间戳，无则 0）；改密后版本变化，
    旧 Token 全部作废。用版本号而非直接比 `iat`，是为了避免登录与改密发生在同一秒时判定失效。
    """
    now = datetime.now()
    expires_at = now + timedelta(days=TOKEN_DAYS_REMEMBER if remember_me else TOKEN_DAYS_DEFAULT)
    payload = {
        "sub": str(user_id),  # 账号 id
        "username": username,
        "iat": int(now.timestamp()),  # 签发时间
        "exp": int(expires_at.timestamp()),  # 过期时间
        "pwd_ver": pwd_ver,  # 密码版本（改密后作废旧 Token）
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm=JWT_ALGORITHM), expires_at


def decode_token(token: str) -> dict:
    """校验签名与有效期：过期抛 80002，其余无效抛 80001（两者前端处理一致）。"""
    try:
        return jwt.decode(token, settings.app_secret_key, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise BizException(ErrorCode.TOKEN_EXPIRED) from exc
    except jwt.PyJWTError as exc:
        raise BizException(ErrorCode.UNAUTHORIZED) from exc


def password_version(changed_at: datetime | None) -> int:
    """密码版本号 = 密码修改时间的秒级时间戳；从未改密为 0。"""
    return int(changed_at.timestamp()) if changed_at else 0


# ---------- 密码 ----------


def _prepare(password: str) -> bytes:
    """bcrypt 只接受 ≤72 字节，先做 sha256 摘要再送哈希：支持任意长度密码且不损失强度。"""
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(plain: str) -> str:
    """生成 bcrypt 哈希串（自带盐值），明文永不落库、不打日志（系统设计 3.5）。"""
    return bcrypt.hashpw(_prepare(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验密码是否匹配哈希串；哈希串损坏等异常一律按不匹配处理。"""
    try:
        return bcrypt.checkpw(_prepare(plain), hashed.encode("utf-8"))
    except ValueError:
        return False


# ---------- Fernet 对称加密（供应商 API Key 落库，步骤 6 使用）----------


def _fernet() -> Fernet:
    """由 APP_SECRET_KEY 派生 Fernet 密钥（32 字节 urlsafe base64）。"""
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(settings.app_secret_key.encode()).digest()))


def encrypt_text(plain: str) -> str:
    """加密敏感文本（如 API Key），返回可入库的密文串。"""
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_text(cipher: str) -> str:
    """解密；密钥变更或密文损坏时抛 10012（重新配置 Key 即可）。"""
    try:
        return _fernet().decrypt(cipher.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise BizException(ErrorCode.LLM_KEY_MISSING, "密钥解析失败，请重新配置") from exc


# ---------- 头像文件 ----------


def save_avatar(user_id: int, filename: str, content: bytes) -> str:
    """校验并落盘头像，返回相对路径（形如 `uploads/avatars/1_a3f9c2d1.png`）。

    校验类型与体积（接口文档 3.2）；服务端重命名，不使用用户原始文件名（系统设计 6 路径穿越防护）。
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in AVATAR_SUFFIXES:
        raise BizException(ErrorCode.PARAM_INVALID, "头像仅支持 jpg / jpeg / png / webp 格式")
    if not content:
        raise BizException(ErrorCode.PARAM_INVALID, "头像文件为空")
    if len(content) > AVATAR_MAX_BYTES:
        raise BizException(ErrorCode.PARAM_INVALID, "头像文件不能超过 2MB")

    try:
        image = Image.open(BytesIO(content))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise BizException(ErrorCode.PARAM_INVALID, "头像文件无法识别，请换一张图片") from exc

    if max(image.size) > AVATAR_SIZE:  # 只缩不放：前端已压到 256，此处兜底
        image.thumbnail((AVATAR_SIZE, AVATAR_SIZE))
    if suffix in {".jpg", ".jpeg"} and image.mode not in ("RGB", "L"):
        image = image.convert("RGB")  # JPEG 不支持透明通道

    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{user_id}_{uuid.uuid4().hex[:8]}{suffix}"
    image.save(AVATAR_DIR / name)
    return f"uploads/avatars/{name}"


def delete_avatar_file(relative_path: str | None) -> None:
    """删除头像文件；仅取路径末段拼接，防路径穿越；文件不存在时静默忽略。"""
    if not relative_path:
        return
    (AVATAR_DIR / Path(relative_path).name).unlink(missing_ok=True)
