"""`app.shadow_write` — 数据模型治理 PR-6 短窗双写模块（Canvas 域首发）。

在 `canvas_store.save_canvas` JSON 主写成功之后，惰性把 canvas 的
`{content_json, content_hash, revision, base_updated_at, ...}` 写入 `data/app.db`
的 `canvases` 表；主写路径（`main.save_canvas` 函数体）**零字节触碰**。

关键契约（治理期）：

- **默认关闭**：`SHADOW_WRITE_CANVAS=false` 时 `is_shadow_write_enabled('canvas')`
  返回 `False`，`run_shadow_write` 立即 return，不 import DB、不构造 engine、
  不落盘任何 diff 文件。
- **主写不切**：JSON 主写路径永远原样返回；shadow write 结果永不进入 HTTP
  响应，也永不通过 `save_canvas` 返回值泄漏。
- **失败隔离**：任何 shadow write 内部异常仅记 warning，绝不 raise。
- **读/写路径独立**：不复用 `app.shadow_read` 内部；两条链路独立扩展。
- **Provider 凭据零落 DB**：Canvas 域本身不涉及凭据；`content_json` 若混入
  凭据键位由 `main.py` 主写路径负责（本模块只做字节等价镜像）。
- **不入库**：`data/shadow_diff/canvas_write/` 由根 `.gitignore` 排除。

详见：

- [[40 实施计划/数据模型治理实施计划与PR清单]] PR-6
- [[30 治理方案/数据模型治理方案]] 迁移策略阶段 4
- [[60 讨论记录/2026-07-19 Wave 3-E-数据 PR-6 开工/2026-07-19 Wave 3-E-数据 PR-6
   开工协调纲要]]
"""

from __future__ import annotations

from app.shadow_write.runner import (
    is_shadow_write_enabled,
    run_shadow_write,
)

__all__ = [
    "is_shadow_write_enabled",
    "run_shadow_write",
]
