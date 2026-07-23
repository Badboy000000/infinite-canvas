"""Provider 领域 router（PR-BE-08 · Wave 3-N.6 Batch 2 主线 A）。

抽出 `main.py` 中 provider 特有路由：
- `GET  /api/providers`
- `PUT  /api/providers`
- `POST /api/providers/test-connection`
- `POST /api/providers/probe-async`
- `POST /api/providers/fetch-models`
- `GET  /api/providers/{provider_id}/fetch-models`

（任务书 §4 中 `/api/test-connection` / `/api/fetch-models` 表述为笔误 —
以代码事实 `/api/providers/test-connection` / `/api/providers/fetch-models`
为准 · 裁决 2 已确认）

裁决 1(GM-14 圆桌自治第 7 次实证 · Lead ratify)：`/api/config`(ai_config)
+ `/api/models`(ai_models) **保留在 `app/api/routers/storage.py`**（PR-BE-05
抽出结果冻结）· 本 router **不承接**。

裁决 2 · 路由顺序三条位置断言(T356 加强)：
- `/api/providers/{provider_id}/fetch-models` 在 `/api/providers/{provider_id}` 之前
- `/api/providers/test-connection`             在 `/api/providers/{provider_id}` 之前
- `/api/providers/probe-async`                 在 `/api/providers/{provider_id}` 之前

（当前实现中 `/api/providers/{provider_id}` 单参 GET/PATCH 路由未真实注册 —
`main.py` 现存代码不存在这条通配路由；本 router 声明顺序仍按上述三条断言
组织，为未来引入通配路由的场景提供 GM-11 硬护栏。）

设计：`create_router(...)` 工厂函数拿到 `ProviderConfigService` +
`ProviderRegistry` + 一批显式 callback，不 `import main`。业务复杂路由
(`test-connection` / `probe-async` / `fetch-models`) 通过 callback 承接
legacy 函数体（保留兼容层，为后续 PR 迁入本模块打底）。
"""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, HTTPException

from app.modules.provider.commands import SaveProvidersCommand
from app.modules.provider.registry import ProviderRegistry
from app.modules.provider.service import ProviderConfigService


def create_router(
    *,
    service: ProviderConfigService,
    registry: ProviderRegistry,
    api_provider_dto: type,
    test_connection_dto: type,
    update_env_values_callback: Callable[[dict[str, str]], Any],
    reload_env_globals_callback: Callable[[], Any],
    public_provider_callback: Callable[[dict[str, Any]], dict[str, Any]],
    test_connection_callback: Callable[[Any], Awaitable[Any]],
    probe_async_callback: Callable[[Any], Awaitable[Any]],
    fetch_models_from_payload_callback: Callable[[Any], Awaitable[Any]],
    fetch_models_by_provider_id_callback: Callable[[str], Awaitable[Any]],
) -> APIRouter:
    """构造 provider 路由分组。

    参数刻意用 `type` 注入 DTO —— DTO 定义仍留在 `main.py`（任务书零触
    碰事实清单第 6 项），本模块只负责路由声明与命令对象装配。

    复杂业务路由（test-connection / probe-async / fetch-models）通过
    callback 承接 legacy 函数体：本 router 层极薄，仅做 DTO → callback
    的透传。
    """

    router = APIRouter()

    # -- fetch-models 前置(裁决 2 加强 · T356 断言 1)：--------------------
    # `/api/providers/{provider_id}/fetch-models` 必须在通配
    # `/api/providers/{provider_id}` 之前声明，防止 FastAPI 把 provider_id
    # 值 `"test-connection"` / `"probe-async"` 误吞到通配路由。

    @router.get("/api/providers/{provider_id}/fetch-models")
    async def fetch_upstream_models(provider_id: str):
        """从已保存的上游 OpenAI 兼容接口拉取 /v1/models 列表，按名称智能分类为 image/chat/video。"""

        return await fetch_models_by_provider_id_callback(provider_id)

    # -- test-connection 前置(裁决 2 · T356 断言 2)：----------------------

    @router.post("/api/providers/test-connection")
    async def test_provider_connection(payload: test_connection_dto):  # type: ignore[valid-type]
        """测试请求地址是否可用：调上游 /v1/models。验证通过时同时把模型清单按类别返回，避免再调一次拉取接口。"""
        return await test_connection_callback(payload)

    # -- probe-async 前置(裁决 2 · T356 断言 3)：--------------------------

    @router.post("/api/providers/probe-async")
    async def probe_async_endpoint(payload: test_connection_dto):  # type: ignore[valid-type]
        """验证异步协议：用假 task_id 请求 GET /v1/tasks/{fake_id}。
        收到 400 Invalid task ID = 端点存在且 Key 有效；401/403 = Key 无效；404/连接失败 = 不支持异步端点。"""
        return await probe_async_callback(payload)

    # -- fetch-models by payload -----------------------------------------

    @router.post("/api/providers/fetch-models")
    async def fetch_upstream_models_from_payload(payload: test_connection_dto):  # type: ignore[valid-type]
        """按页面当前表单值拉取模型，支持新增平台未保存时直接使用临时 Base URL / Key。"""
        return await fetch_models_from_payload_callback(payload)

    # -- 集合 GET / PUT ---------------------------------------------------

    @router.get("/api/providers")
    async def api_providers():
        return {"providers": service.list_providers()}

    @router.put("/api/providers")
    async def save_providers(payload: list[api_provider_dto]):  # type: ignore[valid-type]
        cmd = SaveProvidersCommand(payload_items=payload)
        providers, env_updates = service.save_providers(cmd)
        if env_updates:
            update_env_values_callback(env_updates)
            reload_env_globals_callback()
        return {
            "providers": [public_provider_callback(p) for p in providers]
        }

    return router


__all__ = ["create_router"]
