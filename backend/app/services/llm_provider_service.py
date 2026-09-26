"""AI 供应商配置业务：注册表与账号配置合并、Fernet 加解密、激活位互斥、模型列表缓存（FR-018，系统设计 5.4）。

配置按账号隔离（`user_id + provider` 唯一）；Key 只以密文落库，**任何响应都不回显明文或片段**。
"""

import json
from dataclasses import asdict
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.clients import llm_provider as registry
from app.clients.llm_provider import ModelMeta
from app.database import SYSTEM_USER_ID
from app.exceptions import BizException, ErrorCode
from app.models import LlmProviderConfig
from app.schemas.llm_provider import (
    ActiveProviderDTO,
    FreeModelItemDTO,
    FreeModelListDTO,
    FreeModelSelectRequest,
    FreeProviderDTO,
    ModelItemDTO,
    ModelListDTO,
    ProviderItemDTO,
    ProviderListDTO,
    ProviderSaveRequest,
    ProviderTestDTO,
    ProviderTestRequest,
)
from app.utils.datetime_utils import format_datetime
from app.utils.security import decrypt_text, encrypt_text

CACHE_TTL_HOURS = 24  # 模型列表缓存有效期（系统设计 5.4）


def list_providers(db: Session, user_id: int) -> ProviderListDTO:
    """全部供应商卡片（GET /llm-providers）：注册表 13 项与当前账号配置合并，未配置的也返回。"""
    rows = {
        row.provider: row
        for row in db.scalars(
            select(LlmProviderConfig).where(LlmProviderConfig.user_id == user_id)
        ).all()
    }
    items = [
        _to_item(meta, rows.get(meta.key)) for meta in registry.PROVIDERS.values()
    ]
    return ProviderListDTO(active=_active_provider(db, user_id), providers=items)


def save_provider(
    db: Session, user_id: int, provider: str, payload: ProviderSaveRequest
) -> ProviderItemDTO:
    """保存配置（PUT /llm-providers/{provider}）：重复保存走更新，**不改变当前激活项**。

    账号尚无激活行时，本次保存的供应商自动生效（数据库设计 3.17）。
    """
    meta = _require_meta(provider)
    row = _get_row(db, user_id, provider)
    is_new = row is None
    if is_new:
        row = LlmProviderConfig(user_id=user_id, provider=provider, is_active=0)

    # api_key：省略或留空 = 不修改已存 Key；首次配置必填（ollama 本地无需 Key）
    incoming_key = (payload.api_key or "").strip()
    if incoming_key:
        row.api_key = encrypt_text(incoming_key)
        row.use_shared = 0  # 填了自己的 Key = 不再用平台共享 Key（免费档转自配档）
        row.models_cache = None  # Key 变更后旧模型缓存作废：否则换了错 Key 仍看到缓存、测不出 10013
    elif is_new and meta.needs_key and not row.use_shared:
        raise BizException(ErrorCode.PARAM_INVALID, "首次配置需填写 API Key")

    # base_url：省略 = 不修改；传空串 = 恢复注册表默认
    if payload.base_url is not None:
        row.base_url = payload.base_url.strip() or None
    if not registry.resolve_base_url(meta, row.base_url):
        raise BizException(ErrorCode.PARAM_INVALID, "自定义供应商需填写 API 端点")

    # model：省略 = 不修改；传空串 = 用注册表默认模型
    if payload.model is not None:
        row.model = payload.model.strip() or None

    if is_new:
        if not _has_active(db, user_id):  # 首个配置的供应商自动激活
            row.is_active = 1
        db.add(row)
    row.updated_at = datetime.now()
    db.commit()
    db.refresh(row)
    return _to_item(meta, row)


def delete_provider(db: Session, user_id: int, provider: str) -> None:
    """删除配置（DELETE /llm-providers/{provider}）：仅影响该供应商；删除当前激活项后 AI 进入未配置态。"""
    _require_meta(provider)
    row = _get_row(db, user_id, provider)
    if row is None:
        raise BizException(ErrorCode.NOT_FOUND, "该供应商尚未配置")
    db.delete(row)
    db.commit()


def activate_provider(db: Session, user_id: int, provider: str) -> ActiveProviderDTO:
    """设为当前生效（POST /llm-providers/{provider}/activate）：同一事务内取消其他行激活位，至多一行生效。

    未配置 Key 的供应商（非 ollama）不允许激活——否则后续 LLM 调用必然失败。
    """
    meta = _require_meta(provider)
    row = _get_row(db, user_id, provider)
    if row is None or (meta.needs_key and not row.api_key and not row.use_shared):
        raise BizException(ErrorCode.PARAM_INVALID, "请先填写并保存 API Key，再设为当前使用")
    db.execute(
        update(LlmProviderConfig)
        .where(LlmProviderConfig.user_id == user_id)
        .values(is_active=0)
    )
    row.is_active = 1
    row.updated_at = datetime.now()
    db.commit()
    return ActiveProviderDTO(active=provider)


def get_models(
    db: Session,
    user_id: int,
    provider: str,
    refresh: bool = False,
    api_key: str | None = None,
    base_url: str | None = None,
) -> ModelListDTO:
    """模型列表（GET /llm-providers/{provider}/models）：24h 缓存优先，失败回退内置表。

    传入 `api_key` / `base_url` = **临时探测**（与 /test 同口径，不落库）——供「配置已填、尚未保存」时先看模型：
    跳过缓存读写（结果属于未保存的配置，写进缓存会污染已存 Key 的模型列表）。
    不传：Key 取当前账号已存配置；已存 Key 无效 → 10013（不回退），其余失败不报错、`source=builtin`。
    """
    meta = _require_meta(provider)
    row = _get_row(db, user_id, provider)
    incoming_key = (api_key or "").strip()
    incoming_url = (base_url or "").strip()
    ad_hoc = bool(incoming_key or incoming_url)  # 传了探测参数即临时探测

    endpoint = registry.resolve_base_url(meta, incoming_url or (row.base_url if row else None))
    if not endpoint:
        raise BizException(ErrorCode.PARAM_INVALID, "自定义供应商需先填写 API 端点")

    cached = None if (refresh or ad_hoc) else _load_cache(row, endpoint)
    if cached is not None:
        return cached

    probe_key = incoming_key or (decrypt_text(row.api_key) if row and row.api_key else None)
    if meta.needs_key and not probe_key:
        raise BizException(ErrorCode.LLM_KEY_MISSING)

    try:
        models = registry.list_models(provider, endpoint, probe_key)
    except registry.ProviderAuthError as exc:
        raise BizException(ErrorCode.LLM_TEST_FAILED, str(exc)) from exc
    except registry.ProviderProbeError:
        return ModelListDTO(  # 拉取失败不报错：回退内置表，前端标注「内置列表（上次拉取失败）」
            models=[ModelItemDTO(**asdict(item)) for item in meta.builtin_models],
            source="builtin",
            fetched_at=None,
        )

    fetched_at = datetime.now()
    if not ad_hoc:  # 临时探测不落库
        _store_cache(row, endpoint, models, fetched_at)
        db.commit()
    return ModelListDTO(
        models=[ModelItemDTO(**asdict(item)) for item in models],
        source="remote",
        fetched_at=format_datetime(fetched_at),
    )


def test_provider(db: Session, user_id: int, payload: ProviderTestRequest) -> ProviderTestDTO:
    """连通性测试（POST /llm-providers/test）：**不落库、不保存配置**；失败 → 10013 + 具体原因。"""
    meta = _require_meta(payload.provider)
    row = _get_row(db, user_id, payload.provider)

    api_key = (payload.api_key or "").strip()
    if not api_key and row and row.api_key:
        api_key = decrypt_text(row.api_key)  # 省略则用当前账号已存 Key
    if meta.needs_key and not api_key:
        raise BizException(ErrorCode.LLM_KEY_MISSING)

    base_url = (
        (payload.base_url or "").strip()
        or (row.base_url if row else None)
        or meta.base_url
    )
    if not base_url:
        raise BizException(ErrorCode.PARAM_INVALID, "自定义供应商需填写 API 端点")

    try:
        model = registry.test_connection(payload.provider, base_url, api_key, payload.model)
    except registry.ProviderProbeError as exc:
        raise BizException(ErrorCode.LLM_TEST_FAILED, str(exc)) from exc
    return ProviderTestDTO(message="ok", model=model)


def list_free_models(db: Session) -> FreeModelListDTO:
    """免费模型清单（GET /llm-providers/free-models）：两类来源合成（系统设计 5.4）。

    ①**公开免 Key 服务**（注册表 `is_public`）：本就不需要任何 Key，**不看平台行**；
    ②**平台共享 Key**：只含 `user_id=0` 平台行已配 Key 的供应商。
    按注册表顺序输出（界面下拉顺序可预期）：模型取内置表里标了 `is_free` 的，
    一家都没标则退化为该家默认模型单个；用内置表（静态）而非实时拉取——下拉框内容需可预期，
    且不受服务当下是否可用影响（公开服务的可用性波动由调用时的自动降级兜住）。
    """
    rows = {
        row.provider: row
        for row in db.scalars(
            select(LlmProviderConfig).where(LlmProviderConfig.user_id == SYSTEM_USER_ID)
        ).all()
    }
    providers: list[FreeProviderDTO] = []
    for key in registry.PROVIDER_KEYS:
        meta = registry.get_provider(key)
        if not meta.is_public:
            row = rows.get(key)
            if row is None or not row.api_key:  # 平台未配共享 Key 的家不入选
                continue
        candidates = [item for item in meta.builtin_models if item.is_free]
        if not candidates and meta.default_model:
            candidates = [ModelMeta(meta.default_model, meta.default_model)]
        if not candidates:
            continue
        providers.append(
            FreeProviderDTO(
                provider=meta.key,
                name=meta.name,
                models=[
                    FreeModelItemDTO(id=item.id, display_name=item.display_name)
                    for item in candidates
                ],
            )
        )
    return FreeModelListDTO(providers=providers)


def select_free_model(
    db: Session, user_id: int, payload: FreeModelSelectRequest
) -> ProviderItemDTO:
    """选用免费模型（PUT /llm-providers/free-model）：保存并立即生效。

    写入账号行 `use_shared=1` + 所选模型并置激活位；**不清空账号已存的 api_key**——那是
    用户自己的数据，日后改回自配 Key 时还要用。所选模型按免费清单校验，不信任前端传值。
    """
    meta = _require_meta(payload.provider)
    free_ids = {
        item.id
        for group in list_free_models(db).providers
        if group.provider == meta.key
        for item in group.models
    }
    if not free_ids:
        raise BizException(ErrorCode.PARAM_INVALID, "该供应商未提供免费模型")
    if payload.model not in free_ids:
        raise BizException(ErrorCode.PARAM_INVALID, "所选模型不在免费模型清单内")

    row = _get_row(db, user_id, meta.key)
    if row is None:
        row = LlmProviderConfig(user_id=user_id, provider=meta.key)
        db.add(row)
    row.use_shared = 1
    row.base_url = None  # 端点固定用注册表默认值（免费模型不接受自定义端点）
    row.model = payload.model
    row.models_cache = None
    db.execute(
        update(LlmProviderConfig)
        .where(LlmProviderConfig.user_id == user_id)
        .values(is_active=0)
    )
    row.is_active = 1
    row.updated_at = datetime.now()
    db.commit()
    db.refresh(row)
    return _to_item(meta, row)


# ---------- 内部工具 ----------


def _require_meta(provider: str) -> registry.ProviderMeta:
    """取注册表条目；标识非法 → 10001（接口文档 3.3）。"""
    meta = registry.get_provider(provider)
    if meta is None:
        raise BizException(ErrorCode.PARAM_INVALID, "供应商标识不存在")
    return meta


def _get_row(db: Session, user_id: int, provider: str) -> LlmProviderConfig | None:
    """取当前账号在该供应商下的配置行（未配置返回 None）。"""
    return db.scalar(
        select(LlmProviderConfig).where(
            LlmProviderConfig.user_id == user_id, LlmProviderConfig.provider == provider
        )
    )


def _has_active(db: Session, user_id: int) -> bool:
    """该账号是否已有生效的供应商配置。"""
    return _active_provider(db, user_id) is not None


def _active_provider(db: Session, user_id: int) -> str | None:
    """当前生效供应商标识；未配置任何供应商时为 None。"""
    return db.scalar(
        select(LlmProviderConfig.provider).where(
            LlmProviderConfig.user_id == user_id, LlmProviderConfig.is_active == 1
        )
    )


def _to_item(meta: registry.ProviderMeta, row: LlmProviderConfig | None) -> ProviderItemDTO:
    """注册表条目 + 账号配置行 → 卡片 DTO（未配置的行按注册表默认值展示）。"""
    return ProviderItemDTO(
        provider=meta.key,
        name=meta.name,
        group=meta.group,
        base_url=registry.resolve_base_url(meta, row.base_url if row else None),
        needs_key=meta.needs_key,
        key_set=bool(row and row.api_key),
        model=(row.model if row else None) or "",
        is_active=bool(row and row.is_active),
        use_shared=bool(row and row.use_shared),
    )


def _load_cache(row: LlmProviderConfig | None, base_url: str) -> ModelListDTO | None:
    """读取模型缓存：超 24h、解析失败或端点已变更（缓存按 provider + base_url 维度）均视为失效。"""
    if row is None or not row.models_cache:
        return None
    try:
        payload = json.loads(row.models_cache)
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
        models = [ModelMeta(**item) for item in payload["models"]]
    except (ValueError, KeyError, TypeError):
        return None
    if payload.get("base_url") != base_url:
        return None
    if datetime.now() - fetched_at > timedelta(hours=CACHE_TTL_HOURS):
        return None
    return ModelListDTO(
        models=[ModelItemDTO(**asdict(item)) for item in models],
        source="remote",
        fetched_at=format_datetime(fetched_at),
    )


def _store_cache(
    row: LlmProviderConfig | None, base_url: str, models: list[ModelMeta], fetched_at: datetime
) -> None:
    """写入模型缓存（未保存过配置的供应商无处可存，跳过——下次仍会实时拉取）。"""
    if row is None:
        return
    row.models_cache = json.dumps(
        {
            "base_url": base_url,
            "fetched_at": fetched_at.isoformat(),
            "models": [asdict(item) for item in models],
        },
        ensure_ascii=False,
    )
    row.updated_at = datetime.now()
