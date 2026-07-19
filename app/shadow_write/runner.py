"""`app.shadow_write.runner` — Canvas 短窗双写入口。

`run_shadow_write(domain, snapshot, *, request_id=None)`：JSON 主写成功后
调用；本函数：

1. 门禁：只有 `SHADOW_WRITE_<DOMAIN>` env=truthy 时才继续（未启用零副作用）。
2. Canvas 域：把 `{legacy_id, title, kind, project_legacy_id, owner_label,
   pinned, content_json, content_hash, revision, base_updated_at, deleted_at,
   raw_json, schema_version, imported_at, created_at, updated_at}` upsert 到
   `canvases` 表（`legacy_id` 冲突走 `on_conflict_do_update`）。
3. 失败仅落 `data/shadow_diff/canvas_write/<yyyymmdd>.jsonl` 一行 warning，
   永不 raise 到调用方。

**写延迟上限**：单接口 P95 不超过 500ms（治理方案 §PR-6 P1 硬约束）。
`sha256(content_json)` 与 upsert 都在同线程完成，避免线程池扇出复杂度。

**读/写路径独立**：不 import `app.shadow_read.*` 内部符号；两条链路各自
独立扩展。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os
from typing import Any, Mapping

from app.shadow_write.diff_writer import write_write_failure

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# env gate
# ---------------------------------------------------------------------------

_TRUTHY = frozenset({"1", "true", "yes", "on", "enable", "enabled"})

_DOMAIN_TO_ENV: Mapping[str, str] = {
    "canvas": "SHADOW_WRITE_CANVAS",
}

SUPPORTED_SHADOW_WRITE_DOMAINS: tuple[str, ...] = ("canvas",)


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUTHY


def is_shadow_write_enabled(domain: str) -> bool:
    """Return whether shadow write is enabled for the given domain.

    默认 `False`；未知域始终 `False`。读 env 现读（不缓存），测试可
    `monkeypatch.setenv` 切换。
    """

    env_name = _DOMAIN_TO_ENV.get(domain)
    if env_name is None:
        return False
    return _env_truthy(env_name)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _now_utc() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _compute_content_hash(content_json: str) -> str:
    """`sha256(content_json.encode("utf-8"))` hex digest。"""

    return hashlib.sha256(content_json.encode("utf-8")).hexdigest()


def _read_canvas_disk_bytes(canvas_id: str) -> bytes | None:
    """读回 `main.save_canvas` 刚落盘的字节。

    以磁盘字节为 hash 权威来源，避免 `json.dumps` 的 in-memory 字节与 Windows
    text-mode `json.dump` 落盘字节因 `\\r\\n` / `\\n` 转换而不一致；importer
    (`_record_from_payload`) 也走同一"读磁盘"语义，保证两侧 hash 精确匹配。

    读失败（文件被并发删除等）→ 返回 `None`，调用方降级为 in-memory 序列化。
    """

    try:
        import main  # 懒 import 避免循环

        path = main.canvas_path(canvas_id)
        with open(path, "rb") as fh:
            return fh.read()
    except Exception:  # pragma: no cover — 失败隔离
        return None


def _serialize_content_json(snapshot: Mapping[str, Any]) -> str:
    """把 canvas dict 序列化为**字节等价于 `main.save_canvas` 落盘**的 JSON。

    优先读磁盘上刚落盘的字节（避免 Windows text-mode `\\r\\n` 差异）；
    读盘失败时回退到 in-memory `json.dumps`。
    """

    legacy_id = snapshot.get("id")
    if legacy_id is not None:
        raw = _read_canvas_disk_bytes(str(legacy_id))
        if raw is not None:
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:  # pragma: no cover — 极端场景
                pass
    return json.dumps(snapshot, ensure_ascii=False, indent=2)


def _canvas_record_from_snapshot(
    snapshot: Mapping[str, Any],
    *,
    content_json: str,
    content_hash: str,
) -> dict[str, Any]:
    """Compose the row dict written into `canvases` (upsert-ready)."""

    imported_at = _now_utc()
    legacy_id = snapshot.get("id")
    return {
        "legacy_id": str(legacy_id) if legacy_id is not None else None,
        "title": snapshot.get("title") or None,
        "kind": snapshot.get("kind") or None,
        "project_legacy_id": _stringify(snapshot.get("project")),
        "owner_label": snapshot.get("owner") or None,
        "pinned": bool(snapshot.get("pinned", False)),
        "content_json": content_json,
        "content_hash": content_hash,
        "revision": int(snapshot.get("revision") or 0),
        "base_updated_at": _stringify(snapshot.get("base_updated_at")),
        "deleted_at": _stringify(snapshot.get("deleted_at")),
        "raw_json": json.dumps(
            {
                "id": snapshot.get("id"),
                "title": snapshot.get("title"),
                "kind": snapshot.get("kind"),
                "revision": snapshot.get("revision"),
                "updated_at": snapshot.get("updated_at"),
                "created_at": snapshot.get("created_at"),
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
# DB writer
# ---------------------------------------------------------------------------


def _upsert_canvas(record: Mapping[str, Any]) -> None:
    """Upsert a canvas row keyed on `legacy_id`.

    Errors bubble up to the caller (`run_shadow_write` catches & downgrades to
    warning + diff jsonl).
    """

    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.shared.ids import generate_id

    engine = get_engine()
    stmt = sqlite_insert(t.canvases).values(id=generate_id(), **record)
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
    with engine.begin() as conn:
        conn.execute(stmt)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def run_shadow_write(
    domain: str,
    snapshot: Any,
    *,
    request_id: str | None = None,
) -> dict[str, Any] | None:
    """Run shadow write for `domain`; return the upserted record or `None`.

    - **主写契约**：返回值永不进入 HTTP 响应；调用点应忽略返回值。
    - 门禁未开启 → 立即 `return None`，不做任何 DB / 磁盘 IO。
    - 成功 → 返回 upsert 用的 record dict（不含 hash 字段以外的敏感信息）。
    - 失败 → 落 `data/shadow_diff/canvas_write/<yyyymmdd>.jsonl` 一行 warning
      + 返回 `None`；绝不 raise。
    - Provider 凭据不涉及本域；`content_json` 只做字节等价镜像。
    """

    if domain not in SUPPORTED_SHADOW_WRITE_DOMAINS:
        return None
    if not is_shadow_write_enabled(domain):
        return None
    if not isinstance(snapshot, Mapping):
        _LOG.warning(
            "shadow_write: snapshot must be a mapping domain=%s got=%s",
            domain,
            type(snapshot).__name__,
        )
        return None

    try:
        content_json = _serialize_content_json(snapshot)
        content_hash = _compute_content_hash(content_json)
        record = _canvas_record_from_snapshot(
            snapshot,
            content_json=content_json,
            content_hash=content_hash,
        )
        if not record.get("legacy_id"):
            _LOG.warning(
                "shadow_write: canvas snapshot missing 'id'; skip request_id=%s",
                request_id,
            )
            return None
        _upsert_canvas(record)
        return record
    except Exception as exc:  # pragma: no cover — 失败隔离契约
        _LOG.warning(
            "shadow_write: run_shadow_write failed domain=%s err=%s",
            domain,
            exc,
        )
        try:
            write_write_failure(
                domain=domain,
                legacy_id=str((snapshot or {}).get("id") or ""),
                error=str(exc),
                request_id=request_id,
            )
        except Exception:  # pragma: no cover — nested failure guard
            _LOG.warning("shadow_write: diff writer also failed domain=%s", domain)
        return None


__all__ = [
    "SUPPORTED_SHADOW_WRITE_DOMAINS",
    "is_shadow_write_enabled",
    "run_shadow_write",
]
