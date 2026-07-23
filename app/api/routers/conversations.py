"""Conversations / Chat 路由分组（PR-BE-11 · Wave 3-N.7 Batch 3 主线 A）。

抽出 `main.py` 中 7 对话/聊天路由：
- `GET    /api/conversations`                  — 对话列表
- `POST   /api/conversations`                  — 新建对话
- `GET    /api/conversations/{conversation_id}` — 获取对话
- `DELETE /api/conversations/{conversation_id}` — 删除对话
- `POST   /api/chat`                           — 聊天
- `POST   /api/chat/agent`                     — 智能体聊天
- `POST   /api/chat/stream`                    — 流式聊天

设计对齐 `app/api/routers/storage_files.py` pattern：
- **不 `import main`**：全部端点通过 `create_router(...)` 参数注入回调。
- 使用 `add_api_route` 装配端点，`name` 参数固定 `operation_id` 与 baseline
  完全对齐。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter


def create_router(
    *,
    conversations_cb: Callable[..., Any],
    create_conversation_cb: Callable[..., Any],
    get_conversation_cb: Callable[..., Any],
    delete_conversation_cb: Callable[..., Any],
    chat_cb: Callable[..., Awaitable[Any]],
    chat_agent_cb: Callable[..., Awaitable[Any]],
    chat_stream_cb: Callable[..., Awaitable[Any]],
    conversation_create_dto: type,
    chat_request_dto: type,
) -> APIRouter:
    """构造 conversations / chat 路由分组。

    参数命名约定：`<original_handler_name>_cb` 是 `main.py` 中保留的 legacy
    函数体。回调签名保留原始 FastAPI 依赖注入标记，`add_api_route` 会正确解析。
    """

    router = APIRouter()

    # -- GET /api/conversations ---------------------------------------------
    router.add_api_route(
        "/api/conversations",
        conversations_cb,
        methods=["GET"],
        name="conversations",
    )

    # -- POST /api/conversations --------------------------------------------
    async def _create_conversation(payload: conversation_create_dto, request: Any, x_user_id: str = ""):  # type: ignore[valid-type]
        return await create_conversation_cb(payload, request, x_user_id)

    _create_conversation.__annotations__["payload"] = conversation_create_dto
    _create_conversation.__annotations__["request"] = Any
    router.add_api_route(
        "/api/conversations",
        _create_conversation,
        methods=["POST"],
        name="create_conversation",
    )

    # -- GET /api/conversations/{conversation_id} ---------------------------
    router.add_api_route(
        "/api/conversations/{conversation_id}",
        get_conversation_cb,
        methods=["GET"],
        name="get_conversation",
    )

    # -- DELETE /api/conversations/{conversation_id} ------------------------
    router.add_api_route(
        "/api/conversations/{conversation_id}",
        delete_conversation_cb,
        methods=["DELETE"],
        name="delete_conversation",
    )

    # -- POST /api/chat -----------------------------------------------------
    async def _chat(payload: chat_request_dto, request: Any, x_user_id: str = ""):  # type: ignore[valid-type]
        return await chat_cb(payload, request, x_user_id)

    _chat.__annotations__["payload"] = chat_request_dto
    _chat.__annotations__["request"] = Any
    router.add_api_route(
        "/api/chat",
        _chat,
        methods=["POST"],
        name="chat",
    )

    # -- POST /api/chat/agent -----------------------------------------------
    async def _chat_agent(payload: chat_request_dto, request: Any, x_user_id: str = ""):  # type: ignore[valid-type]
        return await chat_agent_cb(payload, request, x_user_id)

    _chat_agent.__annotations__["payload"] = chat_request_dto
    _chat_agent.__annotations__["request"] = Any
    router.add_api_route(
        "/api/chat/agent",
        _chat_agent,
        methods=["POST"],
        name="chat_agent",
    )

    # -- POST /api/chat/stream ----------------------------------------------
    async def _chat_stream(payload: chat_request_dto, request: Any, x_user_id: str = ""):  # type: ignore[valid-type]
        return await chat_stream_cb(payload, request, x_user_id)

    _chat_stream.__annotations__["payload"] = chat_request_dto
    _chat_stream.__annotations__["request"] = Any
    router.add_api_route(
        "/api/chat/stream",
        _chat_stream,
        methods=["POST"],
        name="chat_stream",
    )

    return router


__all__ = ["create_router"]