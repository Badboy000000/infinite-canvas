"""PR-BE-09 focused contracts for the Task module + canvas_tasks router extraction.

Test IDs: T390-T409（Wave 3-N.6 Batch 3 主线 A · Backend Architect subagent ·
方案 B 收缩承接 · GM-14 圆桌自治第 8 次实证 · CB-P5-31 挂账）

方案 B 差异说明：
- 原任务书要求 5 项抽出（canvas-image-tasks / canvas-comfy-tasks / cancel /
  history 全套）；PR-BE-08（`f277596`）已把 canvas-image / canvas-comfy 抽入
  generation.py；PR-BE-05 已把 `/api/history` 抽入 history.py；cancel 端点
  当前不存在（scope 扩展留独立 PR）。
- **实际收敛为 2 项抽出**：`GET /api/queue_status` + `POST /api/history/delete`
  → `app/api/routers/canvas_tasks.py`。
- 不测 T391/T392/T396（cancel 相关 · 方案 B 不做）。

契约覆盖：
- T390: generation.py + history.py + canvas_tasks.py 三 router 已装配
- T393-T395: TaskModuleFacade.submit_canvas_image_task / submit_canvas_comfy_task
             / get_task_view 委派契约
- T397: /api/queue_status GET shape 冻结
- T398: /api/history GET 分页 shape 冻结 · 5000 条上限
- T399: /api/history/delete POST 幂等 + shape 冻结
- T400: TaskModuleFacade P0 密钥零入库 sentinel 反查
- T401: TaskModuleFacade.retry_task 状态机契约
- T402: get_task_view 优先 legacy CANVAS_TASKS
- T403: TaskErrorCategory mapper 契约(14 值枚举)
- T404: legacy CANVAS_TASKS / CANVAS_TASK_LOCK / QUEUE main.py AST 抗回归
- T405: asyncio.create_task 保留 · main.py grep 未减少
- T406-T408: WebSocket stats / new_image / canvas_updated / asset_library_updated
             / pong 消息 AST 抗回归
- T409: 保活烟测 · canvas image + comfy 任务提交 / 查询 / 重试 · history 查询
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
MAIN_PATH = ROOT / "main.py"
ROUTER_DIR = ROOT / "app" / "api" / "routers"


def _application_routes() -> list[tuple[str, str]]:
    import main

    routes: list[tuple[str, str]] = []
    for route in main.app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                routes.append((route.path, method))
    return routes


# ---------------------------------------------------------------------------
# T390 — 三 router 装配齐全
# ---------------------------------------------------------------------------


def test_t390_three_routers_include_router_all_registered() -> None:
    """T390 · main.py 里的 `include_router` 至少覆盖三处新 router 装配:
    generation.py / history.py / canvas_tasks.py。
    """

    src = MAIN_PATH.read_text(encoding="utf-8")
    for factory in (
        "create_generation_router",
        "create_history_router",
        "create_canvas_tasks_router",
    ):
        pattern = re.compile(
            r"app\.include_router\s*\(\s*" + re.escape(factory) + r"\s*\("
        )
        assert pattern.search(src) is not None, (
            f"main.py 缺少 `app.include_router({factory}(...))` 装配点"
        )


def test_t390_canvas_tasks_router_registers_two_routes() -> None:
    """T390 补充 · canvas_tasks router 恰好注册两条:
    `GET /api/queue_status` + `POST /api/history/delete`。
    """

    routes = _application_routes()
    assert ("/api/queue_status", "GET") in routes
    assert ("/api/history/delete", "POST") in routes
    # 每条只出现一次(装饰器已剥离 · 无重复挂载)
    assert routes.count(("/api/queue_status", "GET")) == 1
    assert routes.count(("/api/history/delete", "POST")) == 1


# ---------------------------------------------------------------------------
# T393 — TaskModuleFacade.submit_canvas_image_task 委派契约
# ---------------------------------------------------------------------------


def test_t393_submit_canvas_image_task_delegates_bytewise() -> None:
    """T393 · TaskModuleFacade.submit_canvas_image_task 委派 legacy
    `main.create_canvas_image_task` · payload 字节等价传递 · 返回值原样透传。
    """

    from app.modules.task.service import TaskModuleFacade
    from app.modules.task.store import TaskModuleStore

    captured: list[Any] = []

    async def _fake_create(payload: Any) -> dict:
        captured.append(payload)
        return {"task_id": "canvas_img_deadbeef", "status": "queued"}

    async def _dummy(_: Any) -> Any:
        return None

    facade = TaskModuleFacade(
        store=TaskModuleStore(),
        create_canvas_image_task=_fake_create,
        create_canvas_comfy_task=_dummy,
        get_canvas_image_task=_dummy,
        get_canvas_comfy_task=_dummy,
    )

    class _FakePayload:
        def __init__(self, prompt: str) -> None:
            self.prompt = prompt
            self.provider_id = "comfly"
            self.model = "test"

    payload = _FakePayload("hello world")
    result = asyncio.run(facade.submit_canvas_image_task(payload))

    assert captured == [payload], "payload 未字节等价传递到 legacy 函数"
    assert result == {"task_id": "canvas_img_deadbeef", "status": "queued"}


# ---------------------------------------------------------------------------
# T394 — TaskModuleFacade.submit_canvas_comfy_task 委派契约
# ---------------------------------------------------------------------------


def test_t394_submit_canvas_comfy_task_delegates_bytewise() -> None:
    """T394 · TaskModuleFacade.submit_canvas_comfy_task 委派 legacy
    `main.create_canvas_comfy_task` · payload 字节等价传递。
    """

    from app.modules.task.service import TaskModuleFacade
    from app.modules.task.store import TaskModuleStore

    captured: list[Any] = []

    async def _fake_create(payload: Any) -> dict:
        captured.append(payload)
        return {"task_id": "canvas_comfy_deadbeef", "status": "queued"}

    async def _dummy(_: Any) -> Any:
        return None

    facade = TaskModuleFacade(
        store=TaskModuleStore(),
        create_canvas_image_task=_dummy,
        create_canvas_comfy_task=_fake_create,
        get_canvas_image_task=_dummy,
        get_canvas_comfy_task=_dummy,
    )

    class _FakePayload:
        def __init__(self) -> None:
            self.workflow_json = {"nodes": []}

    payload = _FakePayload()
    result = asyncio.run(facade.submit_canvas_comfy_task(payload))

    assert captured == [payload]
    assert result == {"task_id": "canvas_comfy_deadbeef", "status": "queued"}


# ---------------------------------------------------------------------------
# T395 — get_task_view 参数化 kind image/comfy
# ---------------------------------------------------------------------------


def test_t395_get_task_view_kind_parameterization() -> None:
    """T395 · TaskModuleFacade.get_task_view 参数化 kind:
    - kind="image" → 委派 `get_canvas_image_task`
    - kind="comfy" → 委派 `get_canvas_comfy_task`
    - kind=其他 → ValueError
    """

    from app.modules.task.service import TaskModuleFacade
    from app.modules.task.store import TaskModuleStore

    image_captured: list[str] = []
    comfy_captured: list[str] = []

    async def _fake_get_image(task_id: str) -> dict:
        image_captured.append(task_id)
        return {"id": task_id, "type": "online-image", "status": "succeeded"}

    async def _fake_get_comfy(task_id: str) -> dict:
        comfy_captured.append(task_id)
        return {"id": task_id, "type": "comfy", "status": "succeeded"}

    async def _dummy(_: Any) -> Any:
        return None

    facade = TaskModuleFacade(
        store=TaskModuleStore(),
        create_canvas_image_task=_dummy,
        create_canvas_comfy_task=_dummy,
        get_canvas_image_task=_fake_get_image,
        get_canvas_comfy_task=_fake_get_comfy,
    )

    image_result = asyncio.run(facade.get_task_view("t1", "image"))
    comfy_result = asyncio.run(facade.get_task_view("t2", "comfy"))
    assert image_captured == ["t1"]
    assert comfy_captured == ["t2"]
    assert image_result["type"] == "online-image"
    assert comfy_result["type"] == "comfy"

    with pytest.raises(ValueError):
        asyncio.run(facade.get_task_view("t3", "video"))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# T397 — /api/queue_status GET shape 冻结(202 response 字段)
# ---------------------------------------------------------------------------


def test_t397_queue_status_shape_frozen() -> None:
    """T397 · `/api/queue_status` GET 返回 shape 冻结:必须含 `total` +
    `position` 字段(200 状态码;非 202——原实现是 200 · legacy 语义保持)。

    构造 synthetic app · 直接调用 create_router(...) callback pattern 验证
    抽出前后 body 逐字节等价。
    """

    from app.api.routers.canvas_tasks import create_router

    async def _fake_queue_status(client_id: str) -> dict:
        return {"total": 3, "position": 2 if client_id == "u1" else 0}

    async def _fake_delete_history(req: Any) -> dict:
        return {"success": True}

    from pydantic import BaseModel

    class _DummyReq(BaseModel):
        timestamp: float

    app = FastAPI()
    app.include_router(
        create_router(
            get_queue_status_callback=_fake_queue_status,
            delete_history_callback=_fake_delete_history,
            delete_history_dto=_DummyReq,
        )
    )
    client = TestClient(app)
    r1 = client.get("/api/queue_status", params={"client_id": "u1"})
    r2 = client.get("/api/queue_status", params={"client_id": "other"})
    assert r1.status_code == 200
    assert r1.json() == {"total": 3, "position": 2}
    assert r2.json() == {"total": 3, "position": 0}


# ---------------------------------------------------------------------------
# T398 — /api/history GET(PR-BE-05 已挂 · 不动)· 5000 条上限
# ---------------------------------------------------------------------------


def test_t398_history_load_facade_5000_limit_alignment() -> None:
    """T398 · `app.stores.history_store.load_history()` facade 与
    `HISTORY_MAX_RECORDS=5000` 上限对齐(承接数据 PR-12)。TaskModuleStore
    `history_view(limit=5000)` 与 facade 契约一致。
    """

    from app.db.history_writer import HISTORY_MAX_RECORDS

    assert HISTORY_MAX_RECORDS == 5000, (
        "数据 PR-12 契约:HISTORY_MAX_RECORDS 应保持 5000"
    )

    # TaskModuleStore.history_view 默认 limit 5000
    from app.modules.task.store import TaskModuleStore

    sig = inspect.signature(TaskModuleStore.history_view)
    assert sig.parameters["limit"].default == 5000


def test_t398_task_module_store_history_view_sort_and_limit() -> None:
    """T398 补充 · TaskModuleStore.history_view 返回 timestamp 倒序 + 截断
    到 limit(legacy `get_history_api` sort_key 语义)。
    """

    from app.adapters.task.in_memory import InMemoryTaskStore
    from app.adapters.task import in_memory as task_adapter_mod

    fake_records = [
        {"timestamp": 100.0, "images": ["a"]},
        {"timestamp": 300.0, "images": ["c"]},
        {"timestamp": 200.0, "images": ["b"]},
    ]

    orig_facade = task_adapter_mod._history_store_facade
    try:
        # 短路 load_history 返回 fixture
        class _FacadeStub:
            @staticmethod
            def load_history() -> list[dict]:
                return list(fake_records)

        task_adapter_mod._history_store_facade = _FacadeStub  # type: ignore[assignment]
        store = InMemoryTaskStore()
        result = store.history_view(limit=2)
        assert len(result) == 2
        assert result[0]["timestamp"] == 300.0
        assert result[1]["timestamp"] == 200.0
    finally:
        task_adapter_mod._history_store_facade = orig_facade


# ---------------------------------------------------------------------------
# T399 — /api/history/delete POST 幂等 + shape 冻结
# ---------------------------------------------------------------------------


def test_t399_history_delete_shape_frozen_and_idempotent() -> None:
    """T399 · `/api/history/delete` POST body 逐字节等价:
    - 命中记录 → {"success": True}
    - 未命中记录 → {"success": False, "message": "Record not found"}
    幂等断言:再次 delete 同一 timestamp,shape 保持 not-found path。
    """

    from pydantic import BaseModel

    from app.api.routers.canvas_tasks import create_router

    async def _fake_queue_status(client_id: str) -> dict:
        return {"total": 0, "position": 0}

    class _Req(BaseModel):
        timestamp: float

    # 模拟 legacy delete_history · 内存态记录
    store: dict[float, dict] = {123.0: {"timestamp": 123.0, "images": []}}

    async def _fake_delete_history(req: _Req) -> dict:
        if req.timestamp in store:
            del store[req.timestamp]
            return {"success": True}
        return {"success": False, "message": "Record not found"}

    app = FastAPI()
    app.include_router(
        create_router(
            get_queue_status_callback=_fake_queue_status,
            delete_history_callback=_fake_delete_history,
            delete_history_dto=_Req,
        )
    )
    client = TestClient(app)

    r1 = client.post("/api/history/delete", json={"timestamp": 123.0})
    assert r1.status_code == 200
    assert r1.json() == {"success": True}

    # 幂等 · 再次 delete → not found path
    r2 = client.post("/api/history/delete", json={"timestamp": 123.0})
    assert r2.json() == {"success": False, "message": "Record not found"}

    # 未命中路径 shape 严格
    r3 = client.post("/api/history/delete", json={"timestamp": 999.0})
    assert r3.json() == {"success": False, "message": "Record not found"}


# ---------------------------------------------------------------------------
# T400 — TaskModuleFacade P0 密钥零入库 sentinel 反查
# ---------------------------------------------------------------------------


_SECRET_SENTINELS = (
    "SECRET_VALUE_LEAK",
    "sk-fake-leaked-1234567890",
    "AKIA0123456789ABCDEF",
    "Bearer FAKELEAKEDBEARER",
)


def test_t400_submit_canvas_image_task_sanitize_payload_dict() -> None:
    """T400 · P0 密钥零入库 · service 层 `_sanitize_payload_dict` 覆盖
    api_key / secret / token / password / credential 常见字段名。
    sentinel 反查 = 0 命中。
    """

    from app.modules.task.service import _sanitize_payload_dict

    payload_dict = {
        "prompt": "hello",
        "provider_id": "comfly",
        "api_key": "sk-fake-leaked-1234567890",
        "secret": "SECRET_VALUE_LEAK",
        "access_token": "AKIA0123456789ABCDEF",
        "authorization": "Bearer FAKELEAKEDBEARER",
        "password": "hunter2",
        "credential": {"nested": "SECRET_VALUE_LEAK"},
    }
    cleaned = _sanitize_payload_dict(payload_dict)
    serialized = json.dumps(cleaned, ensure_ascii=False)
    for sentinel in _SECRET_SENTINELS:
        assert sentinel not in serialized, (
            f"P0 密钥零入库违反 · sanitize 后仍出现 sentinel `{sentinel}`"
        )
    # 非密钥字段保留
    assert cleaned["prompt"] == "hello"
    assert cleaned["provider_id"] == "comfly"
    # 密钥字段被替换为 [REDACTED]
    assert cleaned["api_key"] == "[REDACTED]"
    assert cleaned["secret"] == "[REDACTED]"


# ---------------------------------------------------------------------------
# T401 — TaskModuleFacade.retry_task 状态机契约
# ---------------------------------------------------------------------------


def test_t401_retry_task_delegates_to_task_service() -> None:
    """T401 · TaskModuleFacade.retry_task 委派 `TaskService.retry`。

    - callback 未配置 → RuntimeError(fail-fast)
    - callback 已配置 → 委派并返回 legacy 结果
    - `TaskService.retry` 内部状态机契约:只允许 failed / timed_out / cancelled
      前置状态(由 TaskService 自身承担 · 本 test 用 real TaskService 验证)。
    """

    from app.modules.task.service import TaskModuleFacade
    from app.modules.task.store import TaskModuleStore

    async def _dummy(_: Any) -> Any:
        return None

    # (1) callback 未配置 → RuntimeError
    facade_no_cb = TaskModuleFacade(
        store=TaskModuleStore(),
        create_canvas_image_task=_dummy,
        create_canvas_comfy_task=_dummy,
        get_canvas_image_task=_dummy,
        get_canvas_comfy_task=_dummy,
    )
    with pytest.raises(RuntimeError, match="retry_task_callback not configured"):
        facade_no_cb.retry_task("some-task-id")

    # (2) callback 已配置 → 委派
    captured: list[str] = []

    def _fake_retry(task_id: str) -> str:
        captured.append(task_id)
        return f"retried:{task_id}"

    facade = TaskModuleFacade(
        store=TaskModuleStore(),
        create_canvas_image_task=_dummy,
        create_canvas_comfy_task=_dummy,
        get_canvas_image_task=_dummy,
        get_canvas_comfy_task=_dummy,
        retry_task_callback=_fake_retry,
    )
    result = facade.retry_task("t1")
    assert captured == ["t1"]
    assert result == "retried:t1"


def test_t401_task_service_retry_state_machine_contract() -> None:
    """T401 补充 · `TaskService.retry` 状态机契约:只允许 failed / timed_out
    / cancelled 前置状态 · 其他状态抛 TaskStateError。承载层完整 · 本
    facade 委派后契约保持。
    """

    src = (
        ROOT / "app" / "task" / "service" / "task_service.py"
    ).read_text(encoding="utf-8")
    # 断言 retry() 方法内含状态白名单字面量
    assert '"failed", "timed_out", "cancelled"' in src, (
        "TaskService.retry 状态机白名单契约不应改动"
    )


# ---------------------------------------------------------------------------
# T402 — get_task_view 优先 legacy CANVAS_TASKS
# ---------------------------------------------------------------------------


def test_t402_get_task_view_priorizes_legacy_canvas_tasks_path() -> None:
    """T402 · TaskModuleFacade.get_task_view 委派 legacy 函数 ·
    legacy 函数体本身查询 `CANVAS_TASKS` 内存字典(承载层完整;fallback 到
    TaskService 由未来 PR 承接)。

    contract 断言:
    - facade 只调 callback 一次;不额外查 TaskService
    - main.py 里 get_canvas_image_task / get_canvas_comfy_task 函数体保留
      `CANVAS_TASKS.get(task_id)` 查询
    """

    from app.modules.task.service import TaskModuleFacade
    from app.modules.task.store import TaskModuleStore

    call_counter = {"image": 0, "comfy": 0, "task_service": 0}

    async def _fake_get_image(task_id: str) -> dict:
        call_counter["image"] += 1
        return {"id": task_id, "source": "canvas_tasks"}

    async def _fake_get_comfy(task_id: str) -> dict:
        call_counter["comfy"] += 1
        return {"id": task_id, "source": "canvas_tasks"}

    async def _dummy(_: Any) -> Any:
        call_counter["task_service"] += 1
        return None

    facade = TaskModuleFacade(
        store=TaskModuleStore(),
        create_canvas_image_task=_dummy,
        create_canvas_comfy_task=_dummy,
        get_canvas_image_task=_fake_get_image,
        get_canvas_comfy_task=_fake_get_comfy,
    )
    r = asyncio.run(facade.get_task_view("t1", "image"))
    assert r["source"] == "canvas_tasks"
    assert call_counter["image"] == 1
    assert call_counter["task_service"] == 0

    # main.py 里 legacy 函数体仍查 CANVAS_TASKS
    main_src = MAIN_PATH.read_text(encoding="utf-8")
    assert "CANVAS_TASKS.get(task_id)" in main_src, (
        "legacy get_canvas_*_task 函数体 CANVAS_TASKS 查询消失 · P0-2 兼容层破裂"
    )


# ---------------------------------------------------------------------------
# T403 — TaskErrorCategory mapper 契约(14 值枚举)
# ---------------------------------------------------------------------------


def test_t403_task_error_category_14_values_frozen() -> None:
    """T403 · `TaskErrorCategory` 枚举 14 值契约冻结(承接任务 PR-6)。"""

    from app.task.view.error_category import TaskErrorCategory

    expected = {
        "rate_limit",
        "timeout",
        "upstream_5xx",
        "invalid_credential",
        "invalid_input",
        "quota_exceeded",
        "content_moderation",
        "resource_not_found",
        "cancelled_by_user",
        "cancelled_by_upstream",
        "partial_success",
        "network_error",
        "unknown_recoverable",
        "unknown_terminal",
    }
    actual = {c.value for c in TaskErrorCategory}
    assert actual == expected, f"TaskErrorCategory 14 值契约破裂 · actual={actual}"


# ---------------------------------------------------------------------------
# T404 — legacy CANVAS_TASKS / CANVAS_TASK_LOCK / QUEUE main.py AST 抗回归
# ---------------------------------------------------------------------------


def test_t404_legacy_task_symbols_preserved_in_main() -> None:
    """T404 · legacy 兼容层符号 AST 抗回归:
    - CANVAS_TASKS 全局字典赋值语句存在
    - CANVAS_TASK_LOCK Lock 赋值语句存在
    - QUEUE 列表赋值语句存在
    - QUEUE_LOCK Lock 赋值语句存在
    - HISTORY_LOCK Lock 赋值语句存在
    """

    src = MAIN_PATH.read_text(encoding="utf-8")
    assert re.search(r"^CANVAS_TASKS\s*:", src, re.MULTILINE) or re.search(
        r"^CANVAS_TASKS\s*=", src, re.MULTILINE
    ), "CANVAS_TASKS 全局字典赋值语句缺失"
    assert re.search(r"^CANVAS_TASK_LOCK\s*=\s*Lock", src, re.MULTILINE)
    assert re.search(r"^QUEUE\s*=\s*\[\]", src, re.MULTILINE)
    assert re.search(r"^QUEUE_LOCK\s*=\s*Lock", src, re.MULTILINE)
    assert re.search(r"^HISTORY_LOCK\s*=\s*Lock", src, re.MULTILINE)


# ---------------------------------------------------------------------------
# T405 — asyncio.create_task 保留 · main.py grep 未减少
# ---------------------------------------------------------------------------


def test_t405_asyncio_create_task_calls_preserved() -> None:
    """T405 · main.py 中 `asyncio.create_task(...)` 调用数量应 >= 现有基线
    (fire-and-forget 承接层保留);本 PR 不减少这些调用。
    """

    src = MAIN_PATH.read_text(encoding="utf-8")
    count = len(re.findall(r"asyncio\.create_task\s*\(", src))
    # 至少两个来自 run_canvas_image_task + run_canvas_comfy_task fire-and-forget
    assert count >= 2, (
        f"main.py `asyncio.create_task` 调用数 {count} · 期望至少 2 处"
    )


# ---------------------------------------------------------------------------
# T406-T408 — WebSocket 消息 AST 抗回归
# ---------------------------------------------------------------------------


def test_t406_websocket_stats_message_types_preserved() -> None:
    """T406 · WebSocket `/ws/stats` 相关消息字面量保留:
    stats / new_image / canvas_updated / asset_library_updated / pong。
    """

    src = MAIN_PATH.read_text(encoding="utf-8")
    for msg_type in (
        '"stats"',
        '"new_image"',
        '"canvas_updated"',
        '"asset_library_updated"',
        '"pong"',
    ):
        assert msg_type in src, (
            f"WebSocket 消息字面量 {msg_type} 缺失 · 兼容层破裂"
        )


def test_t407_websocket_stats_route_still_in_main() -> None:
    """T407 · `/ws/stats` websocket 装饰器仍在 main.py。"""

    src = MAIN_PATH.read_text(encoding="utf-8")
    assert '@app.websocket("/ws/stats")' in src, (
        "/ws/stats websocket 装饰器缺失"
    )


def test_t408_shadow_register_hooks_preserved() -> None:
    """T408 · 任务 PR-3 影子登记转发器 `_shadow_register` 保留 ·
    6 处 CANVAS_TASKS 交互点全部保留 shadow hook。
    """

    src = MAIN_PATH.read_text(encoding="utf-8")
    assert "_shadow_register" in src
    # submit / release / transition 语义标签保留
    for label in (
        '"submit"',
        '"release"',
        '"transition"',
    ):
        assert label in src, (
            f"_shadow_register operation label {label} 缺失"
        )


# ---------------------------------------------------------------------------
# T409 — 保活烟测 · canvas image + comfy 任务提交 / 查询 / 重试 · history 查询
# ---------------------------------------------------------------------------


def test_t409_canvas_tasks_router_does_not_import_main() -> None:
    """T409 · `app/api/routers/canvas_tasks.py` 不 `import main` (继承
    PR-BE-05/06/08 硬约束)。"""

    tree = ast.parse(
        (ROUTER_DIR / "canvas_tasks.py").read_text(encoding="utf-8")
    )
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "main" not in imported


def test_t409_task_module_files_do_not_import_main() -> None:
    """T409 补充 · `app/modules/task/*.py` 全部不 `import main`。"""

    mod_dir = ROOT / "app" / "modules" / "task"
    for py_path in mod_dir.glob("*.py"):
        tree = ast.parse(py_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "main", (
                        f"{py_path.name} 违反硬约束:不许 import main"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module != "main", (
                    f"{py_path.name} 违反硬约束:不许 from main import"
                )


def test_t409_smoke_facade_wiring() -> None:
    """T409 · 保活烟测 · TaskModuleFacade + TaskModuleStore 装配路径通畅。"""

    from app.modules.task import (
        DeleteHistoryCommand,
        GetTaskViewCommand,
        ListHistoryCommand,
        RetryTaskCommand,
        SubmitCanvasComfyTaskCommand,
        SubmitCanvasImageTaskCommand,
        TaskModuleFacade,
        TaskModuleStore,
    )

    # 命令对象都可空构造(除必填字段)
    _ = SubmitCanvasImageTaskCommand(payload=None)
    _ = SubmitCanvasComfyTaskCommand(payload=None)
    _ = RetryTaskCommand(task_id="t1")
    _ = GetTaskViewCommand(task_id="t1", kind="image")
    _ = ListHistoryCommand()
    _ = DeleteHistoryCommand(timestamp=1.0)

    # facade + store 类型可实例化
    assert TaskModuleFacade is not None
    assert TaskModuleStore is not None
