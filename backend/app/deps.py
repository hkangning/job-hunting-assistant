"""FastAPI 依赖：从请求头解析当前登录账号（系统设计 3.5）。

受保护端点一律声明 `current_user: User = Depends(get_current_user)`，把 `current_user.id` 传给服务层；
**绝不接受请求体 / 查询参数里的 user_id**（系统设计 3.6）。
"""

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.database import get_db
from app.exceptions import BizException, ErrorCode
from app.models import User
from app.utils.security import decode_token, password_version

BEARER_PREFIX = "Bearer "


def get_current_user(
    authorization: str | None = Header(default=None, description="Bearer <token>（登录/注册接口返回）"),
    db: Session = Depends(get_db),
) -> User:
    """校验 Token 并返回当前账号对象。

    缺失 / 格式错 / 验签失败 → 401 + 80001；过期 → 401 + 80002；账号不存在或密码已改（旧 Token）→ 401。
    """
    if not authorization or not authorization.startswith(BEARER_PREFIX):
        raise BizException(ErrorCode.UNAUTHORIZED)
    payload = decode_token(authorization[len(BEARER_PREFIX) :].strip())

    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError) as exc:
        raise BizException(ErrorCode.UNAUTHORIZED) from exc

    user = db.get(User, user_id)
    if user is None:
        raise BizException(ErrorCode.UNAUTHORIZED)
    if payload.get("pwd_ver") != password_version(user.password_changed_at):
        raise BizException(ErrorCode.TOKEN_EXPIRED, "密码已修改，请重新登录")
    return user
