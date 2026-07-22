"""`app.shadow_read.runner` — 通用 shadow read 入口。

`run_shadow_read(domain, json_result, *, request_id=None)`：JSON 主读成功
后调用；本函数：

1. 门禁：只有 `SHADOW_READ_<DOMAIN>` env=truthy 时才继续（未启用零副作用）。
2. 从 `data/app.db` 读 baseline snapshot；表由数据 PR-3 `0002_baseline_tables`
   建，本 PR 不建表、不迁移。
3. 按稳定字段集比较：
   - `missing_in_db`：JSON 有但 DB 没有的 legacy_id。
   - `missing_in_json`：DB 有但 JSON 没有的 legacy_id。
   - `field_diffs`：交集内每个 legacy_id 的稳定字段差异。
4. 有 diff 时落盘 `data/shadow_diff/<domain>/<yyyymmdd>.jsonl`；无差异
   时不写盘（避免噪声与磁盘占用）。
5. 全程失败隔离；任何异常仅 warning。

**读延迟上限**：单接口 P95 不超过 20ms（治理方案硬约束）。为此本函数：

- 一次性建 engine + 一条 `select(legacy_id, name, ...)` 查询；不做 N+1。
- shadow diff 空时不写盘。
- 全流程无远程调用、无网络 IO。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Mapping

from app.shadow_read.diff_writer import build_diff_record, write_diff_record
from app.shadow_read.fields import (
    STABLE_FIELDS_BY_DOMAIN,
    SUPPORTED_SHADOW_DOMAINS,
)


_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# env gate
# ---------------------------------------------------------------------------

_TRUTHY = frozenset({"1", "true", "yes", "on", "enable", "enabled"})

_DOMAIN_TO_ENV: Mapping[str, str] = {
    "project": "SHADOW_READ_PROJECT",
    "provider_config": "SHADOW_READ_PROVIDER_CONFIG",
    "prompt_library": "SHADOW_READ_PROMPT_LIBRARY",
    "workflow_definition": "SHADOW_READ_WORKFLOW_DEFINITION",
    "canvas": "SHADOW_READ_CANVAS",
}


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUTHY


def is_shadow_read_enabled(domain: str) -> bool:
    """Return whether shadow read is enabled for the given domain.

    All four env vars default to `false`; unknown domains always return
    `False`. Reads env at call time (not at import time) so tests can
    toggle via `monkeypatch.setenv`.
    """

    env_name = _DOMAIN_TO_ENV.get(domain)
    if env_name is None:
        return False
    return _env_truthy(env_name)


# ---------------------------------------------------------------------------
# JSON → normalized records (legacy_id → {stable_field: value})
# ---------------------------------------------------------------------------


def _normalize_json_project(payload: Any) -> dict[str, dict[str, Any]]:
    """JSON `load_projects()` 返回 `[project dict, ...]`。"""

    if isinstance(payload, dict):
        payload = payload.get("projects") or []
    if not isinstance(payload, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        legacy_id = entry.get("id")
        if not legacy_id:
            continue
        out[str(legacy_id)] = {
            "id": entry.get("id"),
            "name": entry.get("name"),
            "order": entry.get("order"),
        }
    return out


def _normalize_json_provider(payload: Any) -> dict[str, dict[str, Any]]:
    """provider snapshot payload 已由 `_safe_provider_records` 深层脱敏。"""

    if not isinstance(payload, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        legacy_id = entry.get("id") or entry.get("name")
        if not legacy_id:
            continue
        out[str(legacy_id)] = {
            "id": entry.get("id"),
            "name": entry.get("name"),
            "base_url": entry.get("base_url"),
            "protocol": entry.get("protocol"),
            "image_request_mode": entry.get("image_request_mode"),
            "enabled": bool(entry.get("enabled", True)),
            "primary": bool(entry.get("primary", False)),
        }
    return out


def _normalize_json_prompt_library(payload: Any) -> dict[str, dict[str, Any]]:
    """`load_prompt_libraries()` 返回 `{active_library_id, libraries[]}`。"""

    if isinstance(payload, dict):
        libs = payload.get("libraries") or []
    elif isinstance(payload, list):
        libs = payload
    else:
        libs = []
    out: dict[str, dict[str, Any]] = {}
    for entry in libs:
        if not isinstance(entry, dict):
            continue
        legacy_id = entry.get("id")
        if not legacy_id:
            continue
        out[str(legacy_id)] = {
            "id": entry.get("id"),
            "name": entry.get("name"),
            "scope": entry.get("scope"),
        }
    return out


def _normalize_json_workflow_definition(payload: Any) -> dict[str, dict[str, Any]]:
    """RunningHub workflow store shape `{providers: [{provider_id, workflows[], apps[]}]}`
    + `workflows/*.json` 内置文件。按 importer 相同规则合成 legacy_id。"""

    out: dict[str, dict[str, Any]] = {}

    # RunningHub side
    providers = payload.get("providers") if isinstance(payload, dict) else None
    if isinstance(providers, list):
        for provider in providers:
            if not isinstance(provider, dict):
                continue
            provider_id = str(provider.get("provider_id") or provider.get("id") or "")
            if not provider_id:
                continue
            for kind_key in ("workflows", "apps"):
                items = provider.get(kind_key) or []
                if not isinstance(items, list):
                    continue
                for wf in items:
                    if not isinstance(wf, dict):
                        continue
                    wf_id = str(
                        wf.get("id")
                        or wf.get("workflow_id")
                        or wf.get("app_id")
                        or ""
                    )
                    if not wf_id:
                        continue
                    legacy_id = f"rh:{provider_id}:{kind_key}:{wf_id}"
                    out[legacy_id] = {
                        "legacy_id": legacy_id,
                        "name": wf.get("name"),
                        "provider_id": provider_id,
                        "kind": kind_key.rstrip("s"),
                    }

    # Built-in workflow files
    try:
        from app.shared.settings import get_settings

        settings = get_settings()
        wf_dir = settings.workflow_dir
    except Exception:
        wf_dir = None

    if wf_dir and os.path.isdir(wf_dir):
        try:
            for name in sorted(os.listdir(wf_dir)):
                if not name.lower().endswith(".json"):
                    continue
                legacy_id = f"file:{name}"
                out[legacy_id] = {
                    "legacy_id": legacy_id,
                    "name": name.rsplit(".", 1)[0],
                    "provider_id": None,
                    "kind": "builtin",
                }
        except OSError:  # pragma: no cover
            pass

    return out


def _normalize_json_canvas(payload: Any) -> dict[str, dict[str, Any]]:
    """`load_canvas()` 返回单个 canvas dict；映射 `project` → `project_legacy_id`，
    `owner` → `owner_label` 以对齐 DB 表列名。"""

    if not isinstance(payload, dict):
        return {}
    legacy_id = payload.get("id")
    if not legacy_id:
        return {}
    return {
        str(legacy_id): {
            "id": payload.get("id"),
            "title": payload.get("title"),
            "kind": payload.get("kind"),
            "project_legacy_id": payload.get("project"),
            "owner_label": payload.get("owner"),
            "pinned": bool(payload.get("pinned", False)),
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
            "deleted_at": payload.get("deleted_at"),
            "revision": payload.get("revision", 0),
            "base_updated_at": payload.get("base_updated_at"),
        }
    }


_NORMALIZERS: Mapping[str, Callable[[Any], dict[str, dict[str, Any]]]] = {
    "project": _normalize_json_project,
    "provider_config": _normalize_json_provider,
    "prompt_library": _normalize_json_prompt_library,
    "workflow_definition": _normalize_json_workflow_definition,
    "canvas": _normalize_json_canvas,
}


# ---------------------------------------------------------------------------
# DB snapshot loaders
# ---------------------------------------------------------------------------


def _load_db_snapshot(domain: str) -> dict[str, dict[str, Any]]:
    """Load `{legacy_id: {stable_field: value}}` from the baseline tables.

    Missing / non-existent DB or table → returns `{}` (treated as "DB empty").
    Any error → warning + `{}`; never raises.
    """

    try:
        from sqlalchemy import select

        from app.data_import import tables as t
        from app.db.engine import get_engine
    except Exception as exc:  # pragma: no cover
        _LOG.warning("shadow_read: sqlalchemy layer unavailable domain=%s err=%s", domain, exc)
        return {}

    domain_to_query = {
        "project": (
            t.projects,
            [t.projects.c.legacy_id, t.projects.c.name, t.projects.c.order_index, t.projects.c.raw_json],
        ),
        "provider_config": (
            t.provider_configs,
            [
                t.provider_configs.c.legacy_id,
                t.provider_configs.c.name,
                t.provider_configs.c.base_url,
                t.provider_configs.c.protocol,
                t.provider_configs.c.image_request_mode,
                t.provider_configs.c.enabled,
                t.provider_configs.c.primary_flag,
            ],
        ),
        "prompt_library": (
            t.prompt_libraries,
            [
                t.prompt_libraries.c.legacy_id,
                t.prompt_libraries.c.name,
                t.prompt_libraries.c.scope,
            ],
        ),
        "workflow_definition": (
            t.workflow_definitions,
            [
                t.workflow_definitions.c.legacy_id,
                t.workflow_definitions.c.name,
                t.workflow_definitions.c.provider_id,
                t.workflow_definitions.c.kind,
            ],
        ),
        "canvas": (
            t.canvases,
            [
                t.canvases.c.legacy_id,
                t.canvases.c.title,
                t.canvases.c.kind,
                t.canvases.c.project_legacy_id,
                t.canvases.c.owner_label,
                t.canvases.c.pinned,
                t.canvases.c.created_at,
                t.canvases.c.updated_at,
                t.canvases.c.deleted_at,
                t.canvases.c.revision,
                t.canvases.c.base_updated_at,
            ],
        ),
    }

    entry = domain_to_query.get(domain)
    if entry is None:
        return {}
    table, columns = entry
    try:
        engine = get_engine()
        with engine.connect() as conn:
            # Table missing (migrations not run) → SQLite raises OperationalError.
            try:
                rows = conn.execute(select(*columns)).fetchall()
            except Exception as exc:
                _LOG.debug(
                    "shadow_read: DB query failed (table likely absent) domain=%s err=%s",
                    domain,
                    exc,
                )
                return {}
    except Exception as exc:
        _LOG.warning("shadow_read: engine open failed domain=%s err=%s", domain, exc)
        return {}

    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        mapping = dict(row._mapping)
        legacy_id = mapping.get("legacy_id")
        if legacy_id is None:
            continue
        record = _project_db_row_to_stable(domain, mapping)
        out[str(legacy_id)] = record
    return out


def _project_db_row_to_stable(
    domain: str, row: dict[str, Any]
) -> dict[str, Any]:
    """Convert a DB row to `{stable_field: value}` for the given domain."""

    if domain == "project":
        return {
            "id": row.get("legacy_id"),
            "name": row.get("name"),
            "order": row.get("order_index"),
        }
    if domain == "provider_config":
        return {
            "id": row.get("legacy_id"),
            "name": row.get("name"),
            "base_url": row.get("base_url"),
            "protocol": row.get("protocol"),
            "image_request_mode": row.get("image_request_mode"),
            "enabled": bool(row.get("enabled", True)),
            "primary": bool(row.get("primary_flag", False)),
        }
    if domain == "prompt_library":
        return {
            "id": row.get("legacy_id"),
            "name": row.get("name"),
            "scope": row.get("scope"),
        }
    if domain == "workflow_definition":
        return {
            "legacy_id": row.get("legacy_id"),
            "name": row.get("name"),
            "provider_id": row.get("provider_id"),
            "kind": row.get("kind"),
        }
    if domain == "canvas":
        def _iso(v: Any) -> Any:
            """Convert datetime to ISO string for JSON-safe serialization."""
            if hasattr(v, "isoformat"):
                return v.isoformat()
            return v

        return {
            "id": row.get("legacy_id"),
            "title": row.get("title"),
            "kind": row.get("kind"),
            "project_legacy_id": row.get("project_legacy_id"),
            "owner_label": row.get("owner_label"),
            "pinned": bool(row.get("pinned", False)),
            "created_at": _iso(row.get("created_at")),
            "updated_at": _iso(row.get("updated_at")),
            "deleted_at": row.get("deleted_at"),
            "revision": row.get("revision", 0),
            "base_updated_at": row.get("base_updated_at"),
        }
    return {}


# ---------------------------------------------------------------------------
# Diff engine
# ---------------------------------------------------------------------------


def _compare_snapshots(
    domain: str,
    json_snapshot: dict[str, dict[str, Any]],
    db_snapshot: dict[str, dict[str, Any]],
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """Return `(missing_in_db, missing_in_json, field_diffs)`."""

    stable_fields = STABLE_FIELDS_BY_DOMAIN.get(domain, frozenset())
    json_ids = set(json_snapshot)
    db_ids = set(db_snapshot)
    missing_in_db = sorted(json_ids - db_ids)
    missing_in_json = sorted(db_ids - json_ids)
    common = json_ids & db_ids

    field_diffs: list[dict[str, Any]] = []
    for legacy_id in sorted(common):
        j_rec = json_snapshot[legacy_id]
        d_rec = db_snapshot[legacy_id]
        for field in stable_fields:
            j_val = j_rec.get(field)
            d_val = d_rec.get(field)
            if j_val != d_val:
                field_diffs.append({
                    "legacy_id": legacy_id,
                    "field": field,
                    "json_value": j_val,
                    "db_value": d_val,
                })
    return missing_in_db, missing_in_json, field_diffs


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def run_shadow_read(
    domain: str,
    json_result: Any,
    *,
    request_id: str | None = None,
) -> dict[str, Any] | None:
    """Run shadow read + diff for `domain`; return the diff record or `None`.

    - **主读契约**：返回值永不进入 HTTP 响应；调用点应忽略返回值（保留返回
      值仅供测试与内部日志消费）。
    - 门禁未开启 → 立即 `return None`，不做任何 DB / 磁盘 IO。
    - 有差异 → 落盘 `data/shadow_diff/<domain>/<yyyymmdd>.jsonl` 一行；返回
      diff record dict（键位见 `diff_writer.DIFF_RECORD_KEYS`）。
    - 无差异 → 不落盘；返回 `None`。
    - 任何异常 → warning + 返回 `None`；绝不 raise。
    """

    if domain not in SUPPORTED_SHADOW_DOMAINS:
        return None
    if not is_shadow_read_enabled(domain):
        return None

    try:
        normalizer = _NORMALIZERS.get(domain)
        if normalizer is None:
            return None
        json_snapshot = normalizer(json_result)
        db_snapshot = _load_db_snapshot(domain)
        if domain == "canvas":
            # CB-P5-08b · 数据 PR-15 内嵌承接：canvas 域是单-id load 路径，
            # 只对该 id 判定（不 O(N) 扫描其它 canvas）。收敛后
            # `missing_in_json` 语义变为"这一次 load 覆盖的 id 集合上的差集"，
            # 消除 shadow_diff 假 missing 噪声。
            from app.shadow_read.canvas_normalizer import (
                scope_db_snapshot_to_json,
            )

            db_snapshot = scope_db_snapshot_to_json(json_snapshot, db_snapshot)
        missing_in_db, missing_in_json, field_diffs = _compare_snapshots(
            domain, json_snapshot, db_snapshot
        )
        if not (missing_in_db or missing_in_json or field_diffs):
            return None
        record = build_diff_record(
            domain=domain,
            missing_in_db=missing_in_db,
            missing_in_json=missing_in_json,
            field_diffs=field_diffs,
            request_id=request_id,
        )
        write_diff_record(record)
        return record
    except Exception as exc:  # pragma: no cover — 失败隔离契约
        _LOG.warning(
            "shadow_read: run_shadow_read failed domain=%s err=%s", domain, exc
        )
        return None


__all__ = [
    "is_shadow_read_enabled",
    "run_shadow_read",
]
