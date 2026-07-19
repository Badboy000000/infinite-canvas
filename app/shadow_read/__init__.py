"""`app.shadow_read` — 数据模型治理 PR-4 低风险 4 类 shadow 双读。

在 4 个低风险 Store（`project_store` / `provider_config_store` /
`prompt_library_store` / `workflow_store`）的 JSON 主读路径成功后，惰性
读取 `data/app.db` 内 `0002_baseline_tables` 迁移建的 baseline 快照，按
"稳定字段集"比较差异，写入 `data/shadow_diff/<domain>/<yyyymmdd>.jsonl`。

关键契约（治理期）：

- **主读不切**：JSON 结果永远原样返回给调用方；shadow 结果永不进入 HTTP
  响应，也永不通过 `Store.load_*` 返回值泄漏。
- **默认关闭**：4 个 env 开关 `SHADOW_READ_*` 全部默认 `false`。关闭时零
  副作用（不 import DB、不 migrate、不构造 store、不生成 diff 文件）。
- **失败隔离**：任何 shadow 内部异常仅记 warning，绝不 raise 到主读路径。
- **不入库**：`data/shadow_diff/` 由仓库根 `.gitignore` 排除，禁止入库。
- **Provider 密钥永不进 diff 日志**：走 store `_safe_provider_records()`
  白名单 + 深层脱敏；密钥字段在 JSON 侧读入时就已剥离。

详见：

- [[40 实施计划/数据模型治理实施计划与PR清单]] PR-4
- [[30 治理方案/数据模型治理方案]] 迁移策略阶段 3
- [[60 讨论记录/2026-07-19 Wave 3-C 开工/2026-07-19 Wave 3-C 开工协调纲要]]
"""

from __future__ import annotations

from app.shadow_read.fields import (
    PROJECT_STABLE_FIELDS,
    PROMPT_LIBRARY_STABLE_FIELDS,
    PROVIDER_STABLE_FIELDS,
    STABLE_FIELDS_BY_DOMAIN,
    SUPPORTED_SHADOW_DOMAINS,
    WORKFLOW_DEFINITION_STABLE_FIELDS,
)
from app.shadow_read.runner import (
    is_shadow_read_enabled,
    run_shadow_read,
)

__all__ = [
    "PROJECT_STABLE_FIELDS",
    "PROMPT_LIBRARY_STABLE_FIELDS",
    "PROVIDER_STABLE_FIELDS",
    "STABLE_FIELDS_BY_DOMAIN",
    "SUPPORTED_SHADOW_DOMAINS",
    "WORKFLOW_DEFINITION_STABLE_FIELDS",
    "is_shadow_read_enabled",
    "run_shadow_read",
]
