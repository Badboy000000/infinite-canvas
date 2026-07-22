"""Canvas store facade — 数据模型治理 PR-0 / PR-6 / PR-7 / PR-10 / PR-15。

包裹 `main.py` 中现有的画布 JSON 读写函数 `save_canvas` / `load_canvas`。
签名与被包裹的原函数一一对应。

- 数据 PR-6 起：`save_canvas` 主写成功后附 shadow write hook。
- 数据 PR-7 起：新增 `CANVAS_PRIMARY_WRITE` env 分派：
  * `"json"`（显式回滚）→ 完全等价 PR-6 行为（老 JSON 主写 + shadow write hook）。
    **必须**保证不 import `app.db.canvas_writer`，不构造 DB engine，不落任何
    fallback 文件（P0 硬约束）。
  * `"db"`（默认 · 数据 PR-15 M1 收官后反转）→ `app.db.canvas_writer.save_canvas_db`
    DB 主写 + JSON 异步回写。DB 主写失败上抛（不 fallback 到 JSON 主写）。
- 数据 PR-10 起：`db` 模式显式启用步骤 + CB-P5-08a busy_timeout 修复承接。
- **数据 PR-15 起（本 PR）**：canvas 域 M1 收官反转默认。`_get_primary_write_mode`
  未设 env 或空 env → `"db"`（既往为 `"json"`）；`save_canvas` 函数体不变，
  分派开关不变；仅 fallback 常量翻转（2 处单行 + AST 断言 zero-diff 于其余部分）。

`_get_primary_write_mode` 是分派入口；未知值 fail-fast（`ValueError`）。

数据 PR-15 · canvas 域 M1 反转默认 · `CANVAS_PRIMARY_WRITE` 使用手册
======================================================================

**默认行为（无 env）**：DB 主写 + JSON 异步回写。不再需要 `export
CANVAS_PRIMARY_WRITE=db`。

**前置条件**（Lead 复核 · 反转前必须已满足）：

1. 目标环境 `data/app.db` 已 `alembic upgrade head`，`canvases` 表存在
   （否则 `save_canvas_db` 会在首次 upsert 时抛 `OperationalError`；
    对应测试 T77 / T91）。
2. 至少一次冷启动通过 `python -m tools.synth_shadow_read_probe --scale=50
   --seed=1337` 输出 `readiness_verdict == "GREEN"`（承接 Wave 3-J 合成压测
   报告 · CB-P5-08a 已修复到 busy_timeout=400ms · 场景 D `per_iter_latency_ms`
   P99 ≤ 500ms · saves_bubbled_exception=0）。
3. `data/canvas/*.json` 快照与 DB 已完成一次数据对账（等价 shadow_read
   命中率 ≥ 0.99）。**承接补丁 P1-RC-B-2** 提示 `tools/check_data_alignment`
   尚未交付（记为 CB-P5-11），当前 Lead 用 `python -m tools.synth_shadow_read_probe
   --scale=50` 的场景 A `hit_rate` 字段 ≥ 0.99 作等价指标。

**⚠️ 强烈建议**（承接补丁 P1-RC-B-3 · 承接 CB-P5-08b · 数据 PR-15 内嵌闭合）：
   数据 PR-15 已修 `shadow_read.canvas_normalizer` 单-id 判定路径（不再 O(N)
   扫描其它 canvas），CB-P5-08b 观察项已关闭；但仍建议 `SHADOW_READ_CANVAS`
   仅在**独立观察窗口**内启用 12-24h，避免长期磁盘占用。

**验收步骤**（默认路径 · 无需 export）：

1. 部署环境直接启动服务；`_get_primary_write_mode` 返回 `"db"`。
2. **可选** `export SHADOW_READ_CANVAS=true` 12-24h 观察窗口继续把
   `data/shadow_diff/canvas/*.jsonl` 作为回退证据链；观察窗口结束后立即
   `unset SHADOW_READ_CANVAS`。
3. 观察 `canvas_store: load_canvas fallback_hit=true` warning 日志频率；
   `fallback_reason=db_empty` 意味着 canvas 尚未导入 DB，需要重新触发一次
   `import_domain("canvas", …)`。

**回滚步骤**（生产可见异常时执行 · P0 快速回滚）：

1. 立即 `export CANVAS_PRIMARY_WRITE=json` → 进程重启后 `save_canvas`
   立即回到 PR-6 语义（老 JSON 主写 + shadow write hook）。回滚不需要
   数据迁移，因为 `db` 模式全过程都异步回写 JSON 文件（`_async_write_json_fallback`）。
2. 校验 `data/canvas/*.json` 与 DB 是否同步（同前对账工具）；如 JSON 落后于 DB
   （例如异步回写线程未跑完），从 DB `content_json` 反导 JSON:
   **⚠️ 承接补丁 P1-RC-B-2**:`tools/export_db_to_json` 尚未交付（Wave 3-K
   记为 CB-P5-11 承接项 · 未交付时需 Lead 手工用 `sqlite3` CLI 直接
   `SELECT content_json FROM canvases WHERE legacy_id = ? ` 并落 JSON 文件）。
3. 保留 `CANVAS_PRIMARY_WRITE=json` + `SHADOW_READ_CANVAS=true` 至少 1 个
   观察窗口，确认 `shadow_diff` 无 `missing_in_json` 尾部记录，再关闭
   shadow_read。

**验收命令**（Wave 3-L 硬门槛，等价 subagent 交付）：

- `pytest tests/db/test_canvas_primary_write_default_reversal.py -v` → 10/10 passed（T90-T99）
- `pytest tests/db/test_canvas_primary_write_db_mode.py -v` → 10/10 passed（T70-T79 抗回归）
- `python -m tools.synth_shadow_read_probe --scale=50 --seed=1337
    --output=probe.json` → `readiness_verdict == "GREEN"`
- `python tools/check_delivery_closure.py`（PR 合并前）
"""
from __future__ import annotations

from typing import Any

from .legacy_snapshot import SchemaVersion, build_snapshot, read_json_source


DOMAIN = "canvas"

# 数据 PR-7 允许值域（其他值 fail-fast）。
_PRIMARY_WRITE_ALLOWED: frozenset[str] = frozenset({"json", "db"})


def _get_primary_write_mode(domain: str) -> str:
    """读 `CANVAS_PRIMARY_WRITE` env（现读，不缓存）。

    - `domain` 目前只支持 `"canvas"`；其他域直接返回 `"json"`。
    - 未设置或空 → `"json"`（默认）。
    - 值域 `{"json", "db"}`；其他值抛 `ValueError`（Settings 层也会兜住，
      但这里的 fail-fast 保证运行时也不静默走错分支）。
    """

    if domain != DOMAIN:
        return "json"
    import os

    raw = os.environ.get("CANVAS_PRIMARY_WRITE")
    if raw is None:
        return "db"
    value = str(raw).strip().lower()
    if not value:
        return "db"
    if value not in _PRIMARY_WRITE_ALLOWED:
        raise ValueError(
            f"Invalid CANVAS_PRIMARY_WRITE {raw!r}; expected one of: "
            + ", ".join(sorted(_PRIMARY_WRITE_ALLOWED))
        )
    return value


def save_canvas(*args: Any, **kwargs: Any) -> Any:
    """`save_canvas(canvas)` wrapper。

    - `CANVAS_PRIMARY_WRITE=json`（默认）→ 老 `main.save_canvas` + PR-6
      shadow write hook；**不 import** `app.db.canvas_writer`。
    - `CANVAS_PRIMARY_WRITE=db` → `save_canvas_db` DB 主写 + JSON 异步回写。
    """

    mode = _get_primary_write_mode(DOMAIN)
    if mode == "db":
        canvas = _extract_canvas_snapshot(args, kwargs)
        if canvas is None:
            # 传入不是 dict：退回到老 impl 让它自己抛错（保持既有语义）。
            from main import save_canvas as _impl

            return _impl(*args, **kwargs)
        # 懒 import：仅在 db 模式下才拉起 canvas_writer 命名空间。
        from app.db.canvas_writer import save_canvas_db, _async_write_json_fallback

        save_canvas_db(canvas)
        _async_write_json_fallback(canvas)
        return None

    # 默认 mode == "json"：完全等价 PR-6 行为。
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
    """`load_canvas(canvas_id)` wrapper。

    - `CANVAS_PRIMARY_WRITE=json`（默认）→ 老 `main.load_canvas` + PR-5
      shadow read hook；**不 import** `app.db.canvas_writer`。
    - `CANVAS_PRIMARY_WRITE=db` → DB 优先；命中直接返回；未命中降级 JSON
      主读（`main.load_canvas` 原语义：404 时抛 HTTPException）；命中率
      warning 日志 + `data/shadow_diff/canvas_load_fallback/*.jsonl`。
    """

    mode = _get_primary_write_mode(DOMAIN)
    if mode == "db":
        return _load_canvas_db_first(*args, **kwargs)

    # 默认 mode == "json"：完全等价 PR-6 行为。
    from main import load_canvas as _impl
    result = _impl(*args, **kwargs)
    # 数据 PR-5 shadow read hook；env 关闭时零开销 return。
    read_shadow(result)
    return result


def _load_canvas_db_first(*args: Any, **kwargs: Any) -> Any:
    """DB 优先读；未命中降级 JSON 主读。命中率通过 warning 日志聚合。"""

    canvas_id: Any = args[0] if args else kwargs.get("canvas_id")
    if not canvas_id:
        # 保留老 impl 的入参校验语义。
        from main import load_canvas as _impl

        return _impl(*args, **kwargs)

    import logging

    logger = logging.getLogger(__name__)
    # 懒 import：仅在 db 模式下才拉起 canvas_writer 命名空间。
    try:
        from app.db.canvas_writer import load_canvas_db

        db_snapshot = load_canvas_db(str(canvas_id))
    except Exception as exc:
        # DB 读失败不吞：降级到 JSON 主读，但记 warning + shadow diff（`db_error`）。
        db_snapshot = None
        logger.warning(
            "canvas_store: load_canvas_db raised, falling back to JSON id=%s err=%s",
            canvas_id,
            exc,
        )
        _record_load_fallback(str(canvas_id), reason="db_error", error=str(exc))

    if db_snapshot is not None:
        if db_snapshot.get("deleted_at"):
            # 与老 `main.load_canvas` 语义对齐：回收站画布抛 404。
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="画布已在回收站")
        logger.info(
            "canvas_store: load_canvas fallback_hit=false id=%s source=db",
            canvas_id,
        )
        return db_snapshot

    # DB 无记录 → JSON fallback；warning + shadow diff（`db_empty`）。
    logger.warning(
        "canvas_store: load_canvas fallback_hit=true fallback_reason=db_empty id=%s",
        canvas_id,
    )
    _record_load_fallback(str(canvas_id), reason="db_empty", error="")
    from main import load_canvas as _impl

    return _impl(*args, **kwargs)


def _record_load_fallback(legacy_id: str, *, reason: str, error: str) -> None:
    """把 load fallback 事件落 `data/shadow_diff/canvas_load_fallback/*.jsonl`。

    失败仅 warning，绝不 raise。
    """

    try:
        import datetime as _dt
        import json
        import os

        from app.shared.settings import get_settings

        record = {
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "domain": "canvas",
            "legacy_id": legacy_id,
            "error": error,
            "fallback_reason": reason,
        }
        base = get_settings().data_dir
        dir_path = os.path.join(base, "shadow_diff", "canvas_load_fallback")
        os.makedirs(dir_path, exist_ok=True)
        file_path = os.path.join(
            dir_path,
            _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d") + ".jsonl",
        )
        with open(file_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # pragma: no cover — 失败隔离
        import logging

        logging.getLogger(__name__).warning(
            "canvas_store: load fallback diff write failed id=%s reason=%s",
            legacy_id,
            reason,
        )


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
