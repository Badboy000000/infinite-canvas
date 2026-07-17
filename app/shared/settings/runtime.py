"""Settings / RuntimeConfigBootstrap 只读 wrapper — PR-BE-03。

本模块只对根 `main.py` 已有的 22 个路径常量与两个启动 helper（`ensure_runtime_config_files`、
`load_env_file`）做**只读包裹**：

- `Settings`：`@dataclass(frozen=True)`，字段与 `main.py` 现有 22 个路径常量 1:1 对应
  （见下方"字段 → 原常量映射表"）；不新增字段，不引入 setter。
- `get_settings() -> Settings`：无参数、无副作用；每次调用从 `main` 模块现读一次快照
  （承接文件 PR-0 的读时求值语义——虽然 22 个路径常量本身在 `main.py` 首次 import 时
  即冻结，`Settings` 仍保持"读时构造"以便未来 `data/storage_settings.json` 或环境注入
  能够透过 wrapper 生效）。
- `RuntimeConfigBootstrap`：一次性副作用封装。**本 PR 不接管**根 `main.py` 里已经执行的
  `ensure_runtime_config_files()` / `load_env_file()` 调用点（L627-628），只提供只读入口
  供未来 wave 消费。

签名冻结（本 PR 不许改）：
- `get_settings() -> Settings`（无参数）。
- `Settings` 22 字段的字段名与顺序。
- `RuntimeConfigBootstrap.ensure_runtime_config_files()`、`.load_env_file()` 签名。

不做：
- 不改 `main.py:302-388`（`StorageSettings` / `apply_storage_settings` 冻结区间）。
- 不引入配置写入路径。
- 不接入 `RequestContext`、DB、新依赖。

详见 [[40 实施计划/后端模块化治理实施计划与PR清单]] PR-BE-03。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """只读运行时配置快照。

    字段 → `main.py` 原常量映射（22 项，1:1）：
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


def get_settings() -> Settings:
    """现读 `main.py` 中 22 个路径常量并构造 `Settings` 只读快照。

    - 无参数、无副作用（不写盘、不改环境变量、不修改 `main` 模块属性）。
    - 每次调用都会重新从 `main` 模块 attribute 现读一次；如未来测试或运维通过
      `monkeypatch.setattr(main, "STORAGE_SETTINGS_FILE", ...)` 之类的手段动态
      注入，`get_settings()` 会立即反映最新值。
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


__all__ = ["Settings", "get_settings", "RuntimeConfigBootstrap"]
