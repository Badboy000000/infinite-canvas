"""`app.shared.settings` — Settings / PathResolver 只读 wrapper 包（PR-BE-03）。

对根 `main.py` 已有的 22 个路径常量、`current_*_dir()` 读时求值三件套、以及
启动 helper（`ensure_runtime_config_files` / `load_env_file`）做**只读包裹**。

对外接口（签名冻结）：
- `get_settings() -> Settings`：无参数，返回 frozen dataclass。
- `Settings`：22 字段，与 `main.py` 原常量 1:1 对应。
- `PathResolver`：`current_upload_dir()` / `current_generated_dir()` /
  `current_local_dir()` 读时求值方法 + Settings 22 字段的只读属性代理。
- `RuntimeConfigBootstrap`：`ensure_runtime_config_files()` / `load_env_file()`
  只读代理（本 PR 不接管调用点，仅提供入口）。

本 PR **不改** `main.py:302-388`（`StorageSettings` / `apply_storage_settings`
冻结区间），也不删除任何 `main.py` 原常量或 helper。仅新增 wrapper。

详见 [[40 实施计划/后端模块化治理实施计划与PR清单]] PR-BE-03。
"""
from .paths import PathResolver
from .runtime import RuntimeConfigBootstrap, Settings, get_settings

__all__ = [
    "PathResolver",
    "RuntimeConfigBootstrap",
    "Settings",
    "get_settings",
]
