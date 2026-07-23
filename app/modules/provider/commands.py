"""Provider 命令对象（PR-BE-08 · Wave 3-N.6 Batch 2 主线 A）。

命令对象承接 `main.py` 中 provider 域端点的入参。每个命令对象都保留一个
`raw: dict` 字段作为宽松兜底，防止 legacy 宽松 JSON 字段在 Service 边界上
因显式建模而丢失（参照 PR-BE-06 canvas commands 硬约束）。

设计约束（任务书零触碰事实清单第 6 项）：
- **不改** `ApiProviderPayload` / `TestConnectionPayload` 等 Pydantic DTO 字
  段与默认值。命令对象只是从 DTO 组装出来的、供 Service 内部使用的独立
  轻量类型；请求 / 响应 shape 与错误码保持逐字节一致。
- 命令对象刻意不引入校验；校验依然在 FastAPI DTO 层完成。
- 密钥字段（api_key / wallet_api_key / volcengine_secret_access_key）走
  `raw: dict` 承接，Service 边界上不落地 log / repr —— 深度脱敏由
  `_safe_provider_records` 承担。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SaveProvidersCommand:
    """`PUT /api/providers` 命令对象。

    `payload_items` 直接承接 `List[ApiProviderPayload]` 的 DTO 序列（每项
    仍是 Pydantic 模型实例），Service 内部使用 `item.dict()` / `getattr`
    读取字段，与 legacy `save_providers` 函数体的调用形式保持一致。

    `raw: dict` 兜底保留调用侧原始 payload（含密钥字段），Service 在把
    env_updates 汇总回 router 之前不落地任何 log。
    """

    payload_items: list[Any]
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TestConnectionCommand:
    """`POST /api/providers/test-connection` / `POST /api/providers/probe-async` 命令对象。

    直接持有 DTO 实例（`TestConnectionPayload`），Service 通过既有的
    `protocol_from_payload` / `api_key_from_payload` helper 读字段，避免
    重复建模造成 shape 漂移。
    """

    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FetchModelsCommand:
    """`POST /api/providers/fetch-models` / `GET /api/providers/{provider_id}/fetch-models`。

    `provider_id` 仅在按 provider_id 路径上有值；按 payload 路径上是空串。
    """

    payload: Any | None = None
    provider_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "SaveProvidersCommand",
    "TestConnectionCommand",
    "FetchModelsCommand",
]
