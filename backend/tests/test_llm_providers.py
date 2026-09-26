"""TC-47~49、TC-55、TC-56、TC-61：AI 供应商配置（步骤 6，FR-018 / 接口文档 v1.10 §3.3）。

**打桩方式**：`list_models` / `test_connection` 是 `app/clients/llm_provider.py` 的**模块级函数**
——该模块是步骤 6 交付的「13 家注册表 + 探测函数」，**无抽象基类**（抽象 `LLMProvider` 与
`get_llm_provider` 注入点属步骤 10 的 `llm_client`），故用 monkeypatch 替换这两个函数本身，
用例全程不触网（测试计划 §1.3）。

**账号归属**：步骤 6 的 8 个端点全部挂 `get_current_user`，请求体不接受 `user_id`；
服务层用例经 `account_id` 取账号，API 用例经 `client`（出厂即带鉴权头）或 `make_account` 取第二个。
"""

import pytest
from fastapi.testclient import TestClient

from app.clients import llm_provider as registry
from app.clients.llm_provider import ModelMeta, ProviderAuthError, ProviderProbeError
from app.exceptions import BizException, ErrorCode
from app.models import LlmProviderConfig
from app.schemas.llm_provider import ProviderSaveRequest
from app.services import llm_provider_service
from app.utils.security import decrypt_text

API = "/api/v1"

# 用例统一使用的供应商（deepseek 需 Key、有内置模型表；ollama 无需 Key；custom 端点为必填）
NEEDS_KEY = "deepseek"
NO_KEY = "ollama"
CUSTOM = "custom"

PLAINTEXT_KEY = "sk-test-1234567890"


# ---------- 打桩 ----------


class FakeLLM:
    """注册表探测函数的内存替身：记录调用、返回预设结果或抛预设异常（不触网）。"""

    def __init__(self) -> None:
        self.list_calls: list[tuple] = []
        self.test_calls: list[tuple] = []
        self.models: list[ModelMeta] = [ModelMeta("fake-model-a", "假模型 A", is_free=True)]
        self.models_error: Exception | None = None
        self.test_model = "fake-model-a"
        self.test_error: Exception | None = None

    def list_models(self, provider: str, base_url: str, api_key: str | None) -> list[ModelMeta]:
        self.list_calls.append((provider, base_url, api_key))
        if self.models_error is not None:
            raise self.models_error
        return list(self.models)

    def test_connection(self, provider: str, base_url: str, api_key: str | None, model: str | None = None) -> str:
        self.test_calls.append((provider, base_url, api_key, model))
        if self.test_error is not None:
            raise self.test_error
        return self.test_model


@pytest.fixture()
def fake_llm(monkeypatch) -> FakeLLM:
    fake = FakeLLM()
    monkeypatch.setattr(registry, "list_models", fake.list_models)
    monkeypatch.setattr(registry, "test_connection", fake.test_connection)
    return fake


def _save(db, user_id: int, provider: str, **kwargs):
    """服务层保存配置的简写。"""
    return llm_provider_service.save_provider(db, user_id, provider, ProviderSaveRequest(**kwargs))


def _row(db, user_id: int, provider: str) -> LlmProviderConfig | None:
    return llm_provider_service._get_row(db, user_id, provider)


def _row_count(client: TestClient) -> int:
    """当前账号在 llm_provider_config 表中的行数（经服务层读，避免直接摸库）。"""
    from app.database import SessionLocal

    with SessionLocal() as session:
        return len(
            session.query(LlmProviderConfig).filter_by(user_id=client.auth_account["id"]).all()
        )


# ---------- TC-55 供应商配置 CRUD ----------


def test_save_first_config_encrypts_key_and_auto_activates(db_session, account_id):
    """TC-55：Key 以 Fernet **密文**落库；账号尚无激活行时，首个保存的供应商**自动生效**。"""
    item = _save(db_session, account_id, NEEDS_KEY, api_key=PLAINTEXT_KEY)

    row = _row(db_session, account_id, NEEDS_KEY)
    assert row.api_key != PLAINTEXT_KEY  # 明文不落库
    assert decrypt_text(row.api_key) == PLAINTEXT_KEY  # 但可解回原文
    assert row.is_active == 1  # 首个配置自动激活
    assert item.key_set is True
    assert item.is_active is True


def test_save_repeated_is_update_not_duplicate(db_session, account_id):
    """TC-55：每账号每供应商一行，重复保存走更新（不产生第二行）。"""
    _save(db_session, account_id, NEEDS_KEY, api_key=PLAINTEXT_KEY)
    _save(db_session, account_id, NEEDS_KEY, model="fake-model-b")

    rows = db_session.query(LlmProviderConfig).filter_by(user_id=account_id, provider=NEEDS_KEY).all()
    assert len(rows) == 1
    assert rows[0].model == "fake-model-b"


def test_save_omitted_key_keeps_stored_key(db_session, account_id):
    """TC-55：`api_key` 省略或留空 = **不修改**已存 Key（只改端点/模型不该把 Key 抹掉）。"""
    _save(db_session, account_id, NEEDS_KEY, api_key=PLAINTEXT_KEY)
    before = _row(db_session, account_id, NEEDS_KEY).api_key

    _save(db_session, account_id, NEEDS_KEY, model="fake-model-b")
    _save(db_session, account_id, NEEDS_KEY, api_key="")

    assert _row(db_session, account_id, NEEDS_KEY).api_key == before


def test_save_first_config_without_key_rejected(db_session, account_id):
    """TC-55：需 Key 的供应商首次配置未传 Key → 10001（`ollama` 本地模型不受此限）。"""
    with pytest.raises(BizException) as exc:
        _save(db_session, account_id, NEEDS_KEY)
    assert exc.value.code == ErrorCode.PARAM_INVALID

    assert _save(db_session, account_id, NO_KEY).key_set is False  # ollama 无需 Key


def test_save_empty_base_url_restores_registry_default(db_session, account_id):
    """接口文档 §3.3 PUT：`base_url` 传空串 = **恢复注册表默认**（不是存空串）。"""
    _save(db_session, account_id, NEEDS_KEY, api_key=PLAINTEXT_KEY, base_url="https://proxy.example.com")
    assert _row(db_session, account_id, NEEDS_KEY).base_url == "https://proxy.example.com"

    _save(db_session, account_id, NEEDS_KEY, base_url="")
    assert _row(db_session, account_id, NEEDS_KEY).base_url is None


def test_save_custom_without_base_url_rejected(db_session, account_id):
    """接口文档 §3.3 PUT：`custom` 未填端点 → 10001。"""
    with pytest.raises(BizException) as exc:
        _save(db_session, account_id, CUSTOM, api_key=PLAINTEXT_KEY)
    assert exc.value.code == ErrorCode.PARAM_INVALID


def test_save_unknown_provider_rejected(db_session, account_id):
    """接口文档 §3.3 PUT：`provider` 非法 → 10001。"""
    with pytest.raises(BizException) as exc:
        _save(db_session, account_id, "not-a-provider", api_key=PLAINTEXT_KEY)
    assert exc.value.code == ErrorCode.PARAM_INVALID


def test_save_does_not_change_active(db_session, account_id):
    """接口文档 §3.3 PUT：**保存不改变当前激活项**（激活只能走 activate 端点）。"""
    _save(db_session, account_id, NEEDS_KEY, api_key=PLAINTEXT_KEY)  # 自动激活
    _save(db_session, account_id, "zhipu", api_key=PLAINTEXT_KEY)  # 再存一个

    assert _row(db_session, account_id, NEEDS_KEY).is_active == 1
    assert _row(db_session, account_id, "zhipu").is_active == 0


def test_delete_removes_config_and_key(db_session, account_id):
    """TC-55：删除后配置与 Key **一并清空**。"""
    _save(db_session, account_id, NEEDS_KEY, api_key=PLAINTEXT_KEY)
    llm_provider_service.delete_provider(db_session, account_id, NEEDS_KEY)

    assert _row(db_session, account_id, NEEDS_KEY) is None
    assert llm_provider_service.list_providers(db_session, account_id).providers  # 注册表卡片仍在


def test_delete_unconfigured_provider_returns_not_found(db_session, account_id):
    """接口文档 §3.3 DELETE：该供应商尚未配置 → 10002。"""
    with pytest.raises(BizException) as exc:
        llm_provider_service.delete_provider(db_session, account_id, NEEDS_KEY)
    assert exc.value.code == ErrorCode.NOT_FOUND


def test_delete_active_provider_clears_active(client: TestClient):
    """接口文档 §3.3 DELETE：删除当前激活项后 `active` 变 null（AI 进入未配置态）。"""
    client.put(f"{API}/llm-providers/{NEEDS_KEY}", json={"api_key": PLAINTEXT_KEY})
    assert client.get(f"{API}/llm-providers").json()["data"]["active"] == NEEDS_KEY

    assert client.delete(f"{API}/llm-providers/{NEEDS_KEY}").status_code == 200
    assert client.get(f"{API}/llm-providers").json()["data"]["active"] is None


def test_list_returns_all_registry_providers(client: TestClient):
    """接口文档 §3.3 GET：返回注册表**全部 12 项**，未配置的也在列表中（供前端渲染卡片）。"""
    client.put(f"{API}/llm-providers/{NEEDS_KEY}", json={"api_key": PLAINTEXT_KEY})
    data = client.get(f"{API}/llm-providers").json()["data"]

    assert len(data["providers"]) == len(registry.PROVIDERS) == 13
    by_key = {item["provider"]: item for item in data["providers"]}
    assert by_key[NEEDS_KEY]["key_set"] is True
    assert by_key["zhipu"]["key_set"] is False  # 未配置
    assert by_key[NO_KEY]["key_set"] is False  # ollama 恒为 false
    assert by_key[NEEDS_KEY]["model"] == ""  # 未选模型 = 空串（非 null）
    assert set(by_key[NEEDS_KEY]["group"] for _ in [0]) <= {"国内", "国外", "聚合", "本地", "自定义"}


@pytest.mark.parametrize("provider", [NEEDS_KEY, NO_KEY, CUSTOM])
def test_key_never_echoed_in_any_response(client: TestClient, provider: str, fake_llm):
    """TC-55：**任何响应都不回显 Key 的明文或片段**（只回 `key_set` 布尔）。"""
    body = {"api_key": PLAINTEXT_KEY}
    if provider == CUSTOM:
        body["base_url"] = "https://custom.example.com/v1"
    client.put(f"{API}/llm-providers/{provider}", json=body)

    responses = [
        client.get(f"{API}/llm-providers"),
        client.get(f"{API}/llm-providers/{provider}/models"),
        client.post(f"{API}/llm-providers/test", json={"provider": provider}),
    ]
    for resp in responses:
        assert resp.status_code == 200
        assert PLAINTEXT_KEY not in resp.text
        assert PLAINTEXT_KEY[:8] not in resp.text  # 片段同样不得出现


# ---------- TC-56 激活互斥 ----------


def test_activate_is_exclusive_within_account(db_session, account_id):
    """TC-56：设为当前使用后，同账号其余供应商 `is_active=false`（同账号内**至多一行**生效）。"""
    _save(db_session, account_id, NEEDS_KEY, api_key=PLAINTEXT_KEY)
    _save(db_session, account_id, "zhipu", api_key=PLAINTEXT_KEY)

    result = llm_provider_service.activate_provider(db_session, account_id, "zhipu")

    assert result.active == "zhipu"
    assert _row(db_session, account_id, "zhipu").is_active == 1
    assert _row(db_session, account_id, NEEDS_KEY).is_active == 0
    assert llm_provider_service.list_providers(db_session, account_id).active == "zhipu"


def test_activate_requires_stored_key(db_session, account_id):
    """接口文档 §3.3 activate：该供应商尚未配置 Key（非 ollama）→ 10001。"""
    _save(db_session, account_id, NO_KEY)  # ollama 无需 Key，可激活
    assert llm_provider_service.activate_provider(db_session, account_id, NO_KEY).active == NO_KEY

    with pytest.raises(BizException) as exc:
        llm_provider_service.activate_provider(db_session, account_id, NEEDS_KEY)  # 未配置
    assert exc.value.code == ErrorCode.PARAM_INVALID


def test_activate_unknown_provider_rejected(db_session, account_id):
    """接口文档 §3.3 activate：`provider` 非法 → 10001。"""
    with pytest.raises(BizException) as exc:
        llm_provider_service.activate_provider(db_session, account_id, "not-a-provider")
    assert exc.value.code == ErrorCode.PARAM_INVALID


# ---------- TC-47 连通性测试（端点随步骤 6 迁至 /llm-providers/test） ----------


def test_test_endpoint_success_and_no_persist(client: TestClient, fake_llm):
    """TC-47：连通成功返回 ok 与实际模型名；**不落库、不保存配置**。"""
    resp = client.post(f"{API}/llm-providers/test", json={"provider": NEEDS_KEY, "api_key": PLAINTEXT_KEY})

    assert resp.status_code == 200
    assert resp.json()["data"] == {"message": "ok", "model": fake_llm.test_model}
    assert fake_llm.test_calls[0][0] == NEEDS_KEY and fake_llm.test_calls[0][2] == PLAINTEXT_KEY
    assert _row_count(client) == 0  # 未产生配置行


def test_test_endpoint_uses_stored_key_when_omitted(client: TestClient, fake_llm):
    """接口文档 §3.3 test：`api_key` 省略则用**当前账号已存 Key**。"""
    client.put(f"{API}/llm-providers/{NEEDS_KEY}", json={"api_key": PLAINTEXT_KEY})
    fake_llm.test_calls.clear()

    assert client.post(f"{API}/llm-providers/test", json={"provider": NEEDS_KEY}).status_code == 200
    assert fake_llm.test_calls[0][2] == PLAINTEXT_KEY  # 用的是库中已存的（已解密的）Key


def test_test_endpoint_failure_maps_10013(client: TestClient, fake_llm):
    """TC-47：连通失败 → **10013**，`message` 携带具体原因。"""
    fake_llm.test_error = ProviderProbeError("Key 无效")

    resp = client.post(f"{API}/llm-providers/test", json={"provider": NEEDS_KEY, "api_key": PLAINTEXT_KEY})

    assert resp.json()["code"] == 10013
    assert "Key 无效" in resp.json()["message"]


def test_test_endpoint_without_key_returns_10012(client: TestClient, fake_llm):
    """接口文档 §3.3 test：未配置 Key 且请求未传 → **10012**。"""
    resp = client.post(f"{API}/llm-providers/test", json={"provider": NEEDS_KEY})
    assert resp.json()["code"] == 10012


def test_test_endpoint_unknown_provider_returns_10001(client: TestClient, fake_llm):
    """接口文档 §3.3 test：`provider` 非法 → **10001**。"""
    resp = client.post(f"{API}/llm-providers/test", json={"provider": "not-a-provider"})
    assert resp.json()["code"] == 10001


# ---------- TC-49 模型列表：动态拉取、24h 缓存、失败回退内置表 ----------


def test_models_remote_fetch_writes_cache(db_session, account_id, fake_llm):
    """TC-49：拉取成功 `source=remote`、`fetched_at` 有值，并写入 `models_cache`。"""
    _save(db_session, account_id, NEEDS_KEY, api_key=PLAINTEXT_KEY)

    result = llm_provider_service.get_models(db_session, account_id, NEEDS_KEY)

    assert result.source == "remote"
    assert result.fetched_at is not None
    assert [m.id for m in result.models] == ["fake-model-a"]
    assert _row(db_session, account_id, NEEDS_KEY).models_cache is not None


def test_models_cache_hit_within_ttl(db_session, account_id, fake_llm):
    """TC-49：缓存 **24h 内不重拉**（第二次不再调用远端）。"""
    _save(db_session, account_id, NEEDS_KEY, api_key=PLAINTEXT_KEY)

    llm_provider_service.get_models(db_session, account_id, NEEDS_KEY)
    llm_provider_service.get_models(db_session, account_id, NEEDS_KEY)

    assert len(fake_llm.list_calls) == 1


def test_models_refresh_forces_refetch(db_session, account_id, fake_llm):
    """接口文档 §3.3 models：`refresh=true` 强制重拉，绕过 24h 缓存。"""
    _save(db_session, account_id, NEEDS_KEY, api_key=PLAINTEXT_KEY)

    llm_provider_service.get_models(db_session, account_id, NEEDS_KEY)
    llm_provider_service.get_models(db_session, account_id, NEEDS_KEY, refresh=True)

    assert len(fake_llm.list_calls) == 2


def test_models_key_change_invalidates_cache(db_session, account_id, fake_llm):
    """接口文档 §3.3 PUT：**传新 Key 时旧模型缓存一并作废**（否则换错 Key 仍命中缓存、测不出 10013）。"""
    _save(db_session, account_id, NEEDS_KEY, api_key=PLAINTEXT_KEY)
    llm_provider_service.get_models(db_session, account_id, NEEDS_KEY)
    assert _row(db_session, account_id, NEEDS_KEY).models_cache is not None

    _save(db_session, account_id, NEEDS_KEY, api_key="sk-another-key")
    assert _row(db_session, account_id, NEEDS_KEY).models_cache is None


def test_models_probe_failure_falls_back_to_builtin(db_session, account_id, fake_llm):
    """TC-49：拉取失败**不报错**，回退内置模型表——`source=builtin`、`fetched_at` 为 null。"""
    _save(db_session, account_id, NEEDS_KEY, api_key=PLAINTEXT_KEY)
    fake_llm.models_error = ProviderProbeError("网络不通")

    result = llm_provider_service.get_models(db_session, account_id, NEEDS_KEY)

    assert result.source == "builtin"
    assert result.fetched_at is None
    assert [m.id for m in result.models] == [m.id for m in registry.PROVIDERS[NEEDS_KEY].builtin_models]
    assert len(result.models) > 0  # 内置表确有条目，否则本用例证明不了回退


def test_models_auth_error_does_not_fall_back(db_session, account_id, fake_llm):
    """接口文档 §3.3 models：已存 Key **无效 → 10013**，鉴权类失败**不回退**内置表（否则掩盖 Key 配置错误）。"""
    _save(db_session, account_id, NEEDS_KEY, api_key=PLAINTEXT_KEY)
    fake_llm.models_error = ProviderAuthError("Key 无效")

    with pytest.raises(BizException) as exc:
        llm_provider_service.get_models(db_session, account_id, NEEDS_KEY)
    assert exc.value.code == ErrorCode.LLM_TEST_FAILED


def test_models_without_key_returns_10012(db_session, account_id, fake_llm):
    """接口文档 §3.3 models：该供应商未配置 Key → **10012**（提示先填 Key）。"""
    with pytest.raises(BizException) as exc:
        llm_provider_service.get_models(db_session, account_id, NEEDS_KEY)
    assert exc.value.code == ErrorCode.LLM_KEY_MISSING
    assert fake_llm.list_calls == []  # 未发请求


def test_models_custom_without_base_url_returns_10001(db_session, account_id, fake_llm):
    """接口文档 §3.3 models：`custom` 未填端点 → 10001。"""
    with pytest.raises(BizException) as exc:
        llm_provider_service.get_models(db_session, account_id, CUSTOM)
    assert exc.value.code == ErrorCode.PARAM_INVALID


def test_models_api_contract(client: TestClient, fake_llm):
    """接口文档 §3.3 models：响应体为 `{models:[{id,display_name,is_free}], source, fetched_at}`。"""
    client.put(f"{API}/llm-providers/{NEEDS_KEY}", json={"api_key": PLAINTEXT_KEY})

    data = client.get(f"{API}/llm-providers/{NEEDS_KEY}/models").json()["data"]

    assert set(data) == {"models", "source", "fetched_at"}
    assert set(data["models"][0]) == {"id", "display_name", "is_free"}


# ---------- TC-48 两级切换：配置按供应商独立留存，切回即用 ----------


def test_switch_back_preserves_previous_config(db_session, account_id):
    """TC-48：激活项切换后，**旧供应商配置仍在**（含所选模型），切回即用、无需重填。"""
    _save(db_session, account_id, NEEDS_KEY, api_key=PLAINTEXT_KEY, model="fake-model-a")
    _save(db_session, account_id, "zhipu", api_key=PLAINTEXT_KEY, model="glm-4.7-flash")

    llm_provider_service.activate_provider(db_session, account_id, "zhipu")
    assert _row(db_session, account_id, NEEDS_KEY).model == "fake-model-a"  # 配置未被清

    llm_provider_service.activate_provider(db_session, account_id, NEEDS_KEY)
    assert llm_provider_service.list_providers(db_session, account_id).active == NEEDS_KEY
    assert _row(db_session, account_id, NEEDS_KEY).model == "fake-model-a"


def test_active_provider_determines_key_used_for_models(db_session, account_id, fake_llm):
    """TC-48：模型列表按**该供应商自己的**配置取 Key 与端点，与当前激活项互不串用。"""
    _save(db_session, account_id, NEEDS_KEY, api_key=PLAINTEXT_KEY)
    _save(db_session, account_id, "zhipu", api_key="sk-zhipu-key")
    llm_provider_service.activate_provider(db_session, account_id, "zhipu")

    llm_provider_service.get_models(db_session, account_id, NEEDS_KEY)

    provider, base_url, api_key = fake_llm.list_calls[0]
    assert (provider, api_key) == (NEEDS_KEY, PLAINTEXT_KEY)
    assert base_url == registry.PROVIDERS[NEEDS_KEY].base_url


# ---------- TC-61 多账号配置隔离 ----------


def test_cross_account_configs_are_isolated(client: TestClient, make_account):
    """TC-61：A/B 各自配置**互不可见**（同供应商各存一份，Key 与模型互不覆盖）。"""
    other = make_account("other_user")
    client.put(f"{API}/llm-providers/{NEEDS_KEY}", json={"api_key": PLAINTEXT_KEY, "model": "fake-model-a"})

    assert client.get(f"{API}/llm-providers").json()["data"]["active"] == NEEDS_KEY
    other_list = client.get(f"{API}/llm-providers", headers=other["headers"]).json()["data"]
    assert other_list["active"] is None  # B 未配置
    assert {i["provider"]: i for i in other_list["providers"]}[NEEDS_KEY]["key_set"] is False

    client.delete(f"{API}/llm-providers/{NEEDS_KEY}")  # A 删除不影响 B
    assert client.get(f"{API}/llm-providers").json()["data"]["active"] is None


def test_cross_account_active_is_independent(client: TestClient, make_account, fake_llm):
    """TC-61：A/B 的**激活项独立**——一方切换激活不影响另一方。"""
    other = make_account("other_user")
    client.put(f"{API}/llm-providers/{NEEDS_KEY}", json={"api_key": PLAINTEXT_KEY})
    client.put(f"{API}/llm-providers/{NO_KEY}", json={})
    client.post(f"{API}/llm-providers/{NO_KEY}/activate")

    other_headers = other["headers"]
    client.put(f"{API}/llm-providers/{NEEDS_KEY}", json={"api_key": PLAINTEXT_KEY}, headers=other_headers)
    client.put(f"{API}/llm-providers/{NO_KEY}", json={}, headers=other_headers)
    client.post(f"{API}/llm-providers/{NEEDS_KEY}/activate", headers=other_headers)

    assert client.get(f"{API}/llm-providers").json()["data"]["active"] == NO_KEY
    assert client.get(f"{API}/llm-providers", headers=other_headers).json()["data"]["active"] == NEEDS_KEY


def test_cross_account_models_fallback_uses_own_config(client: TestClient, make_account, fake_llm):
    """TC-61：断网时模型列表回退内置表——**按各自账号**判定，一方未配置不影响另一方。"""
    other = make_account("other_user")
    client.put(f"{API}/llm-providers/{NEEDS_KEY}", json={"api_key": PLAINTEXT_KEY})
    fake_llm.models_error = ProviderProbeError("网络不通")

    mine = client.get(f"{API}/llm-providers/{NEEDS_KEY}/models").json()["data"]
    assert mine["source"] == "builtin"

    theirs = client.get(f"{API}/llm-providers/{NEEDS_KEY}/models", headers=other["headers"])
    assert theirs.json()["code"] == 10012  # B 未配置 Key，先报缺 Key（不误用 A 的配置）


# ---------- 回归防护：/settings 瘦身（LLM 字段已迁出，不得回流） ----------


def test_settings_no_longer_exposes_llm_fields(client: TestClient):
    """步骤 6 起 `/settings` 与 LLM 供应商字段解耦——旧字段不得回流（避免两处配置口径并存）。

    注：该行为无对应 TC 编号，属步骤 6「settings 瘦身」的回归防护，已在测试日志登记。
    """
    data = client.get(f"{API}/settings").json()["data"]

    # 字段闭包不含任何 LLM 键；`crawl_url` 亦已移除（SRS v1.11 / 数据库设计 v1.5：抓取目标
    # 改由信息源清单承载，后端三处代码于 2026-09-26 删除）
    assert set(data) == {"tts_enabled", "voice_enabled", "default_question_count", "asr_provider",
                         "tts_voice", "asr_key_set", "guide_done", "crawl_enabled"}


# ---------- TC-105：免费模型档（两类来源 + 选用 + 档位互转） ----------


def _seed_platform_row(provider: str, key: str = "sk-platform-shared") -> None:
    """造一行 `user_id=0` 平台共享行（免费模型的 Key 来源）。

    自开会话、每例各造一次：`client` fixture 的逐例清库会 TRUNCATE 本表
    （`_reset_database` 只保留 `config` 表的 user_id=0 行）。
    """
    from app.database import SYSTEM_USER_ID, SessionLocal
    from app.utils.security import encrypt_text

    with SessionLocal() as session:
        session.add(
            LlmProviderConfig(
                user_id=SYSTEM_USER_ID,
                provider=provider,
                api_key=encrypt_text(key),
                model=meta_default_model(provider),
            )
        )
        session.commit()


def meta_default_model(provider: str) -> str | None:
    meta = registry.get_provider(provider)
    return meta.default_model if meta else None


def test_free_models_two_sources(client: TestClient):
    """TC-105：免费清单**两类来源并列**——公开免 Key 服务不看平台行，平台共享型只含已配 Key 的家。"""
    _seed_platform_row("zhipu")

    groups = client.get(f"{API}/llm-providers/free-models").json()["data"]["providers"]
    keys = [g["provider"] for g in groups]

    assert "pollinations" in keys  # 公开免 Key 服务：一行平台行都没配也在
    assert "zhipu" in keys  # 平台共享型：配了共享 Key 才入选
    assert keys == [k for k in registry.PROVIDER_KEYS if k in keys]  # 输出顺序即注册表顺序

    zhipu = next(g for g in groups if g["provider"] == "zhipu")
    assert {m["id"] for m in zhipu["models"]} == {"glm-4.7-flash", "glm-4-flash"}

    public = next(g for g in groups if g["provider"] == "pollinations")
    assert public["models"][0]["id"] == "openai-fast"


def test_free_models_without_platform_row(client: TestClient):
    """TC-105：平台未配任何共享 Key 时，清单**只剩公开免 Key 服务**（不是空数组）。"""
    groups = client.get(f"{API}/llm-providers/free-models").json()["data"]["providers"]

    assert [g["provider"] for g in groups] == ["pollinations"]


def test_select_free_model_saves_and_activates(client: TestClient):
    """TC-105：选用免费模型**保存与生效一步完成**，且**不清账号已存的 Key**（那是用户自己的数据）。"""
    from app.database import SessionLocal
    from app.utils.security import encrypt_text

    uid = client.auth_account["id"]
    _seed_platform_row("zhipu")
    with SessionLocal() as session:  # 先存一把账号自己的 Key，模拟此前的自配档
        session.add(
            LlmProviderConfig(user_id=uid, provider="zhipu", api_key=encrypt_text("sk-mine"), model="glm-4.7-flash")
        )
        session.commit()

    data = client.put(
        f"{API}/llm-providers/free-model", json={"provider": "zhipu", "model": "glm-4-flash"}
    ).json()["data"]

    assert data["use_shared"] is True
    assert data["is_active"] is True
    assert data["model"] == "glm-4-flash"
    assert data["key_set"] is True  # 账号那把 Key 仍在（免费档不清它）
    assert data["base_url"] == registry.get_provider("zhipu").base_url  # 端点固定取注册表值
    assert client.get(f"{API}/llm-providers").json()["data"]["active"] == "zhipu"


def test_select_free_model_validation(client: TestClient):
    """TC-105：`provider` 非法 / 该家不在免费清单 / `model` 不在该家清单 → **10001**（按清单校验，不信任前端传值）。"""
    bad_provider = client.put(f"{API}/llm-providers/free-model", json={"provider": "nope", "model": "x"})
    not_free = client.put(f"{API}/llm-providers/free-model", json={"provider": "deepseek", "model": "x"})
    bad_model = client.put(
        f"{API}/llm-providers/free-model", json={"provider": "pollinations", "model": "not-a-model"}
    )

    assert bad_provider.json()["code"] == 10001
    assert not_free.json()["code"] == 10001
    assert bad_model.json()["code"] == 10001
    assert client.get(f"{API}/llm-providers").json()["data"]["active"] is None  # 一律未生效


def test_own_key_switches_back_to_self_hosted(client: TestClient):
    """TC-105：免费档 → 自配档——`PUT /{provider}` 提交**非空 `api_key`** 即自动置 `use_shared=0`。"""
    _seed_platform_row("zhipu")
    client.put(f"{API}/llm-providers/free-model", json={"provider": "zhipu", "model": "glm-4.7-flash"})

    data = client.put(f"{API}/llm-providers/zhipu", json={"api_key": "sk-my-own"}).json()["data"]

    assert data["use_shared"] is False
    assert data["key_set"] is True
