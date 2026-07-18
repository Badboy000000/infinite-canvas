"""`app.data_import` — 数据模型治理 PR-3 幂等导入器 + 对账工具。

本包只承担"把旧 JSON 按领域幂等导入 DB 空表 + 输出稳定 JSON 对账报告"的
职责；**不启用**任何 Store 从 DB 读、**不切主写**、**不引入密钥导入**。

- `tables`：6 类对象的 SQLAlchemy `Table` 定义；全部挂到
  `from app.db.base import metadata` 单例（禁自建 `MetaData()`）。
- `orchestrator`：`import_domain(domain, ...)` / `reconcile_domain(domain)`
  的调度层；每个 domain 复用对应 Store 的 `snapshot()` 输出。
- `importers/`：6 个 domain 幂等 importer（`INSERT OR IGNORE ON legacy_id`）。
- `reconcile`：JSON vs DB 对账，稳定 JSON 输出。

**硬约束**：Provider importer 必须走
`app.stores.provider_config_store._safe_provider_records` 深度脱敏；
密钥字段（`api_key` / `authorization` / `secret` / ...）**永不进 DB**。

详见 [[40 实施计划/数据模型治理实施计划与PR清单]] PR-3。
"""
from __future__ import annotations

from .orchestrator import (
    SUPPORTED_DOMAINS,
    ImportOutcome,
    ReconcileReport,
    import_domain,
    reconcile_domain,
)

__all__ = [
    "SUPPORTED_DOMAINS",
    "ImportOutcome",
    "ReconcileReport",
    "import_domain",
    "reconcile_domain",
]
