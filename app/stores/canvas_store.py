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

from .legacy_snapshot import SchemaVersion, build_snapshot, read_json_source


DOMAIN = "canvas"


def save_canvas(*args: Any, **kwargs: Any) -> Any:
    # 懒 import 避免与 `main.py` 顶部 `from app.factory import create_app`
    # 桥接语义冲突（`app.factory` 内部懒 `import main`）。
    from main import save_canvas as _impl
    result = _impl(*args, **kwargs)
    # 数据 PR-6 shadow write hook；env 关闭时零开销 return，主写路径不受影响。
    _write_shadow_after_save(args, kwargs)
    return result


def _write_shadow_after_save(args: tuple, kwargs: dict) -> None:
    """`save_canvas` 主写成功后的短窗双写 hook。

    - 门禁：`SHADOW_WRITE_CANVAS` env truthy 才继续；未启用时零开销 return，
      不 import DB 层、不构造 engine、不落盘。
    - 结果永不进入 HTTP 响应；主写返回值原样透传。
    - 失败隔离：任何异常只落 warning + `data/shadow_diff/canvas_write/*.jsonl`，
      **永不冒泡**到 `save_canvas` 主路径（P0 硬约束）。
    """

    try:
        # 零开销 short-circuit：只 import runner 命名空间，不触发 DB 层。
        from app.shadow_write.runner import (
            is_shadow_write_enabled,
            run_shadow_write,
        )

        if not is_shadow_write_enabled(DOMAIN):
            return
        canvas = _extract_canvas_snapshot(args, kwargs)
        if canvas is None:
            return
        run_shadow_write(DOMAIN, canvas)
    except Exception:  # pragma: no cover — 失败隔离契约
        import logging

        logging.getLogger(__name__).warning(
            "canvas_store: shadow write hook failed", exc_info=True
        )


def _extract_canvas_snapshot(args: tuple, kwargs: dict) -> dict[str, Any] | None:
    """把 `save_canvas(canvas)` 的位置/关键字参数还原为 dict。"""

    if args:
        candidate = args[0]
    else:
        candidate = kwargs.get("canvas")
    if isinstance(candidate, dict):
        return candidate
    return None


def load_canvas(*args: Any, **kwargs: Any) -> Any:
    from main import load_canvas as _impl
    result = _impl(*args, **kwargs)
    # 数据 PR-5 shadow read hook；env 关闭时零开销 return。
    read_shadow(result)
    return result


def read_shadow(json_snapshot: Any, *, request_id: str | None = None) -> None:
    """Shadow-read entry；JSON 主读成功后调用。

    - 门禁：`SHADOW_READ_CANVAS` env truthy 才继续。
    - 结果永不进入 HTTP 响应；只影响 `data/shadow_diff/canvas/*.jsonl` 落盘。
    - 失败隔离：任何异常仅记 warning。
    """

    # 零开销 short-circuit：只 import runner 命名空间，不触发 DB 层。
    from app.shadow_read.runner import is_shadow_read_enabled, run_shadow_read

    if not is_shadow_read_enabled(DOMAIN):
        return
    run_shadow_read(DOMAIN, json_snapshot, request_id=request_id)


def snapshot(canvas_id: str) -> dict[str, Any]:
    from main import canvas_path

    path = canvas_path(canvas_id)
    payload, raw_json = read_json_source(path, {})
    return build_snapshot(
        payload,
        raw_json=raw_json,
        schema_version=SchemaVersion.CANVAS,
        legacy_id=str(payload.get("id") or canvas_id),
        legacy_path=path,
        legacy_url=payload.get("url"),
        legacy_owner_label=payload.get("owner"),
    )
