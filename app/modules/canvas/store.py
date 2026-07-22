"""Canvas 持久化 facade（PR-BE-06）。

`CanvasStore` 是路由层之外看到的**唯一**画布持久化入口。它委派给
`app.stores.canvas_store`（这是数据 PR-0/6/7/10/15 已锁的 store facade），
不重新实现 JSON IO，也不直接 `import main`。

严格约束（任务书零触碰第 8 项）：
- **不改** `app.stores.canvas_store` 内部实现（那是主线 A subagent 的目标
  文件）。本类只做同签名的薄委派。

不覆盖的调用点（回收站 / metadata 更新等仍走 `main.py` 里的原函数）会通过
`CanvasService` 的 callback 参数直接注入，仍保持"零触碰"约束。
"""

from __future__ import annotations

from typing import Any

from app.stores import canvas_store as _canvas_store_facade


class CanvasStore:
    """薄委派 store —— 让 service 层不用直接 `import` facade 模块。"""

    def load_canvas(self, canvas_id: str) -> dict[str, Any]:
        return _canvas_store_facade.load_canvas(canvas_id)

    def save_canvas(self, canvas: dict[str, Any]) -> Any:
        return _canvas_store_facade.save_canvas(canvas)
