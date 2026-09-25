"""账号与鉴权测试：TC-52~54（auth_service 服务层）+ TC-58~60（API 集成）。

依据：测试计划 v1.8 TC-52~60 / 接口文档 v1.6 §1.1·§3.2 / SRS v1.9 FR-016·FR-017。
隔离口径（跨账号一律 404 + 10002、不接受请求体传入的 user_id）见系统设计 §3.6。
"""

import io
from datetime import datetime, timedelta
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from app.config import settings
from app.exceptions import BizException, ErrorCode
from app.models import Config, User, UserProfile
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services import auth_service
from app.utils.security import JWT_ALGORITHM, decode_token, verify_password

API = "/api/v1"
PASSWORD = "test123456"


def _register(db, username: str = "tester", password: str = PASSWORD, **kwargs):
    """服务层注册（TC-52~54 直调 auth_service）。"""
    return auth_service.register(db, RegisterRequest(username=username, password=password, **kwargs))


def _png(size=(300, 300), color=(61, 142, 99)) -> bytes:
    """造一张真实 PNG（Pillow 生成，供头像用例使用）。"""
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture()
def avatar_dir(tmp_path, monkeypatch):
    """把头像落盘目录改到临时目录，避免用例往 backend/uploads/ 写文件。"""
    from app.utils import security

    target = tmp_path / "avatars"
    monkeypatch.setattr(security, "AVATAR_DIR", target)
    return target


# ---------- TC-52 注册 ----------


def test_register_first_account_is_admin(db_session):
    """TC-52：首个注册账号 role=ADMIN，其余为 USER（本期无权限差异，字段口径须正确）。"""
    assert _register(db_session, "first_user").user.role == "ADMIN"
    assert _register(db_session, "second_user").user.role == "USER"


def test_register_username_unique_case_insensitive(db_session):
    """TC-52：用户名全站唯一；大小写变体同样视为重名（80003）。"""
    _register(db_session, "ZhangSan")

    with pytest.raises(BizException) as exc:
        _register(db_session, "zhangsan")
    assert exc.value.code == ErrorCode.USERNAME_EXISTS


@pytest.mark.parametrize("bad", ["ab", "a" * 21, "has space", "has-dash", "中文用户名", ""])
def test_register_username_format_rejected(client: TestClient, bad: str):
    """TC-52：用户名须 3~20 位且仅字母/数字/下划线，否则 10001。

    该约束在 DTO 层（`RegisterRequest.username` 的 pattern/length），故走 HTTP 验对外行为。
    """
    resp = client.post(f"{API}/auth/register", json={"username": bad, "password": PASSWORD})
    assert resp.status_code == 400
    assert resp.json()["code"] == 10001


def test_register_password_stored_as_bcrypt(db_session):
    """TC-52：密码 ≥6 位（不足 80006）；以 bcrypt 哈希落库，明文不出现。"""
    with pytest.raises(BizException) as exc:
        _register(db_session, "weak_pwd", password="12345")
    assert exc.value.code == ErrorCode.PASSWORD_WEAK

    data = _register(db_session, "strong_pwd", password="secret123")
    row = db_session.get(User, data.user.id)
    assert "secret123" not in row.password_hash
    assert row.password_hash.startswith("$2")  # bcrypt 哈希串前缀
    assert verify_password("secret123", row.password_hash)
    assert not verify_password("secret124", row.password_hash)


def test_register_provisions_profile_and_account_config(db_session):
    """TC-52：注册时预置该账号的 user_profile 与账号级 config 默认项。"""
    user_id = _register(db_session, "provisioned").user.id

    profiles = db_session.scalars(select(UserProfile).where(UserProfile.user_id == user_id)).all()
    assert len(profiles) == 1 and profiles[0].name is None

    keys = set(db_session.scalars(select(Config.key).where(Config.user_id == user_id)).all())
    assert keys == {"tts_enabled", "voice_enabled", "default_question_count",
                    "asr_provider", "tts_voice", "guide_done"}


# ---------- TC-53 登录 ----------


def test_login_issues_jwt_with_user_id(db_session):
    """TC-53：凭证正确签发 JWT，载荷含 user_id（sub）与密码版本（pwd_ver）。"""
    data = _register(db_session, "login_ok")
    result = auth_service.login(db_session, LoginRequest(username="login_ok", password=PASSWORD))

    payload = decode_token(result.token)
    assert payload["sub"] == str(data.user.id)
    assert payload["username"] == "login_ok"
    assert payload["pwd_ver"] == 0  # 从未改密
    assert result.expires_at > datetime.now()


def test_login_failure_message_indistinguishable(db_session):
    """TC-53：用户名不存在与密码错误返回同一错误码与文案（防用户名枚举）。"""
    _register(db_session, "enum_user")

    with pytest.raises(BizException) as wrong_pwd:
        auth_service.login(db_session, LoginRequest(username="enum_user", password="wrong_pass"))
    with pytest.raises(BizException) as no_user:
        auth_service.login(db_session, LoginRequest(username="ghost_user", password=PASSWORD))

    assert wrong_pwd.value.code == no_user.value.code == ErrorCode.LOGIN_FAILED
    assert wrong_pwd.value.message == no_user.value.message


def test_login_lockout_and_recovery(db_session):
    """TC-53：连续失败 5 次锁定 5 分钟；锁定期内密码正确亦拒（80005）；解锁后成功且计数清零。"""
    _register(db_session, "lock_user")

    for attempt in range(5):
        with pytest.raises(BizException) as exc:
            auth_service.login(db_session, LoginRequest(username="lock_user", password="wrong_pass"))
        assert exc.value.code == ErrorCode.LOGIN_FAILED, f"第 {attempt + 1} 次失败应为 80004"

    with pytest.raises(BizException) as locked:
        auth_service.login(db_session, LoginRequest(username="lock_user", password=PASSWORD))
    assert locked.value.code == ErrorCode.ACCOUNT_LOCKED
    assert "分钟" in locked.value.message  # 文案带剩余锁定时间，前端据此倒计时

    # 模拟锁定到期：把 locked_until 拨到过去
    user = db_session.scalar(select(User).where(User.username == "lock_user"))
    user.locked_until = datetime.now() - timedelta(seconds=1)
    db_session.commit()

    result = auth_service.login(db_session, LoginRequest(username="lock_user", password=PASSWORD))
    assert result.token
    db_session.refresh(user)
    assert user.login_fail_count == 0, "成功登录应清零失败计数"
    assert user.locked_until is None


# ---------- TC-54 免登录有效期与改密作废 ----------


def test_token_ttl_follows_remember_me(db_session):
    """TC-54：勾选「30 天免登录」签发 30 天 Token；不勾选为 1 天。"""
    _register(db_session, "ttl_user")

    normal = auth_service.login(db_session, LoginRequest(username="ttl_user", password=PASSWORD))
    remembered = auth_service.login(
        db_session, LoginRequest(username="ttl_user", password=PASSWORD, remember_me=True)
    )

    days = lambda result: round((result.expires_at - datetime.now()).total_seconds() / 86400)
    assert days(normal) == 1
    assert days(remembered) == 30


def test_password_change_invalidates_old_tokens(client: TestClient, account):
    """TC-54：改密需验原密码（错误 80007）；成功后此前签发的 Token 全部作废。"""
    # 原密码错误 → 80007
    wrong = client.put(
        f"{API}/auth/password", json={"old_password": "wrong_old", "new_password": "newpass123"}
    )
    assert wrong.json()["code"] == 80007

    # 新密码不足 6 位 → 80006
    short = client.put(
        f"{API}/auth/password", json={"old_password": account["password"], "new_password": "123"}
    )
    assert short.json()["code"] == 80006

    # 正确改密
    ok = client.put(
        f"{API}/auth/password", json={"old_password": account["password"], "new_password": "newpass123"}
    )
    assert ok.json()["code"] == 0

    # 旧 Token 立即失效（含 30 天免登录签发的长有效期 Token）
    stale = client.get(f"{API}/auth/me", headers=account["headers"])
    assert stale.status_code == 401
    assert stale.json()["code"] == 80002

    # 旧密码被拒、新密码可登录
    assert client.post(
        f"{API}/auth/login", json={"username": account["username"], "password": account["password"]}
    ).json()["code"] == 80004
    assert client.post(
        f"{API}/auth/login", json={"username": account["username"], "password": "newpass123"}
    ).json()["code"] == 0


# ---------- TC-58 鉴权拦截 ----------


def test_whitelist_endpoints_skip_auth(anon_client):
    """TC-58：白名单三端点免鉴权——/health、/auth/register、/auth/login。"""
    assert anon_client.get(f"{API}/health").json()["code"] == 0
    assert anon_client.post(
        f"{API}/auth/register", json={"username": "whitelist_user", "password": PASSWORD}
    ).json()["code"] == 0
    assert anon_client.post(
        f"{API}/auth/login", json={"username": "whitelist_user", "password": PASSWORD}
    ).json()["code"] == 0


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/applications"),
        ("post", "/applications"),
        ("get", "/applications/trend"),
        ("get", "/profile"),
        ("put", "/profile"),
        ("get", "/auth/me"),
        ("get", "/applications/template"),
    ],
)
def test_business_endpoints_require_token(anon_client, method: str, path: str):
    """TC-58：未带 Token 访问业务接口（含下载类端点）→ 401 + 80001。"""
    resp = getattr(anon_client, method)(f"{API}{path}", **({"json": {}} if method != "get" else {}))
    assert resp.status_code == 401, f"{method} {path}"
    assert resp.json()["code"] == 80001


def test_invalid_and_expired_token_rejected(client, account):
    """TC-58：Token 无效 → 80001；已过期 → 80002（两者前端处理一致，但错误码须可区分）。"""
    ghost = client.get(f"{API}/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert ghost.status_code == 401 and ghost.json()["code"] == 80001

    malformed = client.get(f"{API}/auth/me", headers={"Authorization": "no-bearer-prefix"})
    assert malformed.json()["code"] == 80001

    now = datetime.now()
    expired = jwt.encode(
        {
            "sub": str(account["id"]),
            "username": account["username"],
            "iat": int((now - timedelta(days=2)).timestamp()),
            "exp": int((now - timedelta(days=1)).timestamp()),
            "pwd_ver": 0,
        },
        settings.app_secret_key,
        algorithm=JWT_ALGORITHM,
    )
    stale = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert stale.status_code == 401 and stale.json()["code"] == 80002


def test_body_user_id_is_ignored(client, account, make_account):
    """TC-58：归属只认 Token——请求体里传入的 user_id 一律被忽略（系统设计 §3.6）。"""
    other = make_account("other_user")

    created = client.post(
        f"{API}/applications",
        json={"company": "浩鲸科技", "position": "Java 开发", "user_id": other["id"]},
    )
    assert created.json()["code"] == 0
    app_id = created.json()["data"]["id"]

    # 记录归属 A（传进来的 B 的 user_id 未生效）
    assert client.get(f"{API}/applications/{app_id}", headers=account["headers"]).json()["code"] == 0
    assert client.get(f"{API}/applications/{app_id}", headers=other["headers"]).json()["code"] == 10002


# ---------- TC-59 跨账号数据隔离 ----------


def test_cross_account_access_returns_404(client, account, make_account):
    """TC-59：A 创建的投递，B 用自己的 Token 查/改/流转/删一律 404 + 10002；A 的列表不含 B 的。"""
    other = make_account("other_user")
    app_id = client.post(
        f"{API}/applications", json={"company": "云器科技", "position": "后端开发"}
    ).json()["data"]["id"]

    attempts = [
        ("get", f"/applications/{app_id}", None),
        ("put", f"/applications/{app_id}", {"company": "篡改", "position": "篡改"}),
        ("patch", f"/applications/{app_id}/status", {"status": "WRITTEN"}),
        ("delete", f"/applications/{app_id}", None),
    ]
    for method, path, body in attempts:
        resp = getattr(client, method)(
            f"{API}{path}", headers=other["headers"], **({"json": body} if body else {})
        )
        assert resp.status_code == 404, f"{method} {path} 应返回 404"
        assert resp.json()["code"] == 10002

    # 越权响应与"真不存在"完全一致，不暴露资源是否存在
    ghost = client.get(f"{API}/applications/999999", headers=other["headers"]).json()
    stolen = client.get(f"{API}/applications/{app_id}", headers=other["headers"]).json()
    assert ghost == stolen

    # 各自的列表互不可见
    assert client.get(f"{API}/applications", headers=account["headers"]).json()["data"]["total"] == 1
    assert client.get(f"{API}/applications", headers=other["headers"]).json()["data"]["total"] == 0


def test_cross_account_isolation_profile(client, account, make_account):
    """TC-59：画像按账号隔离——每账号一份，互不覆盖、互不可见。

    （`/settings` 与 AI 配置接口分别属步骤 6/8，届时在同一用例组内补测。）
    """
    other = make_account("other_user")

    client.put(f"{API}/profile", json={"name": "账号A", "skills": "Java,Redis"})

    mine = client.get(f"{API}/profile", headers=account["headers"]).json()["data"]
    theirs = client.get(f"{API}/profile", headers=other["headers"]).json()["data"]
    assert (mine["name"], mine["skills"]) == ("账号A", "Java,Redis")
    assert (theirs["name"], theirs["skills"]) == (None, None)


# ---------- TC-60 头像上传 ----------


def test_avatar_upload_replace_and_reset(client: TestClient, avatar_dir: Path):
    """TC-60：上传返回相对路径且落盘；换头像清理旧文件；恢复默认删除文件并置空。"""
    first = client.post(f"{API}/auth/avatar", files={"file": ("a.png", _png(), "image/png")}).json()
    assert first["code"] == 0
    first_file = avatar_dir / Path(first["data"]["avatar"]).name
    assert first["data"]["avatar"].startswith("uploads/avatars/")
    assert first_file.exists()

    second = client.post(
        f"{API}/auth/avatar", files={"file": ("b.png", _png((120, 120)), "image/png")}
    ).json()
    second_file = avatar_dir / Path(second["data"]["avatar"]).name
    assert second_file.exists()
    assert not first_file.exists(), "换头像应清理旧文件"

    reset = client.delete(f"{API}/auth/avatar").json()
    assert reset["data"]["avatar"] is None
    assert not second_file.exists(), "恢复默认应删除自定义头像文件"


@pytest.mark.parametrize(
    ("filename", "content", "mime"),
    [
        pytest.param("a.gif", b"GIF89a", "image/gif", id="bad-type"),  # 类型不在白名单
        pytest.param("a.png", b"x" * (2 * 1024 * 1024 + 1), "image/png", id="oversize"),  # 超 2MB
        pytest.param("a.png", b"not an image at all", "image/png", id="not-an-image"),  # 后缀合法但非图片
    ],
)
def test_avatar_validation_rejects_invalid(client: TestClient, filename, content, mime):
    """TC-60：类型、体积与真实性校验不合格一律 10001。"""
    resp = client.post(f"{API}/auth/avatar", files={"file": (filename, content, mime)})
    assert resp.json()["code"] == 10001


def test_avatar_downscaled_to_256(client: TestClient, avatar_dir: Path):
    """TC-60：超 256 的图等比缩至最长边 256（只缩不放）。"""
    uploaded = client.post(
        f"{API}/auth/avatar", files={"file": ("big.png", _png((800, 600)), "image/png")}
    ).json()
    with Image.open(avatar_dir / Path(uploaded["data"]["avatar"]).name) as image:
        assert max(image.size) == 256
