"""PR-BE-03 契约测试：Settings / PathResolver 只读 wrapper。

覆盖点：
1. `get_settings()` 返回 frozen dataclass；字段写入触发 `FrozenInstanceError`。
2. `Settings` 22 字段清单严格与 `main.py` 22 个路径常量一一对应（数量与名字）。
3. `PathResolver.current_upload_dir/current_generated_dir/current_local_dir()`
   保持读时求值语义——通过 `monkeypatch.setattr(main, "STORAGE_SETTINGS_FILE", ...)`
   把 wrapper 重定向到临时 JSON 文件后，wrapper 读到新值。
4. 调用 wrapper 无副作用：不写盘、不改环境变量、不修改 `main` 模块属性。

详见 [[40 实施计划/后端模块化治理实施计划与PR清单]] PR-BE-03。
"""
from __future__ import annotations

import copy
import dataclasses
import json
import os
from pathlib import Path

import pytest


# 路径字段名 → main.py 常量名映射（35 项 = 22 首批 + 1 数据 PR-1 + 4 数据 PR-4 + 1 数据 PR-5 + 1 数据 PR-6 + 1 数据 PR-7 + 3 数据 PR-8 + 1 数据 PR-9 + 1 数据 PR-11）
FIELD_TO_MAIN_CONST = {
    "base_dir": "BASE_DIR",
    "workflow_dir": "WORKFLOW_DIR",
    "static_dir": "STATIC_DIR",
    "output_dir": "OUTPUT_DIR",
    "assets_dir": "ASSETS_DIR",
    "output_input_dir": "OUTPUT_INPUT_DIR",
    "output_output_dir": "OUTPUT_OUTPUT_DIR",
    "asset_library_dir": "ASSET_LIBRARY_DIR",
    "local_upload_dir": "LOCAL_UPLOAD_DIR",
    "history_file": "HISTORY_FILE",
    "api_env_file": "API_ENV_FILE",
    "data_dir": "DATA_DIR",
    "conversation_dir": "CONVERSATION_DIR",
    "canvas_dir": "CANVAS_DIR",
    "media_preview_dir": "MEDIA_PREVIEW_DIR",
    "asset_library_path": "ASSET_LIBRARY_PATH",
    "prompt_library_path": "PROMPT_LIBRARY_PATH",
    "api_providers_file": "API_PROVIDERS_FILE",
    "runninghub_workflow_store_file": "RUNNINGHUB_WORKFLOW_STORE_FILE",
    "shared_folders_file": "SHARED_FOLDERS_FILE",
    "global_config_file": "GLOBAL_CONFIG_FILE",
    "storage_settings_file": "STORAGE_SETTINGS_FILE",
    # 数据 PR-1 新增
    "data_db_path": "DATA_DB_PATH",
    # 数据 PR-4（Wave 3-C）新增 4 个 shadow read flags
    "shadow_read_project": "SHADOW_READ_PROJECT",
    "shadow_read_provider_config": "SHADOW_READ_PROVIDER_CONFIG",
    "shadow_read_prompt_library": "SHADOW_READ_PROMPT_LIBRARY",
    "shadow_read_workflow_definition": "SHADOW_READ_WORKFLOW_DEFINITION",
    # 数据 PR-5（Wave 3-D）新增 canvas shadow read flag
    "shadow_read_canvas": "SHADOW_READ_CANVAS",
    # 数据 PR-6（Wave 3-E）新增 canvas shadow write flag
    "shadow_write_canvas": "SHADOW_WRITE_CANVAS",
    # 数据 PR-7（Wave 3-F）新增 canvas primary write mode
    "canvas_primary_write": "CANVAS_PRIMARY_WRITE",
    # 数据 PR-8（Wave 3-G）新增 3 类低风险 domain primary write mode
    "project_primary_write": "PROJECT_PRIMARY_WRITE",
    "prompt_library_primary_write": "PROMPT_LIBRARY_PRIMARY_WRITE",
    "workflow_definition_primary_write": "WORKFLOW_DEFINITION_PRIMARY_WRITE",
    # 数据 PR-9（Wave 3-H）新增 AssetLibrary primary write mode
    "asset_library_primary_write": "ASSET_LIBRARY_PRIMARY_WRITE",
    # 数据 PR-11（Wave 3-N.6 Batch 1 主线 A）新增 Task primary write mode
    "task_primary_write": "TASK_PRIMARY_WRITE",
}

DEPLOYMENT_FIELDS = {
    "deployment_mode",
    "bind_host",
    "bind_port",
    "public_base_url",
    "cors_allowed_origins",
    "session_cookie_name",
    "csrf_enabled",
    "enable_require_auth",
    "enable_admin_only_endpoints",
    "file_url_mode",
    "log_dir",
}


@pytest.fixture(autouse=True)
def _isolate_deployment_settings_cache():
    """Model a fresh process around every test without exposing a public API."""
    from app.shared.settings.runtime import _reset_settings_cache_for_tests

    _reset_settings_cache_for_tests()
    yield
    _reset_settings_cache_for_tests()


def test_settings_is_frozen_dataclass():
    """`Settings` 是 frozen dataclass；对字段赋值必须报错。"""
    from app.shared.settings import Settings, get_settings

    assert dataclasses.is_dataclass(Settings)
    params = Settings.__dataclass_params__  # type: ignore[attr-defined]
    assert params.frozen is True, "Settings 必须是 frozen dataclass"

    settings = get_settings()
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.base_dir = "/tmp/should-fail"  # type: ignore[misc]


def test_settings_fields_preserve_main_constant_contract():
    """原有 23 个路径字段继续严格对应 `main.py` 常量。

    - 路径字段数量与名字不变。
    - 新增字段仅为部署 PR-01 的非敏感字段。
    - 每个字段 → 对应 `main` 属性存在且等值。
    """
    import main

    from app.shared.settings import Settings, get_settings

    fields = {f.name for f in dataclasses.fields(Settings)}
    expected_fields = set(FIELD_TO_MAIN_CONST) | DEPLOYMENT_FIELDS
    assert len(FIELD_TO_MAIN_CONST) == 35
    assert fields == expected_fields, (
        f"Settings 字段名与映射表不一致：\n"
        f"  Settings.fields = {sorted(fields)}\n"
        f"  expected        = {sorted(expected_fields)}"
    )

    settings = get_settings()
    for field_name, const_name in FIELD_TO_MAIN_CONST.items():
        assert hasattr(main, const_name), f"main.py 缺少常量 {const_name}"
        assert getattr(settings, field_name) == getattr(main, const_name), (
            f"Settings.{field_name} != main.{const_name}: "
            f"{getattr(settings, field_name)!r} vs {getattr(main, const_name)!r}"
        )


def test_get_settings_is_side_effect_free(tmp_path, monkeypatch):
    """连续调 `get_settings()` 不写盘、不改 env、不修改 `main` 模块属性。"""
    import main

    from app.shared.settings import get_settings

    # 快照调用前状态
    env_before = dict(os.environ)
    main_dict_before = {
        const: getattr(main, const)
        for const in FIELD_TO_MAIN_CONST.values()
    }

    for _ in range(5):
        snap = get_settings()
        assert snap is not None

    assert dict(os.environ) == env_before, "get_settings() 修改了环境变量"
    for const, value in main_dict_before.items():
        assert getattr(main, const) == value, (
            f"get_settings() 修改了 main.{const}"
        )


def test_path_resolver_current_dirs_read_at_call_time(tmp_path, monkeypatch):
    """`PathResolver.current_*_dir()` 严格保持读时求值语义。

    通过 monkeypatch 把 `main.STORAGE_SETTINGS_FILE` 重定向到 tmp_path 下
    的临时 JSON，然后：
      1. 写入 A 版本 → 三个方法读到 A。
      2. 覆盖为 B 版本 → 同一进程内再次调用应读到 B（禁止 Python-level 缓存）。
    """
    import main

    from app.shared.settings import PathResolver

    tmp_settings = tmp_path / "storage_settings.json"
    upload_a = str(tmp_path / "upload_a").replace("\\", "/")
    generated_a = str(tmp_path / "generated_a").replace("\\", "/")
    local_a = str(tmp_path / "local_a").replace("\\", "/")

    tmp_settings.write_text(
        json.dumps(
            {"upload": upload_a, "generated": generated_a, "local": local_a},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "STORAGE_SETTINGS_FILE", str(tmp_settings))

    resolver = PathResolver()
    assert os.path.abspath(resolver.current_upload_dir()) == os.path.abspath(upload_a)
    assert os.path.abspath(resolver.current_generated_dir()) == os.path.abspath(generated_a)
    assert os.path.abspath(resolver.current_local_dir()) == os.path.abspath(local_a)

    # 覆盖为 B 版本 —— 若 PathResolver 内部有 Python-level 缓存，就会漏读
    upload_b = str(tmp_path / "upload_b").replace("\\", "/")
    generated_b = str(tmp_path / "generated_b").replace("\\", "/")
    local_b = str(tmp_path / "local_b").replace("\\", "/")
    tmp_settings.write_text(
        json.dumps(
            {"upload": upload_b, "generated": generated_b, "local": local_b},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert os.path.abspath(resolver.current_upload_dir()) == os.path.abspath(upload_b)
    assert os.path.abspath(resolver.current_generated_dir()) == os.path.abspath(generated_b)
    assert os.path.abspath(resolver.current_local_dir()) == os.path.abspath(local_b)


def test_path_resolver_attribute_proxies_settings_fields():
    """`PathResolver.<field>` 等价于 `get_settings().<field>`（属性代理）。"""
    from app.shared.settings import PathResolver, get_settings

    resolver = PathResolver()
    settings = get_settings()

    for field_name in FIELD_TO_MAIN_CONST.keys():
        assert getattr(resolver, field_name) == getattr(settings, field_name), (
            f"PathResolver.{field_name} 与 Settings.{field_name} 不一致"
        )


def test_path_resolver_no_setter_available():
    """`PathResolver` 不许暴露任何 setter；对属性赋值应绕过 dataclass 保护。

    虽然 `PathResolver` 是普通类，`obj.x = y` 会成功——但这不影响下层
    数据源，因为所有属性都走 `__getattr__` / `current_*_dir()` 现读代理。
    这里断言的是"设置属性不会污染 wrapper 或 main 的状态"。
    """
    import main

    from app.shared.settings import PathResolver

    resolver = PathResolver()
    original_data_dir = main.DATA_DIR

    # 强行写 attribute（Python 允许），但 next call 仍从 main 现读
    resolver.data_dir = "/tmp/malicious"  # type: ignore[attr-defined]
    from app.shared.settings import get_settings

    assert get_settings().data_dir == original_data_dir, (
        "PathResolver 属性写入污染了 get_settings() 读取路径"
    )
    assert main.DATA_DIR == original_data_dir, (
        "PathResolver 属性写入污染了 main.DATA_DIR"
    )


def test_runtime_config_bootstrap_idempotent(tmp_path, monkeypatch):
    """`RuntimeConfigBootstrap.ensure_runtime_config_files()` 幂等且无异常。

    重定向 `API_ENV_FILE` / `DATA_DIR` 到 tmp_path，连续调 3 次不抛错、
    最终状态：目录已存在 + env 文件已存在。
    """
    import main

    from app.shared.settings import RuntimeConfigBootstrap

    fake_env_file = tmp_path / "API" / ".env"
    fake_data_dir = tmp_path / "data"
    monkeypatch.setattr(main, "API_ENV_FILE", str(fake_env_file))
    monkeypatch.setattr(main, "DATA_DIR", str(fake_data_dir))

    boot = RuntimeConfigBootstrap()
    for _ in range(3):
        boot.ensure_runtime_config_files()

    assert fake_env_file.parent.is_dir()
    assert fake_data_dir.is_dir()
    assert fake_env_file.exists()

    # load_env_file 也应可幂等调用（空文件也应静默返回）
    for _ in range(3):
        boot.load_env_file()


def test_get_settings_reflects_monkeypatched_main_attr(monkeypatch):
    """`get_settings()` 每次现读 `main` 属性；monkeypatch 后立即反映。

    这是 wrapper "读时求值"语义的通用回归——不只是 storage 三件套。
    """
    import main

    from app.shared.settings import get_settings

    original = main.CANVAS_DIR
    assert get_settings().canvas_dir == original
    monkeypatch.setattr(main, "CANVAS_DIR", "/tmp/patched_canvas_dir")
    assert get_settings().canvas_dir == "/tmp/patched_canvas_dir"
    # monkeypatch 会在 fixture teardown 里恢复原值；本函数返回后 main.CANVAS_DIR
    # 会回到 `original`。此处不能内联断言 teardown 效果——teardown 尚未执行。


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("local_personal", "local_personal"),
        ("INTRANET_TEAM", "intranet_team"),
        (" Public_Team ", "public_team"),
    ],
)
def test_deployment_mode_supports_all_modes_case_insensitively(
    monkeypatch, raw_value, expected
):
    from app.shared.settings import DeploymentMode, get_settings

    monkeypatch.setenv("IC_DEPLOYMENT_MODE", raw_value)
    settings = get_settings()

    assert settings.deployment_mode is DeploymentMode(expected)


def test_deployment_mode_defaults_to_current_local_behavior(monkeypatch):
    from app.shared.settings import DeploymentMode, get_settings

    monkeypatch.delenv("IC_DEPLOYMENT_MODE", raising=False)
    settings = get_settings()

    assert settings.deployment_mode is DeploymentMode.LOCAL_PERSONAL
    assert settings.bind_host == "0.0.0.0"
    assert settings.bind_port == 3000
    assert settings.cors_allowed_origins == ("*",)
    assert settings.csrf_enabled is False
    assert settings.enable_require_auth is False
    assert settings.enable_admin_only_endpoints is False
    assert settings.file_url_mode == "legacy"


@pytest.mark.parametrize("raw_value", ["", "local", "public", "unknown"])
def test_invalid_deployment_mode_fails_fast(monkeypatch, raw_value):
    from app.shared.settings import get_settings

    monkeypatch.setenv("IC_DEPLOYMENT_MODE", raw_value)
    with pytest.raises(ValueError, match="Invalid IC_DEPLOYMENT_MODE"):
        get_settings()


def test_deployment_settings_are_immutable_until_process_restart(monkeypatch):
    from app.shared.settings import DeploymentMode, get_settings

    monkeypatch.setenv("IC_DEPLOYMENT_MODE", "local_personal")
    first = get_settings()
    assert first.deployment_mode is DeploymentMode.LOCAL_PERSONAL

    monkeypatch.setenv("IC_DEPLOYMENT_MODE", "intranet_team")
    second = get_settings()

    assert second is not first, "get_settings() 仍应按次组装动态路径快照"
    assert second.deployment_mode is DeploymentMode.LOCAL_PERSONAL
    assert second.csrf_enabled is first.csrf_enabled
    assert second.enable_require_auth is first.enable_require_auth
    assert second.enable_admin_only_endpoints is first.enable_admin_only_endpoints


def test_private_reset_helper_models_process_restart(monkeypatch):
    from app.shared.settings import DeploymentMode, get_settings
    from app.shared.settings.runtime import _reset_settings_cache_for_tests

    monkeypatch.setenv("IC_DEPLOYMENT_MODE", "local_personal")
    assert get_settings().deployment_mode is DeploymentMode.LOCAL_PERSONAL

    monkeypatch.setenv("IC_DEPLOYMENT_MODE", "public_team")
    _reset_settings_cache_for_tests()
    assert get_settings().deployment_mode is DeploymentMode.PUBLIC_TEAM


def test_dynamic_paths_and_stable_deployment_share_one_settings(monkeypatch):
    """路径 monkeypatch 生效，但同进程 deployment 快照保持不变。"""
    import main

    from app.shared.settings import DeploymentMode, Settings, get_settings

    monkeypatch.setenv("IC_DEPLOYMENT_MODE", "intranet_team")
    first = get_settings()

    monkeypatch.setenv("IC_DEPLOYMENT_MODE", "public_team")
    monkeypatch.setattr(main, "CANVAS_DIR", "/tmp/recomputed_canvas_dir")
    second = get_settings()

    assert isinstance(first, Settings)
    assert isinstance(second, Settings)
    assert second.canvas_dir == "/tmp/recomputed_canvas_dir"
    assert second.deployment_mode is DeploymentMode.INTRANET_TEAM


def test_private_reset_helper_is_not_public_api():
    import app.shared.settings as settings_package

    assert "_reset_settings_cache_for_tests" not in settings_package.__all__
    assert not hasattr(settings_package, "_reset_settings_cache_for_tests")


def test_settings_snapshot_contains_no_secret_values(monkeypatch):
    """Settings 只读快照不得吸收同进程中的凭据环境变量。"""
    from app.shared.settings import get_settings

    sentinel = "sk-DEPLOYMENT-PR01-MUST-NOT-LEAK"
    monkeypatch.setenv("OPENAI_API_KEY", sentinel)
    monkeypatch.setenv("IC_SESSION_SECRET", sentinel)
    monkeypatch.setenv("AUTHORIZATION", sentinel)

    snapshot = dataclasses.asdict(get_settings())
    assert sentinel not in repr(snapshot)
    assert not {
        "api_key",
        "authorization",
        "token",
        "session_secret",
    }.intersection(snapshot)


# ---------------------------------------------------------------------------
# 数据 PR-8（Wave 3-G）：3 类低风险 domain 主写门禁 env 映射与 fail-fast
# 数据 PR-9（Wave 3-H）：AssetLibrary 主写门禁 env 映射与 fail-fast
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field_name", "const_name", "env_key"),
    [
        ("project_primary_write", "PROJECT_PRIMARY_WRITE", "PROJECT_PRIMARY_WRITE"),
        (
            "prompt_library_primary_write",
            "PROMPT_LIBRARY_PRIMARY_WRITE",
            "PROMPT_LIBRARY_PRIMARY_WRITE",
        ),
        (
            "workflow_definition_primary_write",
            "WORKFLOW_DEFINITION_PRIMARY_WRITE",
            "WORKFLOW_DEFINITION_PRIMARY_WRITE",
        ),
        (
            "asset_library_primary_write",
            "ASSET_LIBRARY_PRIMARY_WRITE",
            "ASSET_LIBRARY_PRIMARY_WRITE",
        ),
    ],
)
def test_pr8_primary_write_default_is_json(monkeypatch, field_name, const_name, env_key):
    """4 类新 domain 默认（env 未设 / main 常量为空）→ `"json"`。

    数据 PR-9 追加 AssetLibrary（原 3 类 PR-8 扩至 4 类）。
    """

    import main

    from app.shared.settings import get_settings

    monkeypatch.setattr(main, const_name, "json")
    s = get_settings()
    assert getattr(s, field_name) == "json"


@pytest.mark.parametrize(
    ("field_name", "const_name"),
    [
        ("project_primary_write", "PROJECT_PRIMARY_WRITE"),
        ("prompt_library_primary_write", "PROMPT_LIBRARY_PRIMARY_WRITE"),
        ("workflow_definition_primary_write", "WORKFLOW_DEFINITION_PRIMARY_WRITE"),
        ("asset_library_primary_write", "ASSET_LIBRARY_PRIMARY_WRITE"),
    ],
)
def test_pr8_primary_write_db_mode_accepted(monkeypatch, field_name, const_name):
    """`db` 值合法（大小写不敏感）。"""

    import main

    from app.shared.settings import get_settings

    monkeypatch.setattr(main, const_name, "DB")
    s = get_settings()
    assert getattr(s, field_name) == "db"


@pytest.mark.parametrize(
    "const_name",
    [
        "PROJECT_PRIMARY_WRITE",
        "PROMPT_LIBRARY_PRIMARY_WRITE",
        "WORKFLOW_DEFINITION_PRIMARY_WRITE",
        "ASSET_LIBRARY_PRIMARY_WRITE",
    ],
)
def test_pr8_invalid_primary_write_fails_fast_at_settings(monkeypatch, const_name):
    """未知值必须在 `Settings` 构造期抛 `ValueError`（P0 硬约束 #7）。"""

    import main

    from app.shared.settings import get_settings

    monkeypatch.setattr(main, const_name, "invalid")
    with pytest.raises(ValueError, match=f"Invalid {const_name}"):
        get_settings()


# ---------------------------------------------------------------------------
# 数据 PR-11（Wave 3-N.6 Batch 1 主线 A）：Task 层事实存储门禁 env 映射与 fail-fast
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("memory", "memory"),
        ("MEMORY", "memory"),
        (" memory ", "memory"),
        ("sqlite", "sqlite"),
        ("SQLite", "sqlite"),
    ],
)
def test_pr11_task_primary_write_accepted_values(monkeypatch, raw_value, expected):
    """`TASK_PRIMARY_WRITE` 接受 `memory` / `sqlite`（大小写不敏感、strip 后）。

    数据 PR-11 承接 PR-9 pattern；本 PR **只加机制不切默认**（默认 `memory`）。
    """

    import main

    from app.shared.settings import get_settings

    monkeypatch.setattr(main, "TASK_PRIMARY_WRITE", raw_value)
    s = get_settings()
    assert s.task_primary_write == expected


@pytest.mark.parametrize("raw_value", [None, ""])
def test_pr11_task_primary_write_default_is_memory(monkeypatch, raw_value):
    """未设 / 空值 → 默认 `"memory"`（Task 层默认沿用 memory 承接 PR-0）。"""

    import main

    from app.shared.settings import get_settings

    monkeypatch.setattr(main, "TASK_PRIMARY_WRITE", raw_value)
    s = get_settings()
    assert s.task_primary_write == "memory"


@pytest.mark.parametrize("raw_value", ["json", "db", "postgres", "unknown"])
def test_pr11_invalid_task_primary_write_fails_fast_at_settings(monkeypatch, raw_value):
    """未知值必须在 `Settings` 构造期抛 `ValueError`（fail-fast · P0 硬约束）。

    值域 `{"memory","sqlite"}` 之外全部拒绝；错误消息含 allowed set。
    """

    import main

    from app.shared.settings import get_settings

    monkeypatch.setattr(main, "TASK_PRIMARY_WRITE", raw_value)
    with pytest.raises(ValueError, match="Invalid TASK_PRIMARY_WRITE") as exc_info:
        get_settings()
    # 错误消息必须列出 allowed set（memory / sqlite）供操作者定位
    msg = str(exc_info.value)
    assert "memory" in msg
    assert "sqlite" in msg
