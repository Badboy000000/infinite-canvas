"""Provider 领域 Service（PR-BE-08 · Wave 3-N.6 Batch 2 主线 A）。

`ProviderConfigService` 承接 `/api/providers*` 全部端点的读写业务动作。

当前阶段 service 通过显式 callback 委派回 `main.py` 中的原函数体（保留兼容
层），**不 `import main`**；下一批 PR 会把函数体逐步迁入本模块。

Wave 3-N.6 Batch 2 主线 A 硬约束（任务书零触碰事实清单）：
- 不改 `ApiProviderPayload` / `TestConnectionPayload` DTO shape
- 不改 primary 单一约束与 400 语义（"至少保留一个 API 平台" / "API 平台
  ID 重复"）
- 不改 P0 密钥零入库（`_safe_provider_records` 深度脱敏由 store facade
  承担 · service 内部不落地 log）
- 不动 `app/stores/provider_config_store.py` 内部实现（本 PR 只走 facade）
- 不动 `app/adapters/provider/base.py` / `registry.py`（`resolve_adapter`
  函数零触碰 · registry facade 委派而非重实现）

设计：命令对象在方法边界上使用；service 内部使用与 `main.py` 原函数相同
的调用形式（避免形状漂移）。`raw: dict` 兜底承接 legacy 宽松 JSON 字段。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .commands import (
    FetchModelsCommand,
    SaveProvidersCommand,
    TestConnectionCommand,
)
from .store import ProviderStore


class ProviderConfigService:
    """Provider 配置业务动作 service。跨模块副作用通过 callback 显式注入。

    `save_providers` 是唯一写路径 —— 内部**不直接写 .env**，而是把 env
    更新聚合成 `env_updates: dict` 返回给 router，由 router 侧调用
    `update_env_values` 落盘 + `reload_env_globals` 刷新（保留现路径以
    满足 "`.env` 写入路径唯一 · CI grep 抗回归" 硬约束）。
    """

    def __init__(
        self,
        *,
        store: ProviderStore,
        public_api_providers: Callable[[], list[dict[str, Any]]],
        get_api_provider: Callable[[str], dict[str, Any]],
        get_api_provider_exact: Callable[[str], dict[str, Any]],
        normalize_provider: Callable[[dict[str, Any]], dict[str, Any]],
        public_provider: Callable[[dict[str, Any]], dict[str, Any]],
        preserve_runninghub_hidden_overrides: Callable[
            [dict[str, Any]], dict[str, Any]
        ],
        prune_runninghub_workflow_store_for_provider: Callable[
            [dict[str, Any]], None
        ],
        provider_key_env: Callable[[str], str],
        runninghub_wallet_key_env: Callable[[], str],
        volcengine_access_key_env: Callable[[], str],
        volcengine_secret_key_env: Callable[[], str],
    ) -> None:
        self._store = store
        self._public_api_providers = public_api_providers
        self._get_api_provider = get_api_provider
        self._get_api_provider_exact = get_api_provider_exact
        self._normalize_provider = normalize_provider
        self._public_provider = public_provider
        self._preserve_runninghub_hidden_overrides = (
            preserve_runninghub_hidden_overrides
        )
        self._prune_runninghub_workflow_store_for_provider = (
            prune_runninghub_workflow_store_for_provider
        )
        self._provider_key_env = provider_key_env
        self._runninghub_wallet_key_env = runninghub_wallet_key_env
        self._volcengine_access_key_env = volcengine_access_key_env
        self._volcengine_secret_key_env = volcengine_secret_key_env

    # ---- read paths -----------------------------------------------------

    def list_providers(self) -> list[dict[str, Any]]:
        """`GET /api/providers` 主读路径 —— 复用 legacy `public_api_providers`
        以完整承接密钥脱敏 + 20 字段白名单契约。"""

        return self._public_api_providers()

    def get_provider(self, provider_id: str) -> dict[str, Any] | None:
        """按 provider_id 拿单个 provider（严格匹配）。"""

        try:
            return self._get_api_provider_exact(provider_id)
        except Exception:
            return None

    # ---- write path -----------------------------------------------------

    def save_providers(
        self, cmd: SaveProvidersCommand
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """`PUT /api/providers` 主写路径。

        与 `main.py::save_providers` byte-equivalent（除 env_updates 由
        router 侧负责落盘外）。返回：
        - `providers`: 经 `public_provider()` 投影后的响应 list
        - `env_updates`: 待落盘的 env 键值对（router 侧调 `update_env_values`
          + `reload_env_globals`）
        """
        from fastapi import HTTPException  # local import to keep service light

        payload = cmd.payload_items
        providers: list[dict[str, Any]] = []
        env_updates: dict[str, str] = {}
        raw_primary_flags = [
            bool(getattr(item, "primary", False)) for item in payload
        ]
        for item in payload:
            provider = self._normalize_provider(item.dict(exclude={"api_key"}))
            if provider["id"] == "runninghub":
                provider = self._preserve_runninghub_hidden_overrides(provider)
                self._prune_runninghub_workflow_store_for_provider(provider)
            if any(existing["id"] == provider["id"] for existing in providers):
                raise HTTPException(
                    status_code=400,
                    detail=f"API 平台 ID 重复：{provider['id']}",
                )
            providers.append(provider)
            key_env = self._provider_key_env(provider["id"])
            if item.clear_key:
                env_updates[key_env] = ""
            elif item.api_key is not None and item.api_key.strip():
                env_updates[key_env] = item.api_key.strip()
            if provider["id"] == "runninghub":
                wallet_env = self._runninghub_wallet_key_env()
                if item.clear_wallet_key:
                    env_updates[wallet_env] = ""
                elif (
                    item.wallet_api_key is not None
                    and item.wallet_api_key.strip()
                ):
                    env_updates[wallet_env] = item.wallet_api_key.strip()
            if provider["id"] == "volcengine":
                ak_env = self._volcengine_access_key_env()
                sk_env = self._volcengine_secret_key_env()
                if item.clear_volcengine_access_key_id:
                    env_updates[ak_env] = ""
                elif (
                    item.volcengine_access_key_id is not None
                    and item.volcengine_access_key_id.strip()
                ):
                    env_updates[ak_env] = item.volcengine_access_key_id.strip()
                if item.clear_volcengine_secret_access_key:
                    env_updates[sk_env] = ""
                elif (
                    item.volcengine_secret_access_key is not None
                    and item.volcengine_secret_access_key.strip()
                ):
                    env_updates[sk_env] = (
                        item.volcengine_secret_access_key.strip()
                    )
            if provider["id"] == "comfly":
                env_updates["COMFLY_BASE_URL"] = provider["base_url"]
                env_updates["IMAGE_MODELS"] = ",".join(provider["image_models"])
                env_updates["CHAT_MODELS"] = ",".join(provider["chat_models"])
                env_updates["VIDEO_MODELS"] = ",".join(
                    provider.get("video_models") or []
                )
            if provider["id"] == "modelscope":
                env_updates["MODELSCOPE_CHAT_MODELS"] = ",".join(
                    provider["chat_models"]
                )
            if provider["id"] == "runninghub":
                provider["protocol"] = "runninghub"
            if provider["id"] == "volcengine":
                provider["protocol"] = "volcengine"
        if not providers:
            raise HTTPException(
                status_code=400, detail="至少保留一个 API 平台"
            )
        # 强制最多一个 primary(取最后被标记的;都没标记则保持原样不强制)
        primary_indices = [
            i for i, flag in enumerate(raw_primary_flags) if flag
        ]
        if primary_indices:
            winner = primary_indices[-1]
            for i, p in enumerate(providers):
                p["primary"] = i == winner
        self._store.save_api_providers(providers)
        return providers, env_updates

    def set_primary(self, provider_id: str) -> None:
        """将指定 provider_id 设为 primary,其他 provider 的 primary 位置 False。

        当前阶段本方法不被 router 直接调用（primary 位仅通过 PUT
        /api/providers 的 batch 语义标记），保留为公开签名以对齐任务书
        §1 的 `set_primary(provider_id) -> None` 承诺，方便下一批 PR 的
        细粒度 API 扩展直接消费。
        """

        providers = self._store.load_api_providers()
        found = False
        for provider in providers:
            if provider.get("id") == provider_id:
                provider["primary"] = True
                found = True
            else:
                provider["primary"] = False
        if not found:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=404,
                detail=f"未找到 provider：{provider_id}",
            )
        self._store.save_api_providers(providers)


__all__ = [
    "ProviderConfigService",
    "SaveProvidersCommand",
    "TestConnectionCommand",
    "FetchModelsCommand",
]
