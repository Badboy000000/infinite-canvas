"""Asset 模块持久化 facade（PR-BE-07 · Wave 3-N.7 Batch 1 主线 A）。

`AssetLibraryModuleStore` / `PromptLibraryModuleStore` 是**薄委派**，让
service / router 层拿到统一的 `load` / `save` 接口，内部：

- `AssetLibraryModuleStore.load()`  → `app.stores.asset_library_store.load_asset_library()`
- `AssetLibraryModuleStore.save()`  → `app.stores.asset_library_store.save_asset_library(lib)`
- `PromptLibraryModuleStore.load()` → `app.stores.prompt_library_store.load_prompt_libraries()`
- `PromptLibraryModuleStore.save()` → `app.stores.prompt_library_store.save_prompt_libraries(data)`

严格约束（任务书零触碰事实清单）：
- **不改** `app/stores/asset_library_store.py`（PR-9 + PR-23 已 landing）·
  **不改** `app/stores/prompt_library_store.py`（PR-21 已 landing）。
- **不改** `asset_library.json` / `prompt_libraries.json` 磁盘 shape。
- 不直接 `import main`（继承 PR-BE-05/06/08/09 硬约束）。
- ASSET_LIBRARY_PRIMARY_WRITE / PROMPT_LIBRARY_PRIMARY_WRITE env 分派语义
  由 store facade 内部承担；本 module store 仅做同签名的薄委派。
"""

from __future__ import annotations

from typing import Any

from app.stores import asset_library_store as _asset_facade
from app.stores import prompt_library_store as _prompt_facade


class AssetLibraryModuleStore:
    """`asset_library.json` 薄委派 store。

    仅提供 `load()` / `save(lib)` 两个稳定接口。写路径遵守
    `ASSET_LIBRARY_PRIMARY_WRITE` env 分派（PR-9 + PR-23 已实装于
    `app/stores/asset_library_store.py`）。
    """

    def load(self) -> Any:
        """委派 `asset_library_store.load_asset_library()`。"""

        return _asset_facade.load_asset_library()

    def save(self, lib: Any) -> Any:
        """委派 `asset_library_store.save_asset_library(lib)`。

        DB 主写失败会上抛（P0 硬约束 #4）；JSON 主写路径不 fallback（P0
        硬约束 #3）。上层调用点必须容错，参照 `main.py` 现有 legacy 函数
        体的 try/except 边界。
        """

        return _asset_facade.save_asset_library(lib)


class PromptLibraryModuleStore:
    """`prompt_libraries.json` 薄委派 store。

    仅提供 `load()` / `save(data)` 两个稳定接口。写路径遵守
    `PROMPT_LIBRARY_PRIMARY_WRITE` env 分派（PR-21 已实装于
    `app/stores/prompt_library_store.py`）。
    """

    def load(self) -> Any:
        """委派 `prompt_library_store.load_prompt_libraries()`。"""

        return _prompt_facade.load_prompt_libraries()

    def save(self, data: Any) -> Any:
        """委派 `prompt_library_store.save_prompt_libraries(data)`。"""

        return _prompt_facade.save_prompt_libraries(data)


__all__ = ["AssetLibraryModuleStore", "PromptLibraryModuleStore"]
