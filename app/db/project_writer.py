"""`app.db.project_writer` — 数据 PR-8 Project DB 主写路径。

只有 `PROJECT_PRIMARY_WRITE=db` 时，`project_store.save_projects` /
`.load_projects` 才 import 本模块（默认 `json` 路径**不 import**）。

关键契约（治理期）：

- **DB 主写失败必须上抛**：`save_projects_db` 出错抛异常，不允许 fallback
  到 JSON 主写（避免"双主写分叉"）；仅 JSON 异步回写允许失败静默。
- **集合级写事务**：整个 `projects` list 在一个 transaction 里先 UPSERT
  全部 legacy_id，再 DELETE `legacy_id NOT IN payload`；D-1=B 决策下不做
  乐观锁（`updated_at` 仅作诊断字段）。
- **JSON 异步回写允许失败静默**：`_async_write_json_fallback` 内部异常仅
  warning + `data/shadow_diff/project_json_fallback/*.jsonl`，不冒泡。
- **Provider 凭据零落 DB**：Project 域不涉及 Provider；`raw_json` 仅字节
  等价镜像每条 project entry。

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


DOMAIN = "project"


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


def _build_row(entry: Mapping[str, Any], imported_at: _dt.datetime) -> dict[str, Any]:
    """Build UPSERT row for one project entry. Byte-equivalent shape to
    `app.data_import.importers.project._record`."""

    legacy_id = entry.get("id")
    return {
        "legacy_id": str(legacy_id) if legacy_id is not None else None,
        "name": entry.get("name") or None,
        "order_index": int(entry.get("order") or 0),
        "raw_json": _serialize_raw_json(entry),
        "schema_version": "v1_legacy_json",
        "imported_at": imported_at,
        "created_at": imported_at,
        "updated_at": imported_at,
    }


def _valid_entries(projects: Iterable[Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for entry in projects or []:
        if not isinstance(entry, dict):
            continue
        if not entry.get("id"):
            continue
        entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# DB 主写
# ---------------------------------------------------------------------------


def save_projects_db(projects: list[dict]) -> None:
    """DB 主写整个 projects 列表（集合级写事务）。

    - 单个事务里先 UPSERT 全部 legacy_id 行，再 DELETE 所有 `legacy_id
      NOT IN payload` 行；保证 DB 与 payload 完全一致。
    - 不做乐观锁（D-1=B 决策；集合级并发极低，`updated_at` 仅作诊断）。
    - 任何 DB 错误 → 原样上抛（**不吞异常、不 fallback 到 JSON 主写**）。
    """

    from sqlalchemy import delete
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.shared.ids import generate_id

    entries = _valid_entries(projects)
    imported_at = _now_utc()

    rows = [_build_row(entry, imported_at) for entry in entries]
    legacy_ids: list[str] = [row["legacy_id"] for row in rows if row.get("legacy_id")]

    engine = get_engine()
    with engine.begin() as conn:
        # UPSERT 全部 legacy_id 行
        for row in rows:
            stmt = sqlite_insert(t.projects).values(id=generate_id(), **row)
            update_cols = {
                "name": stmt.excluded.name,
                "order_index": stmt.excluded.order_index,
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
                delete(t.projects).where(t.projects.c.legacy_id.notin_(legacy_ids))
            )
        else:
            # payload 空 → 清空整表
            conn.execute(delete(t.projects))


def load_projects_db() -> list[dict] | None:
    """从 DB 读回 projects list（DB 主模式下调用）。

    - DB 有行 → 返回反序列化 raw_json 后的 list（按 `order_index` 升序）。
    - DB 空 / 全部 raw_json 反序列化失败 → 返回 `None`（上层决定 fallback JSON）。
    """

    from sqlalchemy import select

    from app.data_import import tables as t
    from app.db.engine import get_engine

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(t.projects.c.raw_json, t.projects.c.order_index).order_by(
                t.projects.c.order_index.asc()
            )
        ).fetchall()

    if not rows:
        return None

    result: list[dict] = []
    for row in rows:
        raw = row.raw_json
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except (TypeError, ValueError) as exc:  # pragma: no cover — 极端场景
            _LOG.warning(
                "project_writer.load_projects_db: raw_json decode failed err=%s",
                exc,
            )
            continue
        if isinstance(entry, dict) and entry.get("id"):
            result.append(entry)

    return result if result else None


# ---------------------------------------------------------------------------
# JSON 异步回写（fallback）
# ---------------------------------------------------------------------------


_JSON_FALLBACK_LOCK = threading.Lock()
_JSON_FALLBACK_DIFF_KEYS: tuple[str, ...] = (
    "ts",
    "domain",
    "error",
    "fallback_reason",
)


def _shadow_diff_root() -> str:
    try:
        from app.shared.settings import get_settings

        base = get_settings().data_dir
    except Exception:  # pragma: no cover — settings 不可用时回退
        base = os.path.join(os.getcwd(), "data")
    return os.path.join(base, "shadow_diff")


def _record_json_fallback_failure(
    *,
    error: str,
    fallback_reason: str = "json_write_error",
) -> str | None:
    """把 JSON 回写失败落 `data/shadow_diff/project_json_fallback/<yyyymmdd>.jsonl`。

    失败仅 warning，绝不 raise（隔离契约）。
    """

    record = {
        "ts": _now_iso(),
        "domain": DOMAIN,
        "error": str(error),
        "fallback_reason": str(fallback_reason),
    }
    dir_path = os.path.join(_shadow_diff_root(), "project_json_fallback")
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
            "project_writer: json_fallback diff write failed err=%s", exc
        )
        return None


def _write_json_fallback_sync(projects: list[dict]) -> None:
    """同步写 JSON 文件（供异步 helper 内部调用）。

    - 复现 `main.save_projects` 落盘字节：
      `json.dump({"projects": projects}, f, ensure_ascii=False, indent=2)`。
    - 失败仅 warning + shadow diff，绝不 raise。
    """

    try:
        import main

        os.makedirs(main.DATA_DIR, exist_ok=True)
        with main.CANVAS_LOCK:
            with open(main.PROJECTS_PATH, "w", encoding="utf-8") as fh:
                json.dump(
                    {"projects": projects}, fh, ensure_ascii=False, indent=2
                )
    except Exception as exc:  # 隔离契约：写失败仅 warning，不 raise
        _LOG.warning(
            "project_writer: json_fallback write failed err=%s", exc
        )
        try:
            _record_json_fallback_failure(
                error=str(exc), fallback_reason="json_write_error"
            )
        except Exception:  # pragma: no cover — nested failure guard
            _LOG.warning("project_writer: diff writer also failed")


def _async_write_json_fallback(projects: list[dict]) -> None:
    """异步把 projects list 回写到 JSON 文件（供 DB 主写成功后触发）。

    - 优先 `asyncio.run_in_executor`；否则退化为 daemon thread。
    - 不阻塞主写路径；异常一律吞掉。
    """

    snapshot = list(projects) if projects else []

    def _target() -> None:
        try:
            _write_json_fallback_sync(snapshot)
        except Exception as exc:  # pragma: no cover — nested guard
            _LOG.warning(
                "project_writer: async json_fallback target raised err=%s", exc
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
        except Exception:  # pragma: no cover — 事件循环拒绝调度
            pass

    threading.Thread(target=_target, daemon=True).start()


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


__all__ = [
    "save_projects_db",
    "load_projects_db",
]
