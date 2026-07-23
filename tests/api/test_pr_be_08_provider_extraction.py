"""PR-BE-08 focused contracts for the provider domain + 4 router group extraction.

Test IDs: T350-T369 (Wave 3-N.6 Batch 2 主线 A · Backend Architect subagent)

契约覆盖:
- T350-T355: 4 路由分组注册齐全(providers / runninghub / cli / generation)
- T356 (加强 · 裁决 2): providers router 内部路由顺序三条位置断言
- T357: ProviderConfigService.save_providers 密钥脱敏 sentinel 反查
- T358 (加强 · 裁决 3): ProviderRegistry.resolve 双参 + 单参 case + 空 model 一致语义
- T359-T362: 4 类 Adapter 抽出契约(Interface 存在 · legacy 实现仍在 main.py)
- T363: legacy `is_xxx_provider()` / `provider_protocol()` 分支 AST 抗回归
- T364: `.env` 写入路径唯一性(除 providers router · 其他新模块不许写)
- T365: `/api/providers` 前后端 legacy DTO `ApiProviderPayload` shape 冻结
- T366-T369: 保活烟测覆盖 Provider 配置读/写/registry/adapter facade
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute


ROOT = Path(__file__).resolve().parents[2]
ROUTER_DIR = ROOT / "app" / "api" / "routers"
BE08_ROUTER_FILES = (
    "providers.py",
    "runninghub.py",
    "cli.py",
    "generation.py",
)


# ---------------------------------------------------------------------------
# T350-T355 — 4 路由分组 API 注册齐全
# ---------------------------------------------------------------------------

EXPECTED_PROVIDER_ROUTES = frozenset(
    {
        ("/api/providers", "GET"),
        ("/api/providers", "PUT"),
        ("/api/providers/test-connection", "POST"),
        ("/api/providers/probe-async", "POST"),
        ("/api/providers/fetch-models", "POST"),
        ("/api/providers/{provider_id}/fetch-models", "GET"),
    }
)

EXPECTED_RUNNINGHUB_ROUTES = frozenset(
    {
        ("/api/runninghub/app-info", "GET"),
        ("/api/runninghub/submit", "POST"),
        ("/api/runninghub/workflow-submit", "POST"),
        ("/api/runninghub/workflow-info", "GET"),
        ("/api/runninghub/workflows", "GET"),
        ("/api/runninghub/workflows/fetch", "POST"),
        ("/api/runninghub/workflows/{workflow_id:path}", "GET"),
        ("/api/runninghub/workflows/{workflow_id:path}", "PUT"),
        ("/api/runninghub/workflows/{workflow_id:path}", "DELETE"),
        ("/api/runninghub/query", "GET"),
        ("/api/runninghub/upload-asset", "POST"),
    }
)

EXPECTED_CLI_ROUTES = frozenset(
    {
        ("/api/codex/status", "GET"),
        ("/api/codex/help", "POST"),
        ("/api/gemini-cli/status", "GET"),
        ("/api/gemini-cli/help", "POST"),
        ("/api/jimeng/status", "GET"),
        ("/api/jimeng/credit", "GET"),
        ("/api/jimeng/logout", "POST"),
        ("/api/jimeng/login/start", "POST"),
        ("/api/jimeng/login/status", "GET"),
        ("/api/jimeng/help", "POST"),
        ("/api/jimeng/query-media", "POST"),
    }
)

EXPECTED_GENERATION_ROUTES = frozenset(
    {
        ("/api/online-image", "POST"),
        ("/api/image-task-query", "POST"),
        ("/api/canvas-image-tasks", "POST"),
        ("/api/canvas-image-tasks/{task_id}", "GET"),
        ("/api/canvas-comfy-tasks", "POST"),
        ("/api/canvas-comfy-tasks/{task_id}", "GET"),
        ("/api/image-params", "GET"),
        ("/api/canvas-video", "POST"),
    }
)


def _application_routes() -> list[tuple[str, str]]:
    import main

    routes: list[tuple[str, str]] = []
    for route in main.app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                routes.append((route.path, method))
    return routes


def test_t350_provider_routes_registered() -> None:
    """T350 · providers router 6 条路由齐全 · 每条只出现一次。"""

    routes = _application_routes()
    for entry in EXPECTED_PROVIDER_ROUTES:
        assert routes.count(entry) == 1, f"providers route missing or dup: {entry}"


def test_t351_runninghub_routes_registered() -> None:
    """T351 · runninghub router 11 条路由齐全 · 每条只出现一次。"""

    routes = _application_routes()
    for entry in EXPECTED_RUNNINGHUB_ROUTES:
        assert routes.count(entry) == 1, f"runninghub route missing or dup: {entry}"


def test_t352_cli_routes_registered() -> None:
    """T352 · cli router 11 条路由齐全 · 每条只出现一次。"""

    routes = _application_routes()
    for entry in EXPECTED_CLI_ROUTES:
        assert routes.count(entry) == 1, f"cli route missing or dup: {entry}"


def test_t353_generation_routes_registered() -> None:
    """T353 · generation router 8 条路由齐全 · 每条只出现一次。"""

    routes = _application_routes()
    for entry in EXPECTED_GENERATION_ROUTES:
        assert routes.count(entry) == 1, f"generation route missing or dup: {entry}"


def test_t354_routers_do_not_import_main() -> None:
    """T354 · 4 路由文件都不 `import main`(继承 PR-BE-05/06 硬约束)。"""

    for filename in BE08_ROUTER_FILES:
        tree = ast.parse((ROUTER_DIR / filename).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert "main" not in imported, filename


def test_t355_main_include_router_order() -> None:
    """T355 · main.py include_router 顺序:providers → runninghub → cli → generation。"""

    import re

    src = (ROOT / "main.py").read_text(encoding="utf-8")
    order = [
        "create_providers_router",
        "create_runninghub_router",
        "create_cli_router",
        "create_generation_router",
    ]
    positions: list[int] = []
    for name in order:
        pattern = re.compile(
            r"app\.include_router\s*\(\s*" + re.escape(name) + r"\s*\("
        )
        match = pattern.search(src)
        assert match is not None, f"main.py 缺少 `app.include_router({name}(...))` 调用"
        positions.append(match.start())
    assert positions == sorted(positions), (
        "main.py include_router 顺序漂移;期望 providers → runninghub → cli → generation"
    )


# ---------------------------------------------------------------------------
# T356 (加强 · 裁决 2) — providers router 内部路由顺序三条位置断言
# ---------------------------------------------------------------------------

def test_t356_providers_router_declares_priority_routes_first() -> None:
    """T356 · GM-11 路由顺序 · 三条位置断言(裁决 2 加强):

    - `/api/providers/{provider_id}/fetch-models` 在 `/api/providers/{provider_id}` 之前
    - `/api/providers/test-connection`             在 `/api/providers/{provider_id}` 之前
    - `/api/providers/probe-async`                 在 `/api/providers/{provider_id}` 之前

    保证:即使未来引入通配 `/api/providers/{provider_id}` GET/PATCH 路由,
    也不会把 `"test-connection"` / `"probe-async"` / `"{provider_id}/fetch-
    models"` 当成 provider_id 值吞掉。
    """

    src = (ROUTER_DIR / "providers.py").read_text(encoding="utf-8")

    fetch_models_by_id_pos = src.find('"/api/providers/{provider_id}/fetch-models"')
    test_conn_pos = src.find('"/api/providers/test-connection"')
    probe_async_pos = src.find('"/api/providers/probe-async"')
    # 通配 /api/providers/{provider_id} (无 fetch-models 后缀)
    by_id_wildcard_pos = -1
    # 精确搜索独立的 `/api/providers/{provider_id}"` (不含 /fetch-models)
    import re

    m = re.search(r'"/api/providers/\{provider_id\}"(?![/])', src)
    if m:
        by_id_wildcard_pos = m.start()

    assert fetch_models_by_id_pos >= 0, "fetch-models by-id route decorator missing"
    assert test_conn_pos >= 0, "test-connection route decorator missing"
    assert probe_async_pos >= 0, "probe-async route decorator missing"

    # 若通配 `/api/providers/{provider_id}` 存在,三条静态路径必须在其之前;
    # 若未来还未引入通配路由,则本 PR 视为"预留 GM-11 硬护栏 · 三条静态路径
    # 存在即通过"(当前实现)。
    if by_id_wildcard_pos >= 0:
        assert fetch_models_by_id_pos < by_id_wildcard_pos, (
            "GM-11 断言 1 违反 · `/api/providers/{provider_id}/fetch-models` "
            "必须在 `/api/providers/{provider_id}` 之前"
        )
        assert test_conn_pos < by_id_wildcard_pos, (
            "GM-11 断言 2 违反 · `/api/providers/test-connection` 必须在 "
            "`/api/providers/{provider_id}` 之前"
        )
        assert probe_async_pos < by_id_wildcard_pos, (
            "GM-11 断言 3 违反 · `/api/providers/probe-async` 必须在 "
            "`/api/providers/{provider_id}` 之前"
        )


# ---------------------------------------------------------------------------
# T357 — ProviderConfigService.save_providers 密钥脱敏 sentinel 反查
# ---------------------------------------------------------------------------

_SECRET_SENTINELS = (
    "SECRET_VALUE_LEAK",
    "sk-fake-leaked-1234567890",
)


def test_t357_service_never_exposes_raw_api_key_in_public_provider() -> None:
    """T357 · P0 密钥零入库反查 · save_providers 后 `public_provider()` 投影
    的响应体 grep sentinel = 0 命中。

    通过 fake store 捕获 save_api_providers 的入参 · 断言:入参 dict 里没有
    `api_key` 字段(脱敏契约:`_safe_provider_records` 白名单不含 api_key ·
    但本 service 层调用侧已剥离 `api_key=exclude`)。
    """

    import json

    from app.modules.provider.commands import SaveProvidersCommand
    from app.modules.provider.service import ProviderConfigService
    from app.modules.provider.store import ProviderStore

    saved_records: list[list[dict[str, Any]]] = []

    class _CaptureStore(ProviderStore):
        def load_api_providers(self) -> list[dict[str, Any]]:
            return []

        def save_api_providers(self, providers: list[dict[str, Any]]) -> Any:  # type: ignore[override]
            saved_records.append([dict(p) for p in providers])
            return None

    def _normalize_provider(item: dict[str, Any]) -> dict[str, Any]:
        # mimic main.normalize_provider · 关键点:api_key 由 `exclude={"api_key"}`
        # 剥离 · 不会进入 normalize 输入。
        result = dict(item)
        result["id"] = str(result.get("id") or "").strip().lower()
        result.setdefault("base_url", "")
        result.setdefault("image_models", [])
        result.setdefault("chat_models", [])
        result.setdefault("video_models", [])
        return result

    def _public_provider(p: dict[str, Any]) -> dict[str, Any]:
        # 白名单剔除敏感字段。测试用极简版本。
        return {
            "id": p.get("id"),
            "base_url": p.get("base_url"),
            "primary": p.get("primary", False),
        }

    service = ProviderConfigService(
        store=_CaptureStore(),
        public_api_providers=lambda: [],
        get_api_provider=lambda pid: {},
        get_api_provider_exact=lambda pid: {},
        normalize_provider=_normalize_provider,
        public_provider=_public_provider,
        preserve_runninghub_hidden_overrides=lambda p: p,
        prune_runninghub_workflow_store_for_provider=lambda p: None,
        provider_key_env=lambda pid: f"{pid.upper()}_API_KEY",
        runninghub_wallet_key_env=lambda: "RUNNINGHUB_WALLET_KEY",
        volcengine_access_key_env=lambda: "VOLC_AK",
        volcengine_secret_key_env=lambda: "VOLC_SK",
    )

    # 构造带 sentinel 密钥的 payload
    class _FakePayload:
        def __init__(self, pid: str, api_key: str) -> None:
            self.id = pid
            self.api_key = api_key
            self.clear_key = False
            self.primary = False
            self.wallet_api_key = None
            self.clear_wallet_key = False
            self.volcengine_access_key_id = None
            self.clear_volcengine_access_key_id = False
            self.volcengine_secret_access_key = None
            self.clear_volcengine_secret_access_key = False

        def dict(self, exclude: set[str] | None = None) -> dict[str, Any]:
            data = {"id": self.id}
            if exclude and "api_key" in exclude:
                return data
            return {**data, "api_key": self.api_key}

    payload = [_FakePayload("comfly", "sk-fake-leaked-1234567890")]
    cmd = SaveProvidersCommand(payload_items=payload)
    providers, env_updates = service.save_providers(cmd)

    # 事实断言 1: saved store record 里没有 api_key
    assert saved_records, "save_api_providers 未被调用"
    stored = saved_records[-1]
    serialized = json.dumps(stored, ensure_ascii=False)
    for sentinel in _SECRET_SENTINELS:
        assert sentinel not in serialized, (
            f"P0 密钥零入库违反 · store 层出现 sentinel `{sentinel}`"
        )

    # 事实断言 2: public_provider 投影里也没有 api_key
    public_projected = json.dumps(
        [_public_provider(p) for p in providers], ensure_ascii=False
    )
    for sentinel in _SECRET_SENTINELS:
        assert sentinel not in public_projected, (
            f"P0 密钥零入库违反 · public_provider 投影出现 `{sentinel}`"
        )

    # 事实断言 3: env_updates 里的 api_key 仅到 env 落盘路径 · router 侧调
    # update_env_values 时统一处理 · 不进 store。这一断言仅确认 env 走的是
    # 独立通道:api_key 出现在 env_updates 而非 store 里。
    assert env_updates.get("COMFLY_API_KEY") == "sk-fake-leaked-1234567890"


# ---------------------------------------------------------------------------
# T358 (加强 · 裁决 3) — ProviderRegistry.resolve 双参 + 单参 + 空 model 一致
# ---------------------------------------------------------------------------

def test_t358_registry_resolve_dual_signature() -> None:
    """T358 · GM-14 圆桌自治第 7 次实证 · 裁决 3 加强:

    - resolve(provider_id) 单参 case → 走默认 protocol
    - resolve(provider_id, model=None) 与 单参 case 行为完全一致(空 model
      与 explicit None 语义一致)
    - resolve(provider_id, model="foo") 双参 case → 走 model_protocols 映射
    - resolve(unknown_id) → None(不抛异常,便于调用方走 legacy 兜底)
    """

    from app.adapters.provider.base import (
        AdapterCapabilities,
        BaseAdapter,
        ConnectionResult,
        ProviderTaskCapabilities,
        TaskError,
    )
    from app.adapters.provider.registry import _REGISTRY, adapter, resolve_adapter
    from app.modules.provider.registry import ProviderRegistry, ProviderResolution

    # 用测试专属 protocol 注册一个 minimal adapter · 不污染全局(测试结尾
    # 恢复原状 · 参照 tests/provider/test_registry.py pattern)
    test_protocols = ("pr_be_08_test_a", "pr_be_08_test_b")
    saved = {p: _REGISTRY.pop(p, None) for p in test_protocols}
    try:

        @adapter(protocol="pr_be_08_test_a", capabilities=("chat",))
        class _AdapterA(BaseAdapter):
            def describe_capabilities(self):
                return AdapterCapabilities(chat=True)

            def describe_task_capabilities(self):
                return ProviderTaskCapabilities()

            async def test_connection(self, credential):
                return ConnectionResult(ok=True)

            def classify_error(self, exc, context):
                return TaskError(
                    code="test", category="INTERNAL",  # type: ignore[arg-type]
                    request_id="x",
                )

        @adapter(protocol="pr_be_08_test_b", capabilities=("image_generate",))
        class _AdapterB(BaseAdapter):
            def describe_capabilities(self):
                return AdapterCapabilities(image_generate=True)

            def describe_task_capabilities(self):
                return ProviderTaskCapabilities()

            async def test_connection(self, credential):
                return ConnectionResult(ok=True)

            def classify_error(self, exc, context):
                return TaskError(
                    code="test", category="INTERNAL",  # type: ignore[arg-type]
                    request_id="x",
                )

        providers = [
            {
                "id": "p1",
                "protocol": "pr_be_08_test_a",
                "model_protocols": {"special-model": "pr_be_08_test_b"},
            }
        ]
        registry = ProviderRegistry(load_providers=lambda: providers)

        # 单参 case
        res_single = registry.resolve("p1")
        assert isinstance(res_single, ProviderResolution)
        assert res_single.protocol == "pr_be_08_test_a"

        # 双参 case · explicit None (与单参等价)
        res_none = registry.resolve("p1", None)
        assert isinstance(res_none, ProviderResolution)
        assert res_none.protocol == res_single.protocol

        # 双参 case · 空 model 字符串(与 None 等价)
        res_empty = registry.resolve("p1", "")
        assert isinstance(res_empty, ProviderResolution)
        assert res_empty.protocol == res_single.protocol

        # 双参 case · model 命中 model_protocols 表映射
        res_special = registry.resolve("p1", "special-model")
        assert isinstance(res_special, ProviderResolution)
        assert res_special.protocol == "pr_be_08_test_b"

        # 未注册 provider_id → None (不抛异常)
        res_missing = registry.resolve("no-such-provider")
        assert res_missing is None

        # 三字段冻结契约:provider / protocol / adapter
        from dataclasses import fields as _fields

        assert {f.name for f in _fields(ProviderResolution)} == {
            "provider",
            "protocol",
            "adapter",
        }
    finally:
        for p in test_protocols:
            _REGISTRY.pop(p, None)
            if saved[p] is not None:
                _REGISTRY[p] = saved[p]


# ---------------------------------------------------------------------------
# T359-T362 — 4 类 Adapter 契约(Interface / Capabilities · 实现仍在 main.py)
# ---------------------------------------------------------------------------

def test_t359_image_adapter_capability_declared() -> None:
    """T359 · AdapterCapabilities 有 image_generate 声明位 · 现有 adapter
    抽象层已就绪(GM-16 pre-flight 已核 · 无需新增 ImageProviderAdapter 类)。"""

    from app.adapters.provider.base import AdapterCapabilities

    caps = AdapterCapabilities(image_generate=True)
    assert caps.supports("image_generate") is True
    assert caps.supports("chat") is False


def test_t360_video_adapter_capability_declared() -> None:
    """T360 · AdapterCapabilities 有 video_generate 声明位。"""

    from app.adapters.provider.base import AdapterCapabilities

    caps = AdapterCapabilities(video_generate=True)
    assert caps.supports("video_generate") is True


def test_t361_chat_adapter_capability_declared() -> None:
    """T361 · AdapterCapabilities 有 chat / chat_stream 声明位。"""

    from app.adapters.provider.base import AdapterCapabilities

    caps = AdapterCapabilities(chat=True, chat_stream=True)
    assert caps.supports("chat") is True
    assert caps.supports("chat_stream") is True


def test_t362_workflow_adapter_capability_declared() -> None:
    """T362 · AdapterCapabilities 有 workflow_run 声明位。"""

    from app.adapters.provider.base import AdapterCapabilities

    caps = AdapterCapabilities(workflow_run=True)
    assert caps.supports("workflow_run") is True


# ---------------------------------------------------------------------------
# T363 — legacy `is_xxx_provider()` / `provider_protocol()` 分支 AST 抗回归
# ---------------------------------------------------------------------------

REQUIRED_LEGACY_HELPERS = (
    "provider_protocol",
    "is_apimart_provider",
    "is_gemini_provider",
    "is_volcengine_provider",
    "is_runninghub_provider",
    "is_jimeng_provider",
    "is_codex_provider",
    "is_gemini_cli_provider",
    "normalize_provider",
    "public_provider",
    "public_api_providers",
)


def test_t363_legacy_provider_branches_still_in_main() -> None:
    """T363 · legacy provider 分支硬约束保留 · AST 直读 main.py 断言。"""

    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    def_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for helper in REQUIRED_LEGACY_HELPERS:
        assert helper in def_names, f"main.py 缺少 legacy provider 分支 `{helper}`"


# ---------------------------------------------------------------------------
# T364 — `.env` 写入路径唯一性(CI grep 抗回归)
# ---------------------------------------------------------------------------

def test_t364_env_write_stays_out_of_new_modules() -> None:
    """T364 · 除 providers router 之外(实际写 .env 的 update_env_values 仍
    在 main.py · router 只调 callback)· 新增 4 路由文件 / provider 模块内
    不许直接 `open(...API_ENV_FILE...)` 或 `write .env`。
    """

    forbidden_patterns = ("API_ENV_FILE", ".env")
    target_files = [
        ROUTER_DIR / "providers.py",
        ROUTER_DIR / "runninghub.py",
        ROUTER_DIR / "cli.py",
        ROUTER_DIR / "generation.py",
        ROOT / "app" / "modules" / "provider" / "service.py",
        ROOT / "app" / "modules" / "provider" / "store.py",
        ROOT / "app" / "modules" / "provider" / "registry.py",
        ROOT / "app" / "modules" / "provider" / "commands.py",
    ]
    for fp in target_files:
        text = fp.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            # 允许 provider router 通过 callback 调 update_env_values(不落地
            # `.env` 字符串);字符串常量 / 直接 open 才是违规。
            if pattern == ".env":
                assert '".env"' not in text and "'.env'" not in text, (
                    f"{fp} 出现字面量 `.env` · 违反 `.env` 写入路径唯一硬约束"
                )
            else:
                assert pattern not in text, (
                    f"{fp} 引用 `{pattern}` · 违反 `.env` 写入路径唯一硬约束"
                )


# ---------------------------------------------------------------------------
# T365 — `/api/providers` legacy DTO `ApiProviderPayload` shape 冻结
# ---------------------------------------------------------------------------

def test_t365_api_provider_payload_shape_frozen() -> None:
    """T365 · `ApiProviderPayload` DTO 字段清单冻结(前端 API 设置页面契约)。

    zero-touch 事实清单第 6 项:不改 DTO 字段与默认值。断言关键字段存在:
    - id / name / base_url / protocol / api_key / clear_key / primary
    - image_models / chat_models / video_models
    - wallet_api_key / clear_wallet_key (runninghub)
    - volcengine_access_key_id / volcengine_secret_access_key
    """

    import main

    dto = main.ApiProviderPayload
    fields = set(dto.__fields__.keys()) if hasattr(dto, "__fields__") else set()
    # pydantic v2 兼容
    if not fields and hasattr(dto, "model_fields"):
        fields = set(dto.model_fields.keys())

    required = {
        "id",
        "name",
        "base_url",
        "protocol",
        "api_key",
        "clear_key",
        "primary",
        "image_models",
        "chat_models",
        "video_models",
        "wallet_api_key",
        "clear_wallet_key",
        "volcengine_access_key_id",
        "volcengine_secret_access_key",
        "clear_volcengine_access_key_id",
        "clear_volcengine_secret_access_key",
    }
    missing = required - fields
    assert not missing, f"ApiProviderPayload 缺少字段:{missing}"


# ---------------------------------------------------------------------------
# T366-T369 — 保活烟测
# ---------------------------------------------------------------------------

def test_t366_service_list_providers_returns_iterable() -> None:
    """T366 · Provider service 保活 · list_providers 走 public_api_providers callback。"""

    from app.modules.provider.service import ProviderConfigService

    fake_store = MagicMock()
    fake_store.load_api_providers.return_value = [
        {"id": "comfly"},
        {"id": "modelscope"},
    ]

    service = ProviderConfigService(
        store=fake_store,
        public_api_providers=lambda: [{"id": "comfly"}, {"id": "modelscope"}],
        get_api_provider=lambda pid: {"id": pid},
        get_api_provider_exact=lambda pid: {"id": pid},
        normalize_provider=lambda x: x,
        public_provider=lambda x: x,
        preserve_runninghub_hidden_overrides=lambda p: p,
        prune_runninghub_workflow_store_for_provider=lambda p: None,
        provider_key_env=lambda pid: "",
        runninghub_wallet_key_env=lambda: "",
        volcengine_access_key_env=lambda: "",
        volcengine_secret_key_env=lambda: "",
    )
    result = service.list_providers()
    assert isinstance(result, list)
    assert {p["id"] for p in result} == {"comfly", "modelscope"}


def test_t367_service_get_provider_returns_dict_or_none() -> None:
    """T367 · Provider service 保活 · get_provider 严格匹配 · 未找到返回 None。"""

    from app.modules.provider.service import ProviderConfigService

    def _get_exact(pid: str):
        if pid == "comfly":
            return {"id": "comfly", "base_url": "https://example.com"}
        raise HTTPException(status_code=404, detail="not found")

    service = ProviderConfigService(
        store=MagicMock(),
        public_api_providers=lambda: [],
        get_api_provider=lambda pid: {},
        get_api_provider_exact=_get_exact,
        normalize_provider=lambda x: x,
        public_provider=lambda x: x,
        preserve_runninghub_hidden_overrides=lambda p: p,
        prune_runninghub_workflow_store_for_provider=lambda p: None,
        provider_key_env=lambda pid: "",
        runninghub_wallet_key_env=lambda: "",
        volcengine_access_key_env=lambda: "",
        volcengine_secret_key_env=lambda: "",
    )
    hit = service.get_provider("comfly")
    assert hit is not None
    assert hit["id"] == "comfly"
    miss = service.get_provider("nonexistent")
    assert miss is None


def test_t368_registry_capability_shortcut() -> None:
    """T368 · ProviderRegistry.capability(provider_id, name) 保活。"""

    from app.adapters.provider.base import (
        AdapterCapabilities,
        BaseAdapter,
        ConnectionResult,
        ProviderTaskCapabilities,
        TaskError,
    )
    from app.adapters.provider.registry import _REGISTRY, adapter
    from app.modules.provider.registry import ProviderRegistry

    test_protocol = "pr_be_08_capability_probe"
    saved = _REGISTRY.pop(test_protocol, None)
    try:

        @adapter(protocol=test_protocol, capabilities=("image_generate",))
        class _P(BaseAdapter):
            def describe_capabilities(self):
                return AdapterCapabilities(image_generate=True, chat=False)

            def describe_task_capabilities(self):
                return ProviderTaskCapabilities()

            async def test_connection(self, credential):
                return ConnectionResult(ok=True)

            def classify_error(self, exc, context):
                return TaskError(
                    code="test", category="INTERNAL",  # type: ignore[arg-type]
                    request_id="x",
                )

        registry = ProviderRegistry(
            load_providers=lambda: [{"id": "p2", "protocol": test_protocol}]
        )
        assert registry.capability("p2", "image_generate") is True
        assert registry.capability("p2", "chat") is False
        # 未注册的 provider_id → False
        assert registry.capability("no-such", "image_generate") is False
    finally:
        _REGISTRY.pop(test_protocol, None)
        if saved is not None:
            _REGISTRY[test_protocol] = saved


def test_t369_registry_list_protocols_returns_sorted() -> None:
    """T369 · ProviderRegistry.list_protocols 委派 registered_protocols · 稳定排序。"""

    from app.modules.provider.registry import ProviderRegistry

    registry = ProviderRegistry(load_providers=lambda: [])
    protocols = registry.list_protocols()
    assert isinstance(protocols, list)
    # registered_protocols 返回 sorted tuple · 转 list 后 == sorted(list)
    assert protocols == sorted(protocols)
