"""`app.shared.settings` — Settings / DeploymentMode / PathResolver 只读包。

对根 `main.py` 已有的 22 个路径常量、`current_*_dir()` 读时求值三件套、以及
启动 helper（`ensure_runtime_config_files` / `load_env_file`）做**只读包裹**。

对外接口（签名冻结）：
- `get_settings() -> Settings`：无参数，返回 frozen dataclass。
- `Settings`：保留 23 个路径字段，并追加部署 PR-01 非敏感运行开关。
- `DeploymentMode`：三种部署模式的字符串枚举。
- `PathResolver`：`current_upload_dir()` / `current_generated_dir()` /
  `current_local_dir()` 读时求值方法 + Settings 22 字段的只读属性代理。
- `RuntimeConfigBootstrap`：`ensure_runtime_config_files()` / `load_env_file()`
  只读代理（本 PR 不接管调用点，仅提供入口）。

部署 PR-01 不改 `main.py`，启动摘要接线留给 Lead；既有路径常量与 helper
继续保留。

详见 [[40 实施计划/后端模块化治理实施计划与PR清单]] PR-BE-03。
"""
from .paths import PathResolver
from .runtime import DeploymentMode, RuntimeConfigBootstrap, Settings, get_settings

__all__ = [
    "DeploymentMode",
    "PathResolver",
    "RuntimeConfigBootstrap",
    "Settings",
    "get_settings",
]
