"""`app.db.workflow_writer` — 数据 PR-8 WorkflowDefinition DB 主写路径。

只有 `WORKFLOW_DEFINITION_PRIMARY_WRITE=db` 时，`workflow_store.save_runninghub_workflow_store`
才 import 本模块（默认 `json` 路径**不 import**）。

关键契约（治理期）：

- **P0 密钥剪枝**：`workflow_definitions.raw_json` 严禁包含 provider
  `api_key` / `access_token` / `secret` / `authorization` / `password` /
  `client_secret` / ... 相关键；写库前深度剪枝（复用 provider_config_store
  `_is_sensitive_field` 语义）。shadow diff 落盘前同样剪枝（P0 硬约束 #5）。
- **集合级写事务**：整个 `runninghub_workflow_store` payload（`Dict[workflowId, cfg]`）
  在单事务里先 UPSERT 全部 `legacy_id="rh:<workflow_id>"` 行，再 DELETE
  `legacy_id NOT IN payload`。
- **DB 主写失败必须上抛**（P0 硬约束 #4）。
- **JSON 异步回写允许失败静默** + shadow diff 追加落盘。
- **`prune_runninghub_workflow_store_for_provider` 语义等价**：因 store facade
  夹在 `main.py:prune_runninghub_workflow_store_for_provider` 与 legacy JSON
  save 之间，`WORKFLOW_DEFINITION_PRIMARY_WRITE=db` 下 prune 语义自动等价
  （facade 分派会调本模块）。

详见：

- [[40 实施计划/数据模型治理实施计划与PR清单]] PR-8
- [[60 讨论记录/2026-07-19 Wave 3-G-数据 PR-8 开工]] 协调纲要
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import threading
from typing import Any, Iterable, Mapping

_LOG = logging.getLogger(__name__)


DOMAIN = "workflow_definition"


# ---------------------------------------------------------------------------
# P0 密钥剪枝（与 provider_config_store `_is_sensitive_field` 语义一致）
# ---------------------------------------------------------------------------


# 完整名称匹配（normalize 后小写去 `[^a-z0-9]`）
_SENSITIVE_FIELD_NAMES: frozenset[str] = frozenset({
    "accesstoken", "apikey", "authorization", "clientsecret", "credential",
    "key", "password", "privatekey", "secret", "secretaccesskey",
    "sessionsecret", "token", "walletkey",
    # workflow 额外常见键
    "envfile", "dotenv",
})

# 前缀 / 后缀匹配
_SENSITIVE_AFFIXES: tuple[str, ...] = (
    "apikey", "accesstoken", "authtoken", "clientsecret",
    "credential", "password", "privatekey", "secretaccesskey",
    "sessionsecret", "walletkey",
)


def _is_sensitive_field(name: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(name or "").lower())
    if not normalized:
        return False
    if normalized in _SENSITIVE_FIELD_NAMES:
        return True
    return any(
        normalized.startswith(prefix) or normalized.endswith(prefix)
        for prefix in _SENSITIVE_AFFIXES
    )


def _prune_secrets(value: Any) -> Any:
    """深度剪除敏感键。dict / list 递归；scalar 原样返回。

    对 dict：过滤 `_is_sensitive_field(key) is True` 的键；对剩余 value 递归。
    对 list：逐项递归。字符串不做 URL 解析（workflow 场景下 URL query 密钥
    风险低，且避免与 provider_config_store 相互耦合）。
    """

    if isinstance(value, dict):
        return {
            key: _prune_secrets(item)
            for key, item in value.items()
            if not _is_sensitive_field(key)
        }
    if isinstance(value, list):
        return [_prune_secrets(item) for item in value]
    return value


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


def _iter_workflow_entries(store: Any) -> list[tuple[str, dict[str, Any]]]:
    """`runninghub_workflow_store` 顶层结构：`Dict[workflowId, cfg]`（其中 cfg 是 dict）。

    返回 `[(workflow_id, cfg), ...]`，过滤空 key / 非 dict cfg。
    """

    if not isinstance(store, dict):
        return []
    entries: list[tuple[str, dict[str, Any]]] = []
    for workflow_id, cfg in store.items():
        wid = str(workflow_id or "").strip()
        if not wid:
            continue
        if not isinstance(cfg, dict):
            continue
        entries.append((wid, cfg))
    return entries


def _build_row(
    workflow_id: str, cfg: Mapping[str, Any], imported_at: _dt.datetime
) -> dict[str, Any]:
    """Build UPSERT row for one runninghub workflow entry."""

    # P0 密钥剪枝：raw_json 深度剪除任何 sensitive 字段
    safe_cfg = _prune_secrets(dict(cfg))
    legacy_id = f"rh:{workflow_id}"
    return {
        "legacy_id": legacy_id,
        "name": (cfg.get("title") or cfg.get("name") or workflow_id) or None,
        "provider_id": "runninghub",
        "kind": "workflow",
        "legacy_path": None,
        "raw_json": _serialize_raw_json(safe_cfg),
        "schema_version": "v1_legacy_json",
        "imported_at": imported_at,
        "created_at": imported_at,
        "updated_at": imported_at,
    }


# ---------------------------------------------------------------------------
# DB 主写
# ---------------------------------------------------------------------------


def save_runninghub_workflow_store_db(store: dict) -> None:
    """DB 主写整个 runninghub workflow store（集合级写事务）。

    - store 结构：`Dict[workflowId, cfg]`。
    - 单事务：UPSERT 全部 `legacy_id="rh:<workflow_id>"` 行 → DELETE
      `WHERE provider_id = 'runninghub' AND legacy_id NOT IN payload`。
    - **P0 密钥剪枝**：`raw_json` 深度剪除任何 `_is_sensitive_field` 匹配的
      字段（`api_key` / `access_token` / `secret` / `authorization` / ...）。
    - 任何 DB 错误 → 原样上抛（**不 fallback**）。

    注意：本函数只维护 `provider_id='runninghub'` 的行；其他 provider（如
    builtin `file:*`）不受影响。
    """

    from sqlalchemy import and_, delete
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.shared.ids import generate_id

    entries = _iter_workflow_entries(store)
    imported_at = _now_utc()
    rows = [_build_row(wid, cfg, imported_at) for wid, cfg in entries]
    legacy_ids: list[str] = [row["legacy_id"] for row in rows]

    engine = get_engine()
    with engine.begin() as conn:
        for row in rows:
            stmt = sqlite_insert(t.workflow_definitions).values(
                id=generate_id(), **row
            )
            update_cols = {
                "name": stmt.excluded.name,
                "provider_id": stmt.excluded.provider_id,
                "kind": stmt.excluded.kind,
                "legacy_path": stmt.excluded.legacy_path,
                "raw_json": stmt.excluded.raw_json,
                "schema_version": stmt.excluded.schema_version,
                "updated_at": stmt.excluded.updated_at,
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=["legacy_id"], set_=update_cols
            )
            conn.execute(stmt)

        # DELETE `provider_id='runninghub' AND legacy_id NOT IN payload`
        # 只清 runninghub 域，避免误伤 builtin `file:*` 行。
        rh_filter = t.workflow_definitions.c.provider_id == "runninghub"
        if legacy_ids:
            conn.execute(
                delete(t.workflow_definitions).where(
                    and_(
                        rh_filter,
                        t.workflow_definitions.c.legacy_id.notin_(legacy_ids),
                    )
                )
            )
        else:
            conn.execute(delete(t.workflow_definitions).where(rh_filter))


def load_runninghub_workflow_store_db() -> dict | None:
    """从 DB 读回 runninghub workflow store（DB 主模式下调用）。

    - `provider_id='runninghub'` 且 `raw_json` 非空 → 组装
      `Dict[workflow_id, cfg]`；`workflow_id` 从 `legacy_id` 去 `rh:` 前缀。
    - 无匹配行 → `None`（上层 fallback JSON）。
    """

    from sqlalchemy import select

    from app.data_import import tables as t
    from app.db.engine import get_engine

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                t.workflow_definitions.c.legacy_id,
                t.workflow_definitions.c.raw_json,
            ).where(t.workflow_definitions.c.provider_id == "runninghub")
        ).fetchall()

    if not rows:
        return None

    result: dict[str, dict] = {}
    for row in rows:
        legacy_id = row.legacy_id or ""
        if not legacy_id.startswith("rh:"):
            continue
        wid = legacy_id[len("rh:"):]
        raw = row.raw_json
        if not raw:
            continue
        try:
            cfg = json.loads(raw)
        except (TypeError, ValueError) as exc:  # pragma: no cover
            _LOG.warning(
                "workflow_writer.load: raw_json decode failed id=%s err=%s",
                legacy_id,
                exc,
            )
            continue
        if isinstance(cfg, dict):
            result[wid] = cfg

    return result if result else None


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
    `data/shadow_diff/workflow_definition_json_fallback/<yyyymmdd>.jsonl`。

    **P0**：diff 落盘前不写 workflow 内容体（只记 error / reason），杜绝密钥
    通过 diff 泄露。
    """

    record = {
        "ts": _now_iso(),
        "domain": DOMAIN,
        "error": str(error),
        "fallback_reason": str(fallback_reason),
    }
    dir_path = os.path.join(
        _shadow_diff_root(), "workflow_definition_json_fallback"
    )
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
            "workflow_writer: json_fallback diff write failed err=%s", exc
        )
        return None


def _write_json_fallback_sync(store: Mapping[str, Any]) -> None:
    """同步写 JSON 文件。复现 `main.save_runninghub_workflow_store` 落盘字节。

    注意 JSON 文件仍走 legacy 路径（历史 workflow JSON 允许含密钥字段），
    仅 **DB 层 & shadow diff** 做密钥剪枝。这是治理期"字节等价 JSON 主写"
    的必要妥协：切换到 db 主写只是让 DB 侧零密钥，JSON 回退方向不动。
    """

    try:
        import main

        os.makedirs(main.DATA_DIR, exist_ok=True)
        with open(main.RUNNINGHUB_WORKFLOW_STORE_FILE, "w", encoding="utf-8") as fh:
            json.dump(dict(store), fh, ensure_ascii=False, indent=2)
    except Exception as exc:
        _LOG.warning(
            "workflow_writer: json_fallback write failed err=%s", exc
        )
        try:
            _record_json_fallback_failure(
                error=str(exc), fallback_reason="json_write_error"
            )
        except Exception:  # pragma: no cover
            _LOG.warning("workflow_writer: diff writer also failed")


def _async_write_json_fallback(store: Mapping[str, Any]) -> None:
    """异步把 store 回写到 JSON。"""

    snapshot = dict(store) if store else {}

    def _target() -> None:
        try:
            _write_json_fallback_sync(snapshot)
        except Exception as exc:  # pragma: no cover
            _LOG.warning(
                "workflow_writer: async json_fallback target raised err=%s",
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
    "save_runninghub_workflow_store_db",
    "load_runninghub_workflow_store_db",
    "_is_sensitive_field",
    "_prune_secrets",
]
