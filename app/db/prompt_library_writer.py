"""`app.db.prompt_library_writer` — 数据 PR-8 PromptLibrary DB 主写路径。

只有 `PROMPT_LIBRARY_PRIMARY_WRITE=db` 时，`prompt_library_store.save_prompt_libraries`
才 import 本模块（默认 `json` 路径**不 import**）。

关键契约（治理期）：

- **D-2=B 决策**：PromptLibrary items **全塞 `prompt_libraries.raw_json`**；
  `prompt_items` 表 PR-8 **不主写**（M2 后续 PR 展平）。整个 `{active_library_id,
  libraries: [...]}` payload 结构由 `raw_json` 承载。
- **集合级写事务**：单个事务里先 UPSERT 全部 library legacy_id 行（`raw_json`
  = 单库完整 payload 含 items），再 DELETE `legacy_id NOT IN payload`。
- **DB 主写失败必须上抛**（P0 硬约束 #4）。
- **JSON 异步回写允许失败静默**：`_async_write_json_fallback` 内部异常仅
  warning + `data/shadow_diff/prompt_library_json_fallback/*.jsonl`。
- **`system` / `readonly` / `version` 语义不变**：normalize 由 `main.save_prompt_libraries`
  的函数体承担（本 wrapper 只承接 UPSERT-DELETE，不改 normalize）。

详见：

- [[40 实施计划/数据模型治理实施计划与PR清单]] PR-8
- [[60 讨论记录/2026-07-19 Wave 3-G-数据 PR-8 开工]] 协调纲要
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import threading
from typing import Any, Iterable, Mapping

_LOG = logging.getLogger(__name__)


DOMAIN = "prompt_library"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _now_utc() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _today_utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d")


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _serialize_raw_json(payload: Any) -> str:
    try:
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=False, separators=(",", ":")
        )
    except (TypeError, ValueError):
        return "{}"


def _iter_libraries(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    libs = payload.get("libraries")
    if not isinstance(libs, list):
        return []
    return [lib for lib in libs if isinstance(lib, dict) and lib.get("id")]


def _build_row(
    library: Mapping[str, Any],
    payload: Mapping[str, Any],
    imported_at: _dt.datetime,
) -> dict[str, Any]:
    """Build UPSERT row for one library. `raw_json` = full library payload
    (含 items —— D-2=B 决策：不展平 `prompt_items` 表)."""

    legacy_id = library.get("id")
    # `raw_json` 保存整个库（含 items）；同时把 payload 顶层的
    # `active_library_id` 作为兄弟字段并入（走 D-2=B 的 raw_json 单一事实源）。
    library_payload = dict(library)
    library_payload.setdefault(
        "active_library_id", payload.get("active_library_id")
    )
    return {
        "legacy_id": str(legacy_id),
        "name": library.get("name") or None,
        "scope": library.get("scope") or ("system" if legacy_id == "system" else None),
        "raw_json": _serialize_raw_json(library_payload),
        "schema_version": "v1_legacy_json",
        "imported_at": imported_at,
        "created_at": imported_at,
        "updated_at": imported_at,
    }


# ---------------------------------------------------------------------------
# DB 主写
# ---------------------------------------------------------------------------


def save_prompt_libraries_db(payload: dict) -> None:
    """DB 主写整个 prompt libraries payload（集合级写事务）。

    - `payload` 结构：`{active_library_id, libraries: [{id, name, scope, items, ...}, ...],
      updated_at}`（`main.normalize_prompt_libraries` 输出）。
    - 单个事务里先 UPSERT 全部 library legacy_id 行（`raw_json` 存整个 library 含 items），
      再 DELETE `legacy_id NOT IN payload`。
    - 任何 DB 错误 → 原样上抛（**不 fallback**）。
    - **`prompt_items` 表 PR-8 不写**（D-2=B 决策）。
    """

    from sqlalchemy import delete
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.shared.ids import generate_id

    libraries = _iter_libraries(payload)
    imported_at = _now_utc()

    rows = [_build_row(lib, payload, imported_at) for lib in libraries]
    legacy_ids: list[str] = [row["legacy_id"] for row in rows]

    engine = get_engine()
    with engine.begin() as conn:
        # UPSERT 全部 library legacy_id
        for row in rows:
            stmt = sqlite_insert(t.prompt_libraries).values(
                id=generate_id(), **row
            )
            update_cols = {
                "name": stmt.excluded.name,
                "scope": stmt.excluded.scope,
                "raw_json": stmt.excluded.raw_json,
                "schema_version": stmt.excluded.schema_version,
                "updated_at": stmt.excluded.updated_at,
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=["legacy_id"], set_=update_cols
            )
            conn.execute(stmt)

        # DELETE `legacy_id NOT IN payload`
        if legacy_ids:
            conn.execute(
                delete(t.prompt_libraries).where(
                    t.prompt_libraries.c.legacy_id.notin_(legacy_ids)
                )
            )
        else:
            conn.execute(delete(t.prompt_libraries))


def load_prompt_libraries_db() -> dict | None:
    """从 DB 读回完整 payload（DB 主模式下调用）。

    - 有行 → 组装 `{active_library_id, libraries: [...], updated_at}`；
      `active_library_id` 从每行 `raw_json` 中取首个非空值。
    - 空 → `None`（上层决定 fallback JSON）。
    """

    from sqlalchemy import select

    from app.data_import import tables as t
    from app.db.engine import get_engine

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(t.prompt_libraries.c.raw_json).order_by(
                t.prompt_libraries.c.legacy_id.asc()
            )
        ).fetchall()

    if not rows:
        return None

    libraries: list[dict] = []
    active_id: str | None = None
    for row in rows:
        raw = row.raw_json
        if not raw:
            continue
        try:
            library = json.loads(raw)
        except (TypeError, ValueError) as exc:  # pragma: no cover
            _LOG.warning(
                "prompt_library_writer.load: raw_json decode failed err=%s", exc
            )
            continue
        if not isinstance(library, dict) or not library.get("id"):
            continue
        # active_library_id 是 payload 顶层字段；在 raw_json 里以兄弟字段方式保留
        if active_id is None:
            aid = library.pop("active_library_id", None)
            if aid:
                active_id = str(aid)
        else:
            library.pop("active_library_id", None)
        libraries.append(library)

    if not libraries:
        return None
    if not active_id:
        active_id = "system" if any(l.get("id") == "system" for l in libraries) else libraries[0]["id"]
    return {
        "active_library_id": active_id,
        "libraries": libraries,
    }


# ---------------------------------------------------------------------------
# JSON 异步回写（fallback）
# ---------------------------------------------------------------------------


_JSON_FALLBACK_LOCK = threading.Lock()


def _shadow_diff_root() -> str:
    try:
        from app.shared.settings import get_settings

        base = get_settings().data_dir
    except Exception:  # pragma: no cover
        base = os.path.join(os.getcwd(), "data")
    return os.path.join(base, "shadow_diff")


def _record_json_fallback_failure(
    *, error: str, fallback_reason: str = "json_write_error"
) -> str | None:
    """把 JSON 回写失败落
    `data/shadow_diff/prompt_library_json_fallback/<yyyymmdd>.jsonl`。

    失败仅 warning，绝不 raise。
    """

    record = {
        "ts": _now_iso(),
        "domain": DOMAIN,
        "error": str(error),
        "fallback_reason": str(fallback_reason),
    }
    dir_path = os.path.join(_shadow_diff_root(), "prompt_library_json_fallback")
    file_path = os.path.join(dir_path, f"{_today_utc()}.jsonl")
    line = json.dumps(record, ensure_ascii=False, sort_keys=False) + "\n"
    try:
        os.makedirs(dir_path, exist_ok=True)
        with _JSON_FALLBACK_LOCK:
            with open(file_path, "a", encoding="utf-8") as fh:
                fh.write(line)
        return file_path
    except Exception as exc:  # pragma: no cover
        _LOG.warning(
            "prompt_library_writer: json_fallback diff write failed err=%s", exc
        )
        return None


def _write_json_fallback_sync(payload: Mapping[str, Any]) -> None:
    """同步写 JSON 文件（供异步 helper 内部调用）。

    - 复现 `main.save_prompt_libraries` 落盘字节：
      `json.dump(payload, f, ensure_ascii=False, indent=2)`。
    - 失败仅 warning + shadow diff，绝不 raise。
    """

    try:
        import main

        os.makedirs(main.DATA_DIR, exist_ok=True)
        with open(main.PROMPT_LIBRARY_PATH, "w", encoding="utf-8") as fh:
            json.dump(dict(payload), fh, ensure_ascii=False, indent=2)
    except Exception as exc:
        _LOG.warning(
            "prompt_library_writer: json_fallback write failed err=%s", exc
        )
        try:
            _record_json_fallback_failure(
                error=str(exc), fallback_reason="json_write_error"
            )
        except Exception:  # pragma: no cover
            _LOG.warning("prompt_library_writer: diff writer also failed")


def _async_write_json_fallback(payload: Mapping[str, Any]) -> None:
    """异步把 payload 回写 JSON。"""

    snapshot = dict(payload) if payload else {}

    def _target() -> None:
        try:
            _write_json_fallback_sync(snapshot)
        except Exception as exc:  # pragma: no cover
            _LOG.warning(
                "prompt_library_writer: async json_fallback target raised err=%s",
                exc,
            )

    try:
        import asyncio

        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        try:
            loop.run_in_executor(None, _target)
            return
        except Exception:  # pragma: no cover
            pass

    threading.Thread(target=_target, daemon=True).start()


__all__ = [
    "save_prompt_libraries_db",
    "load_prompt_libraries_db",
]
