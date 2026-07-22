"""`app.db.canvas_writer` — 数据 PR-7 Canvas DB 主写路径。

只有 `CANVAS_PRIMARY_WRITE=db` 时，`canvas_store.save_canvas` / `.load_canvas`
才 import 本模块（默认 `json` 路径**不 import**）。

关键契约（治理期）：

- **DB 主写失败必须上抛**：`save_canvas_db` 出错抛 `HTTPException` 或子类，
  不允许 fallback 到 JSON 主写（避免"双主写分叉"）。
- **JSON 异步回写允许失败静默**：`_async_write_json_fallback` 内部异常仅
  warning + `data/shadow_diff/canvas_json_fallback/*.jsonl`，不冒泡。
- **乐观锁**：`WHERE base_updated_at = current_base_updated_at`；若指定
  `base_updated_at` 与 DB 现值不匹配则抛 `CanvasConflictError` (HTTP 409)，
  detail 键位与路由层 `main.py:16286` 保持字节等价。
- **Provider 凭据零落 DB**：Canvas 域不涉及 Provider；`content_json` 仅做
  字节等价镜像，与 shadow write 契约一致。

详见：

- [[40 实施计划/数据模型治理实施计划与PR清单]] PR-7
- [[30 治理方案/数据模型治理方案]] 迁移策略阶段 5
- [[60 讨论记录/2026-07-19 Wave 3-F-数据 PR-7 开工/2026-07-19 Wave 3-F-数据 PR-7
   开工协调纲要]]
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os
import threading
from typing import Any, Mapping

from fastapi import HTTPException

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class CanvasConflictError(HTTPException):
    """DB 主写路径下的乐观锁冲突。

    HTTP 409；`detail` shape 与路由层 `main.py:update_canvas` (L16286) 拒绝
    旧版本时的 `message` 键保持字节等价，前端解析路径不区分冲突来源。
    """

    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            detail={"message": "画布已被其他页面更新，已拒绝旧版本覆盖。"},
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _now_ms() -> int:
    # 与 `main.now_ms` 字节等价；避免 import main（后者会顶层加载整个应用）。
    import time

    return int(time.time() * 1000)


def _now_utc() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _compute_content_hash(content_json: str) -> str:
    """`sha256(content_json.encode("utf-8"))` hex digest。"""

    return hashlib.sha256(content_json.encode("utf-8")).hexdigest()


def _serialize_content_json(canvas: Mapping[str, Any]) -> str:
    """把 canvas dict 序列化为**与老 `main.save_canvas` 落盘字节等价**的 JSON。

    老 `main.save_canvas` 使用 `json.dump(canvas, f, ensure_ascii=False, indent=2)`；
    这里复现同一参数，保证 `content_json` 与 JSON 回写文件字节等价。
    """

    return json.dumps(canvas, ensure_ascii=False, indent=2)


def _build_row(
    canvas: Mapping[str, Any],
    *,
    content_json: str,
    content_hash: str,
) -> dict[str, Any]:
    """构造 upsert 用的 row dict（与 shadow_write.runner 保持字段列表一致）。"""

    imported_at = _now_utc()
    legacy_id = canvas.get("id")
    return {
        "legacy_id": str(legacy_id) if legacy_id is not None else None,
        "title": canvas.get("title") or None,
        "kind": canvas.get("kind") or None,
        "project_legacy_id": _stringify(canvas.get("project")),
        "owner_label": canvas.get("owner") or None,
        "pinned": bool(canvas.get("pinned", False)),
        "content_json": content_json,
        "content_hash": content_hash,
        "revision": int(canvas.get("revision") or 0),
        "base_updated_at": _stringify(canvas.get("base_updated_at")),
        "deleted_at": _stringify(canvas.get("deleted_at")),
        "raw_json": json.dumps(
            {
                "id": canvas.get("id"),
                "title": canvas.get("title"),
                "kind": canvas.get("kind"),
                "revision": canvas.get("revision"),
                "updated_at": canvas.get("updated_at"),
                "created_at": canvas.get("created_at"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "schema_version": "v1_legacy_json",
        "imported_at": imported_at,
        "created_at": imported_at,
        "updated_at": imported_at,
    }


# ---------------------------------------------------------------------------
# DB 主写
# ---------------------------------------------------------------------------


def _fetch_current_row(conn, legacy_id: str) -> tuple[bool, str | None]:
    """读 DB 当前 row 的 `base_updated_at`；返回 `(exists, base_updated_at)`。

    条件更新（乐观锁）比对语义：

    - `exists == False` → 首次插入，无冲突可比。
    - `exists == True` → 用返回的 `base_updated_at` 与调用方传入值做严格
      相等比对（`None` 也视为一个具体值）。
    """

    from sqlalchemy import select

    from app.data_import import tables as t

    row = conn.execute(
        select(t.canvases.c.base_updated_at).where(
            t.canvases.c.legacy_id == legacy_id
        )
    ).fetchone()
    if row is None:
        return False, None
    return True, row.base_updated_at


def save_canvas_db(canvas: dict) -> None:
    """DB 主写 canvas。

    副作用（in-place 修改传入 canvas dict）：

    - `canvas["updated_at"] = now_ms()`（与老 `main.save_canvas` 字节等价）。
    - `canvas["revision"] = (canvas.get("revision") or 0) + 1`。
    - `canvas["base_updated_at"] = canvas["updated_at"]`（成功后同步）。

    抛错语义：

    - 缺 `id` → `HTTPException(400)`。
    - 乐观锁冲突（DB 现值 `base_updated_at` 与传入 `base_updated_at` 不一致
      且 DB 已有记录）→ `CanvasConflictError` (409)。
    - 其他 DB 错误 → 原样上抛（**不吞异常、不 fallback 到 JSON 主写**）。
    """

    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.shared.ids import generate_id

    legacy_id = canvas.get("id")
    if not legacy_id:
        raise HTTPException(status_code=400, detail="无效的画布 ID")
    legacy_id_str = str(legacy_id)

    # 保留调用方传入的 base_updated_at（乐观锁比对用），随后再更新 canvas
    # 内的字段。为了与老 `main.save_canvas` 语义一致，`updated_at` 用毫秒
    # 时间戳；`revision` 单调递增。
    expected_base = _stringify(canvas.get("base_updated_at"))

    canvas["updated_at"] = _now_ms()
    canvas["revision"] = int(canvas.get("revision") or 0) + 1
    # 写入 DB 的 base_updated_at 列 = 新 updated_at 字符串（作为下一次写入的
    # 乐观锁基线）。调用方传入的 base_updated_at 只做比对，不进 row。
    new_base_updated_at = str(canvas["updated_at"])
    # CB-P5-10 · 数据 PR-15 内嵌承接：先把 canvas["base_updated_at"] 对齐到
    # 新基线，**再**做 content_json 序列化——这样 DB 的 `content_json` 与
    # 异步 JSON 回写文件字段字节等价，避免 base_updated_at 序列化时序漂移。
    # 修复前：content_json 里的 base_updated_at 是"旧基线"（客户端传入值），
    # 而异步 JSON 回写用的是已 mutate 后的 canvas（新基线），二者不字节等价。
    canvas["base_updated_at"] = new_base_updated_at

    content_json = _serialize_content_json(canvas)
    content_hash = _compute_content_hash(content_json)
    row = _build_row(canvas, content_json=content_json, content_hash=content_hash)
    # 覆盖 row 中的 base_updated_at：写入 DB 的值必须是"新的基线"而非
    # "客户端刚才用来比对的旧基线"（`_build_row` 已从 canvas 读到新值，
    # 这里的显式赋值是防御 build_row 未来重构漂移的护栏）。
    row["base_updated_at"] = new_base_updated_at

    engine = get_engine()
    with engine.begin() as conn:
        exists, current_base = _fetch_current_row(conn, legacy_id_str)
        if exists and current_base != expected_base:
            # DB 已有记录且传入 base_updated_at 与 DB 现值不匹配 → 409。
            # 注意：`expected_base is None`（客户端未提供）也算不匹配——严格
            # 语义避免"客户端漏传基线时静默覆盖别人的更新"。
            raise CanvasConflictError()

        stmt = sqlite_insert(t.canvases).values(id=generate_id(), **row)
        update_cols = {
            "title": stmt.excluded.title,
            "kind": stmt.excluded.kind,
            "project_legacy_id": stmt.excluded.project_legacy_id,
            "owner_label": stmt.excluded.owner_label,
            "pinned": stmt.excluded.pinned,
            "content_json": stmt.excluded.content_json,
            "content_hash": stmt.excluded.content_hash,
            "revision": stmt.excluded.revision,
            "base_updated_at": stmt.excluded.base_updated_at,
            "deleted_at": stmt.excluded.deleted_at,
            "raw_json": stmt.excluded.raw_json,
            "schema_version": stmt.excluded.schema_version,
            "updated_at": stmt.excluded.updated_at,
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["legacy_id"], set_=update_cols
        )
        conn.execute(stmt)

    # CB-P5-10 · canvas base_updated_at 已在序列化前对齐到新基线（见上方
    # 承接注释）；此处不再重复赋值，保留注释作 zero-touch 护栏说明。


def load_canvas_db(canvas_id: str) -> dict | None:
    """从 DB 读回 canvas（DB 主模式下调用）。

    - 命中 → 返回反序列化后的 dict。
    - 未命中 / `content_json is NULL` → 返回 `None`（上层决定 fallback JSON）。
    - JSON 反序列化失败 → warning + 返回 `None`（治理期宽松，不阻塞读路径）。
    """

    from sqlalchemy import select

    from app.data_import import tables as t
    from app.db.engine import get_engine

    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            select(t.canvases.c.content_json).where(
                t.canvases.c.legacy_id == str(canvas_id)
            )
        ).fetchone()
    if row is None or not row.content_json:
        return None
    try:
        return json.loads(row.content_json)
    except (TypeError, ValueError) as exc:  # pragma: no cover — 极端场景
        _LOG.warning(
            "canvas_writer.load_canvas_db: content_json decode failed id=%s err=%s",
            canvas_id,
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# JSON 异步回写（fallback）
# ---------------------------------------------------------------------------


_JSON_FALLBACK_LOCK = threading.Lock()
_JSON_FALLBACK_DIFF_KEYS: tuple[str, ...] = (
    "ts",
    "domain",
    "legacy_id",
    "error",
    "fallback_reason",
)


def _shadow_diff_root() -> str:
    """`<DATA_DIR>/shadow_diff`；DATA_DIR 走 Settings 读时求值。"""

    try:
        from app.shared.settings import get_settings

        base = get_settings().data_dir
    except Exception:  # pragma: no cover — settings 不可用时回退
        base = os.path.join(os.getcwd(), "data")
    return os.path.join(base, "shadow_diff")


def _today_utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d")


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _record_json_fallback_failure(
    *,
    legacy_id: str,
    error: str,
    fallback_reason: str = "json_write_error",
) -> str | None:
    """把 JSON 回写失败落 `data/shadow_diff/canvas_json_fallback/<yyyymmdd>.jsonl`。

    失败仅 warning，绝不 raise（隔离契约）。
    """

    record = {
        "ts": _now_iso(),
        "domain": "canvas",
        "legacy_id": str(legacy_id),
        "error": str(error),
        "fallback_reason": str(fallback_reason),
    }
    dir_path = os.path.join(_shadow_diff_root(), "canvas_json_fallback")
    file_path = os.path.join(dir_path, f"{_today_utc()}.jsonl")
    line = json.dumps(record, ensure_ascii=False, sort_keys=False) + "\n"
    try:
        os.makedirs(dir_path, exist_ok=True)
        with _JSON_FALLBACK_LOCK:
            with open(file_path, "a", encoding="utf-8") as fh:
                fh.write(line)
        return file_path
    except Exception as exc:  # pragma: no cover — 失败隔离
        _LOG.warning(
            "canvas_writer: json_fallback diff write failed id=%s err=%s",
            legacy_id,
            exc,
        )
        return None


def _write_json_fallback_sync(canvas: Mapping[str, Any]) -> None:
    """同步写 JSON 文件（供异步 helper 内部调用）。

    - 复现 `main.save_canvas` 落盘字节：`json.dump(canvas, f, ensure_ascii=False, indent=2)`。
    - 失败仅 warning + shadow diff，绝不 raise（主写已成功，回写只是回退准备）。
    """

    legacy_id = str(canvas.get("id") or "")
    try:
        # 懒 import main：canvas_path/CANVAS_LOCK 都在主模块，避免顶层循环。
        import main

        path = main.canvas_path(legacy_id)
        # 用 main.CANVAS_LOCK 与老 JSON 主写共享同一把锁，避免读者读到半写盘。
        with main.CANVAS_LOCK:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(dict(canvas), fh, ensure_ascii=False, indent=2)
    except Exception as exc:  # 隔离契约：写失败仅 warning，不 raise
        _LOG.warning(
            "canvas_writer: json_fallback write failed id=%s err=%s",
            legacy_id,
            exc,
        )
        try:
            _record_json_fallback_failure(
                legacy_id=legacy_id,
                error=str(exc),
                fallback_reason="json_write_error",
            )
        except Exception:  # pragma: no cover — nested failure guard
            _LOG.warning(
                "canvas_writer: diff writer also failed id=%s", legacy_id
            )


def _async_write_json_fallback(canvas: dict) -> None:
    """异步把 canvas 回写到 JSON 文件（供 DB 主写成功后触发）。

    - 优先走 `asyncio.create_task` 走入事件循环；如果调用点不在事件循环里，
      使用 `threading.Thread(daemon=True)` 完成。
    - **不阻塞主写路径**；本函数立即返回。
    - 内部异常一律吞掉（走 `_write_json_fallback_sync` 的失败隔离契约）。
    """

    snapshot = dict(canvas)  # 拷贝一份，避免异步执行时被 in-place 修改

    def _target() -> None:
        # 顶层再兜一次异常：即便 `_write_json_fallback_sync` 内部隔离契约被
        # 未来某次改动或测试 monkeypatch 破坏，异步任务也不至于 leak 未捕获
        # 异常到线程/事件循环层（会污染 pytest warning）。
        try:
            _write_json_fallback_sync(snapshot)
        except Exception as exc:  # pragma: no cover — nested guard
            _LOG.warning(
                "canvas_writer: async json_fallback target raised err=%s", exc
            )

    # 优先尝试事件循环；不在事件循环里就退化为后台线程。
    try:
        import asyncio

        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        try:
            # run_in_executor：默认线程池；不占用事件循环 CPU。
            loop.run_in_executor(None, _target)
            return
        except Exception:  # pragma: no cover — 事件循环拒绝调度
            pass

    # 无事件循环 / 调度失败 → 走后台线程。daemon=True 避免阻塞进程退出。
    threading.Thread(target=_target, daemon=True).start()


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


__all__ = [
    "CanvasConflictError",
    "save_canvas_db",
    "load_canvas_db",
]
