"""Asset 模块 Service facade（PR-BE-07 · Wave 3-N.7 Batch 1 主线 A）。

`AssetModuleFacade` 承接 asset 域公共状态（store 引用 + P0 密钥零入库
sanitize helper）。**40 端点的路由层通过 callback factory 委派**，本
facade 提供跨端点的通用工具与稳定接口签名。

**方案对齐**：
- 与 `app.modules.task.service.TaskModuleFacade` 完全同源（PR-BE-09 pattern）：
  路由层调 callback → callback 委派 legacy `main.upload_local_assets` /
  `main.get_asset_library` / `main.create_prompt_library` 函数体。
- 本 facade **不 `import main`**（继承 PR-BE-05 / 06 / 08 / 09 硬约束）。

**P0 密钥零入库防线（GM-16 v2 沿用 · CB-P5-32 承接）**：
- upload / import-urls / caption / classify 端点 payload 可能透传 provider
  api_key / secret / access_token / password / credential 字段。
- `_sanitize_payload_dict` helper 对齐 `app.modules.task.service._sanitize_payload_dict`
  pattern · sentinel token 集合完全一致（`_SECRET_KEY_TOKENS`）。
- 本 facade 不落地 log · 不落地 dict 副本 · 委派时透传 DTO 实例。sanitize
  view 仅在审计断言路径（T443）消费。
"""

from __future__ import annotations

from typing import Any

from .store import AssetLibraryModuleStore, PromptLibraryModuleStore


#: 需要脱敏的字段名子串（对齐 `app.modules.task.service._SECRET_KEY_TOKENS` +
#: `app.task.view.provider_view._SECRET_KEY_TOKENS`）。命中任一即整字段值
#: 替换为 `"[REDACTED]"`。
_SECRET_KEY_TOKENS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "access_token",
    "accesstoken",
    "secret",
    "bearer",
    "authorization",
    "password",
    "credential",
    "session_token",
    "refresh_token",
)


def _looks_like_secret_key(key: str) -> bool:
    lowered = str(key).lower()
    return any(tok in lowered for tok in _SECRET_KEY_TOKENS)


def _sanitize_payload_dict(payload: Any) -> Any:
    """把 payload dict 里形似密钥的字段替换为 `"[REDACTED]"`。

    仅在断言 P0 密钥零入库防线时使用 · 不改变 payload 委派到 legacy
    `main.upload_local_assets` / `main.classify_local_assets` 等函数时传入
    的实例 · 返回一个新的 sanitize 后 dict（供审计断言）。

    与 `app.modules.task.service._sanitize_payload_dict` 逐行同源（`_SECRET_KEY_TOKENS`
    集合一致），保证 GM-16 v2 sentinel sweep 断言可复用跨 module 的 helper。
    """

    if not isinstance(payload, dict):
        return payload
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if _looks_like_secret_key(key):
            cleaned[str(key)] = "[REDACTED]"
            continue
        cleaned[str(key)] = value
    return cleaned


class AssetModuleFacade:
    """Asset 域 service facade（薄状态载体）。

    承接：
    - `library_store`  : `asset_library.json` 薄委派（AssetLibraryModuleStore）
    - `prompt_store`   : `prompt_libraries.json` 薄委派（PromptLibraryModuleStore）

    **不承接**每端点分派 —— 40 端点走 router callback factory pattern（对齐
    PR-BE-09 canvas_tasks router）。本 facade 只提供稳定的 store 引用与
    sanitize helper 出口，便于 test / future PR 迁入函数体时消费。
    """

    def __init__(
        self,
        *,
        library_store: AssetLibraryModuleStore | None = None,
        prompt_store: PromptLibraryModuleStore | None = None,
    ) -> None:
        self._library_store = library_store or AssetLibraryModuleStore()
        self._prompt_store = prompt_store or PromptLibraryModuleStore()

    @property
    def library_store(self) -> AssetLibraryModuleStore:
        return self._library_store

    @property
    def prompt_store(self) -> PromptLibraryModuleStore:
        return self._prompt_store

    def load_asset_library(self) -> Any:
        """`GET /api/asset-library` 后端 fetch view。"""

        return self._library_store.load()

    def load_prompt_libraries(self) -> Any:
        """`GET /api/prompt-libraries` 后端 fetch view（未 public 化处理）。

        注意：`main.get_prompt_libraries` 端点最终返回 `public_prompt_libraries()`
        视图（脱去 hidden 字段）；本 facade 只做原始 load 委派，view 化
        由 router callback 承接。
        """

        return self._prompt_store.load()

    @staticmethod
    def sanitize_payload_dict(payload: Any) -> Any:
        """静态入口 · 供测试路径 (T443) 断言 sentinel sweep = 0 命中。"""

        return _sanitize_payload_dict(payload)


__all__ = [
    "AssetModuleFacade",
    "_sanitize_payload_dict",
    "_looks_like_secret_key",
    "_SECRET_KEY_TOKENS",
]
