"""`app.shadow_read.fields` — 4 domain 稳定字段集常量。

稳定字段集：diff 比较的白名单字段；未在集合内的字段一律忽略（避免读时
排序、时间戳漂移等噪声进 diff）。选择原则：

- 只选**语义稳定**且**跨 JSON/DB 一致**的字段（`id / name / order` 之类）。
- **不**收录时间戳（`created_at` / `updated_at` / `imported_at`），因为
  JSON 侧是 epoch ms 而 DB 侧是 tz-aware ISO datetime，本 PR 不做转换。
- **不**收录密钥或其他敏感字段。
- Provider 字段集为 `provider_config_store._PROVIDER_SNAPSHOT_FIELD_ORDER`
  子集（白名单已由 store 侧深层脱敏保证不含密钥）。
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping


PROJECT_STABLE_FIELDS: frozenset[str] = frozenset({
    "id",
    "name",
    "order",
})
"""Project：`{id, name, order}`；`created_at` / `updated_at` 不入 diff。"""


PROVIDER_STABLE_FIELDS: frozenset[str] = frozenset({
    "id",
    "name",
    "base_url",
    "protocol",
    "image_request_mode",
    "enabled",
    "primary",
})
"""ProviderConfig：只取白名单标量字段；`_safe_provider_records` 已深层脱敏。

**硬约束**：任何密钥字段（`key` / `api_key` / `authorization` / ...）绝不
进入此集合；provider store snapshot 从来不透出密钥字段（白名单只允许
`_PROVIDER_SNAPSHOT_FIELD_ORDER`），本 PR 只从中挑标量字段做 diff。
"""


PROMPT_LIBRARY_STABLE_FIELDS: frozenset[str] = frozenset({
    "id",
    "name",
    "scope",
})
"""PromptLibrary：只对 library 顶层字段做 diff。`items` 由 importer 拆表
存在 `prompt_items`；`items` 集合级差异在 `missing_in_*` 键位承载。"""


WORKFLOW_DEFINITION_STABLE_FIELDS: frozenset[str] = frozenset({
    "legacy_id",
    "name",
    "provider_id",
    "kind",
})
"""WorkflowDefinition：`legacy_id` 作为跨 JSON/DB 主键（`rh:<pid>:<kind>:<wid>`
或 `file:<basename>`）——importer 已按此规则合成；JSON 侧为便于比较也走同
规则合成后进 diff。
"""


STABLE_FIELDS_BY_DOMAIN: Mapping[str, frozenset[str]] = MappingProxyType({
    "project": PROJECT_STABLE_FIELDS,
    "provider_config": PROVIDER_STABLE_FIELDS,
    "prompt_library": PROMPT_LIBRARY_STABLE_FIELDS,
    "workflow_definition": WORKFLOW_DEFINITION_STABLE_FIELDS,
})

SUPPORTED_SHADOW_DOMAINS: tuple[str, ...] = (
    "project",
    "provider_config",
    "prompt_library",
    "workflow_definition",
)


__all__ = [
    "PROJECT_STABLE_FIELDS",
    "PROVIDER_STABLE_FIELDS",
    "PROMPT_LIBRARY_STABLE_FIELDS",
    "WORKFLOW_DEFINITION_STABLE_FIELDS",
    "STABLE_FIELDS_BY_DOMAIN",
    "SUPPORTED_SHADOW_DOMAINS",
]
