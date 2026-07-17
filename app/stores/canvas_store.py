"""Canvas store facade — 数据模型治理 PR-0。

包裹 `main.py` 中现有的画布 JSON 读写函数 `save_canvas` / `load_canvas`。
只做委派，不引入 DB、不改任何接口 shape、不改锁的持有方式
（`CANVAS_LOCK` 仍留在原函数体内）。签名与被包裹的原函数一一对应。

后续（数据 PR-1 起）会在此 facade 内部切换到 SQLAlchemy Session；
路由层通过 `canvas_store.save_canvas(...)` / `canvas_store.load_canvas(...)`
调用，无需感知底层存储介质。
"""
from __future__ import annotations

from typing import Any


def save_canvas(*args: Any, **kwargs: Any) -> Any:
    # 懒 import 避免与 `main.py` 顶部 `from app.factory import create_app`
    # 桥接语义冲突（`app.factory` 内部懒 `import main`）。
    from main import save_canvas as _impl
    return _impl(*args, **kwargs)


def load_canvas(*args: Any, **kwargs: Any) -> Any:
    from main import load_canvas as _impl
    return _impl(*args, **kwargs)
