"""Settings / DeploymentMode / RuntimeConfigBootstrap 只读 wrapper。

本模块对根 `main.py` 已有的 23 个路径常量、部署模式与两个启动 helper
（`ensure_runtime_config_files`、`load_env_file`）做**只读包裹**：

- `Settings`：`@dataclass(frozen=True)`；保留 23 个路径字段并追加部署 PR-01
  的非敏感运行开关，不引入 setter。
- `DeploymentMode`：从 `IC_DEPLOYMENT_MODE` 读取三种受支持模式。
- `get_settings() -> Settings`：deployment / security 字段在进程内首次读取后冻结，
  后续配置变化要求重启；23 个既有路径字段仍在每次调用时从 `main` 模块现读，
  保留 monkeypatch 与既有读时求值契约。
- `RuntimeConfigBootstrap`：一次性副作用封装。**本 PR 不接管**根 `main.py` 里已经执行的
  `ensure_runtime_config_files()` / `load_env_file()` 调用点（L627-628），只提供只读入口
  供未来 wave 消费。

签名冻结（本 PR 不许改）：
- `get_settings() -> Settings`（无参数）。
- `Settings` 原 23 个路径字段的字段名与顺序。
- `RuntimeConfigBootstrap.ensure_runtime_config_files()`、`.load_env_file()` 签名。

不做：
- 不改 `main.py:302-388`（`StorageSettings` / `apply_storage_settings` 冻结区间）。
- 不引入配置写入路径。
- 不接入 `RequestContext`、DB、新依赖。

详见 [[40 实施计划/后端模块化治理实施计划与PR清单]] PR-BE-03。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from types import MappingProxyType
from typing import Mapping


class DeploymentMode(str, Enum):
    """Supported deployment trust boundaries."""

    LOCAL_PERSONAL = "local_personal"
    INTRANET_TEAM = "intranet_team"
    PUBLIC_TEAM = "public_team"

    @classmethod
    def from_environment(cls) -> DeploymentMode:
        """Read and validate ``IC_DEPLOYMENT_MODE``."""
        raw_value = os.environ.get("IC_DEPLOYMENT_MODE")
        if raw_value is None:
            return cls.LOCAL_PERSONAL

        normalized = raw_value.strip().lower()
        try:
            return cls(normalized)
        except ValueError as exc:
            allowed = ", ".join(mode.value for mode in cls)
            raise ValueError(
                f"Invalid IC_DEPLOYMENT_MODE {raw_value!r}; expected one of: {allowed}"
            ) from exc


@dataclass(frozen=True)
class Settings:
    """只读运行时配置快照。

    路径字段 → `main.py` 原常量映射（23 项，1:1）：
        base_dir                       → BASE_DIR
        workflow_dir                   → WORKFLOW_DIR
        static_dir                     → STATIC_DIR
        output_dir                     → OUTPUT_DIR
        assets_dir                     → ASSETS_DIR
        output_input_dir               → OUTPUT_INPUT_DIR（默认锚点；运行时用 PathResolver.current_upload_dir()）
        output_output_dir              → OUTPUT_OUTPUT_DIR（默认锚点；运行时用 PathResolver.current_generated_dir()）
        asset_library_dir              → ASSET_LIBRARY_DIR
        local_upload_dir               → LOCAL_UPLOAD_DIR（默认锚点；运行时用 PathResolver.current_local_dir()）
        history_file                   → HISTORY_FILE
        api_env_file                   → API_ENV_FILE
        data_dir                       → DATA_DIR
        conversation_dir               → CONVERSATION_DIR
        canvas_dir                     → CANVAS_DIR
        media_preview_dir              → MEDIA_PREVIEW_DIR
        asset_library_path             → ASSET_LIBRARY_PATH
        prompt_library_path            → PROMPT_LIBRARY_PATH
        api_providers_file             → API_PROVIDERS_FILE
        runninghub_workflow_store_file → RUNNINGHUB_WORKFLOW_STORE_FILE
        shared_folders_file            → SHARED_FOLDERS_FILE
        global_config_file             → GLOBAL_CONFIG_FILE
        storage_settings_file          → STORAGE_SETTINGS_FILE
        data_db_path                   → DATA_DB_PATH  (数据 PR-1 新增)
    """

    base_dir: str
    workflow_dir: str
    static_dir: str
    output_dir: str
    assets_dir: str
    output_input_dir: str
    output_output_dir: str
    asset_library_dir: str
    local_upload_dir: str
    history_file: str
    api_env_file: str
    data_dir: str
    conversation_dir: str
    canvas_dir: str
    media_preview_dir: str
    asset_library_path: str
    prompt_library_path: str
    api_providers_file: str
    runninghub_workflow_store_file: str
    shared_folders_file: str
    global_config_file: str
    storage_settings_file: str
    # 数据 PR-1 新增字段：SQLite 数据库文件路径。默认由 `main.py` `DATA_DB_PATH`
    # 常量定义为 `<DATA_DIR>/app.db`；env `DATA_DB_PATH` 可覆盖。**新增此字段的
    # 依据**是 PR-BE-03 "下游需要注意的接口" 段落约定的"两步走"（`Settings` 加
    # 字段 + `main.py` 加对应常量）。签名扩展性影响：只增字段、不改字段顺序，
    # 22 → 23 项。已有 22 项测试 `test_settings_fields_match_main_constants`
    # 断言精确匹配 23 项字段清单。
    data_db_path: str

    # Deployment PR-01 adds a mode declaration and the non-secret switches that
    # later security PRs will consume. Defaults mirror today's runtime exactly;
    # this PR does not wire them into main.py, CORS, routes, or static mounts.
    deployment_mode: DeploymentMode = DeploymentMode.LOCAL_PERSONAL
    bind_host: str = "0.0.0.0"
    bind_port: int = 3000
    public_base_url: str = ""
    cors_allowed_origins: tuple[str, ...] = ("*",)
    session_cookie_name: str = "infinite_canvas_session"
    csrf_enabled: bool = False
    enable_require_auth: bool = False
    enable_admin_only_endpoints: bool = False
    file_url_mode: str = "legacy"
    log_dir: str = ""


@lru_cache(maxsize=1)
def _deployment_snapshot() -> Mapping[str, object]:
    """Return the immutable process-lifetime deployment/security snapshot.

    This is deliberately private: production callers consume the single public
    ``Settings`` contract via ``get_settings()``.  Caching only this group keeps
    deployment and security switches restart-bound without freezing the 23
    legacy path fields that must remain call-time resolved.
    """
    import main  # lazy import avoids main -> settings -> main cycles

    return MappingProxyType(
        {
            "deployment_mode": DeploymentMode.from_environment(),
            "bind_host": "0.0.0.0",
            "bind_port": 3000,
            "public_base_url": "",
            "cors_allowed_origins": ("*",),
            "session_cookie_name": "infinite_canvas_session",
            "csrf_enabled": False,
            "enable_require_auth": False,
            "enable_admin_only_endpoints": False,
            "file_url_mode": "legacy",
            "log_dir": os.path.join(main.BASE_DIR, "logs"),
        }
    )


def _reset_settings_cache_for_tests() -> None:
    """Clear process-lifetime settings state for isolated tests only.

    The helper is intentionally absent from this module's ``__all__`` and from
    ``app.shared.settings``.  Runtime configuration changes still require a
    process restart; tests use this private seam to model a fresh process.
    """
    _deployment_snapshot.cache_clear()


def get_settings() -> Settings:
    """组装动态路径与进程级 deployment/security 的只读 `Settings`。

    - 无参数、无副作用（不写盘、不改环境变量、不修改 `main` 模块属性）。
    - 23 个路径字段每次调用都会从 `main` 模块 attribute 现读；如测试通过
      `monkeypatch.setattr(main, "STORAGE_SETTINGS_FILE", ...)` 之类的手段动态
      注入，`get_settings()` 会立即反映最新值。
    - deployment / security 字段只在进程内首次调用时读取；后续环境变量变化
      不生效，配置变更要求重启进程。
    - 内部 `import main` 是懒 import，避免形成 `main → app.shared.settings → main`
      的循环导入（`main.py` 顶部会 `from app.shared.settings import get_settings`）。
    """
    import main  # 懒 import，规避循环

    return Settings(
        base_dir=main.BASE_DIR,
        workflow_dir=main.WORKFLOW_DIR,
        static_dir=main.STATIC_DIR,
        output_dir=main.OUTPUT_DIR,
        assets_dir=main.ASSETS_DIR,
        output_input_dir=main.OUTPUT_INPUT_DIR,
        output_output_dir=main.OUTPUT_OUTPUT_DIR,
        asset_library_dir=main.ASSET_LIBRARY_DIR,
        local_upload_dir=main.LOCAL_UPLOAD_DIR,
        history_file=main.HISTORY_FILE,
        api_env_file=main.API_ENV_FILE,
        data_dir=main.DATA_DIR,
        conversation_dir=main.CONVERSATION_DIR,
        canvas_dir=main.CANVAS_DIR,
        media_preview_dir=main.MEDIA_PREVIEW_DIR,
        asset_library_path=main.ASSET_LIBRARY_PATH,
        prompt_library_path=main.PROMPT_LIBRARY_PATH,
        api_providers_file=main.API_PROVIDERS_FILE,
        runninghub_workflow_store_file=main.RUNNINGHUB_WORKFLOW_STORE_FILE,
        shared_folders_file=main.SHARED_FOLDERS_FILE,
        global_config_file=main.GLOBAL_CONFIG_FILE,
        storage_settings_file=main.STORAGE_SETTINGS_FILE,
        data_db_path=main.DATA_DB_PATH,
        **_deployment_snapshot(),
    )


class RuntimeConfigBootstrap:
    """`main.py` 启动 helper 的只读封装。

    **本 PR 不改变启动时序**：根 `main.py` L627-628 仍在模块级调用
    `ensure_runtime_config_files()` 与 `load_env_file()`。本类只是为未来 PR
    提供统一入口，让 `create_app()` 里能显式调用，而不是隐式依赖 `import main`
    的顶层副作用。当前调用方需自行判断幂等性（`ensure_runtime_config_files`
    每次调用只 makedirs 一次，`load_env_file` 使用 `os.environ.setdefault`
    避免覆盖已注入的 env，两者均对重复调用安全）。
    """

    def ensure_runtime_config_files(self) -> None:
        """只读代理到 `main.ensure_runtime_config_files()`。

        副作用：makedirs 配置目录并 touch 空 `API/.env`（幂等）。
        """
        import main  # 懒 import

        main.ensure_runtime_config_files()

    def load_env_file(self) -> None:
        """只读代理到 `main.load_env_file()`。

        副作用：把 `API/.env` 中的键值以 `os.environ.setdefault` 注入进程环境
        （不覆盖已存在项，幂等）。
        """
        import main  # 懒 import

        main.load_env_file()


__all__ = ["DeploymentMode", "Settings", "get_settings", "RuntimeConfigBootstrap"]
