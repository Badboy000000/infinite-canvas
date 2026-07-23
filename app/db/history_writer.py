"""`app.db.history_writer` — 数据 PR-12 GenerationHistory DB 主写路径。

**跨模块引用（顶注硬约束 · GM-16 加强版）**：本 writer 是 `app/db/` 层的
`generation_history` SQL 主写（数据 PR-12 · Wave 3-N.6 Batch 2 主线 B）；
与 `app/task/history/writer.py::HistoryWriter`（task 域 `TASK_HISTORY_ENABLE`
flag · 独立子系统 · 消费 tasks / node_runs 五张表）**语义分离 · 不冲突 · 不重复**。
两者仅共享历史领域词汇；本 writer 承接 legacy `main.save_to_history` /
`main.get_history_api` 的字节承载 · task 域 writer 承接 task 五件套的
snapshot 关联。

只有 `HISTORY_PRIMARY_WRITE=db` 时，`history_store.save_to_history` 才
import 本模块（`json` 路径**不 import**）。

**数据 PR-12**（Wave 3-N.6 Batch 2 主线 B · GM-22 pattern 第 7 次复用）：
本 PR **只加机制不切默认** · 默认 `"json"` 完全等价 legacy · GM-22 反转独立 PR。

关键契约（治理期）：

- **N-record UPSERT + DELETE oldest**：与 AssetLibrary 单文档不同；每 record
  一行（`legacy_id` UNIQUE 幂等键），单事务里
  `INSERT ... ON CONFLICT(legacy_id) DO UPDATE` + 尾端 DELETE 保持 ≤5000
  条（与 legacy `main.save_to_history` `history[:5000]` 上限对齐 · GM-06
  兼容契约）。
- **legacy_id 兜底合成**（GM-14 圆桌授权 · 参照 `app/task/history/writer.py:82
  _canonical_record_key` pattern 但输入字段独立选择）：
  * 优先级 1：`record["id"]` 显式提供
  * 优先级 2：`record["legacy_id"]` 显式提供
  * 优先级 3：`_synthesize_history_legacy_id(record)` 合成（`task_id +
    request_id + timestamp + prompt_summary[:80]` SHA1 头 16 位）
  * 极端 fallback：`timestamp_ns` 保底（合成键失败不能拒写；GM-06 语义兼容）
- **DB 主写失败必须上抛**（P0 硬约束 #4）：出错抛异常，不允许 fallback
  到 JSON 主写；仅 JSON 异步回写允许失败静默。
- **JSON 异步回写允许失败静默**：`_async_write_json_fallback` 内部异常仅
  warning + `data/shadow_diff/history_json_fallback/*.jsonl`，不冒泡。
- **P0 密钥深度剪枝**（跨 domain 抗回归 · 参照 provider_config_store
  `_safe_provider_records` pattern · 但 history 是通用 domain · 独立 helper
  `_safe_history_record`）：`api_key` / `secret` / `token` / `password` /
  `credential` / `raw_response` / `Bearer` / `Authorization` 等黑名单字段
  任意深度嵌套均剪枝后再入 raw_json；shadow_diff jsonl 稳定键位
  `(ts, domain, error, fallback_reason)` 不含内容体。

详见：
- [[40 实施计划/数据模型治理实施计划与PR清单]] PR-12
- [[70 开发过程跟踪/治理机制/subagent 任务书回写义务清单#GM-14]] 圆桌授权
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os
import threading
import time
from typing import Any, Mapping

_LOG = logging.getLogger(__name__)


DOMAIN = "generation_history"

# GM-06 兼容契约：legacy `main.save_to_history` 上限 `history[:5000]`。
HISTORY_MAX_RECORDS = 5000

# P0 硬约束 #5 · 密钥深度剪枝黑名单（大小写不敏感命中）。参照
# `app/stores/provider_config_store._safe_provider_records` · 但 history 是通用
# domain（不像 provider_configs 是白名单模型），这里用黑名单更保守。
_SECRET_KEY_BLACKLIST: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "secret",
        "secret_key",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "credential",
        "credentials",
        "authorization",
        "bearer",
        "raw_response",
    }
)
_SECRET_KEY_REDACTION = "[REDACTED_BY_HISTORY_WRITER]"


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


def _safe_history_record(record: Any) -> Any:
    """深度剪枝黑名单字段（任意层级嵌套）。

    - dict → 逐 key 判黑名单，命中即 `[REDACTED_BY_HISTORY_WRITER]`；否则递归。
    - list / tuple → 逐元素递归（返回 list）。
    - 其余 scalar → 原样返回。

    P0 硬约束 #5 保护面：`api_key` / `secret` / `token` / `password` /
    `credential` / `Bearer` / `Authorization` / `raw_response` 等黑名单
    命中即剪枝。业务 URL 字段（`url` / `source_url` / `legacy_url`）不在黑名单，
    保留用于追溯（与 AssetLibrary T9 pattern 对齐）。
    """

    if isinstance(record, Mapping):
        out: dict[str, Any] = {}
        for k, v in record.items():
            key_lower = str(k).strip().lower()
            if key_lower in _SECRET_KEY_BLACKLIST:
                out[k] = _SECRET_KEY_REDACTION
            else:
                out[k] = _safe_history_record(v)
        return out
    if isinstance(record, (list, tuple)):
        return [_safe_history_record(v) for v in record]
    return record


def _synthesize_history_legacy_id(record: Mapping[str, Any]) -> str:
    """兜底合成稳定 legacy_id（GM-14 圆桌授权 pattern）。

    输入字段（缺失 → 空串占位以保持输入稳定）：
    - `task_id` / `request_id` / `timestamp` / `prompt_summary[:80]`

    输出：SHA1(ident).hexdigest()[:16]。同 record 二次调用必须完全一致。
    极端 case（所有字段都缺失且 SHA1 计算异常 · pragma no cover）走
    `timestamp_ns` 保底。
    """

    task_id = record.get("task_id") if isinstance(record, Mapping) else None
    request_id = record.get("request_id") if isinstance(record, Mapping) else None
    ts = record.get("timestamp") if isinstance(record, Mapping) else None
    prompt = record.get("prompt_summary") if isinstance(record, Mapping) else None
    if not isinstance(prompt, str):
        # 允许 record 顶层放 `prompt` 字段（legacy 常见）作 fallback。
        prompt = (
            record.get("prompt") if isinstance(record, Mapping) else None
        )
    prompt_head = str(prompt or "")[:80]

    ident = "|".join(
        [
            str(task_id or ""),
            str(request_id or ""),
            str(ts or ""),
            prompt_head,
        ]
    )
    try:
        return hashlib.sha1(ident.encode("utf-8")).hexdigest()[:16]
    except Exception:  # pragma: no cover — 极端场景保底
        return f"ts_{time.time_ns()}"


def _derive_history_legacy_id(record: Mapping[str, Any]) -> str:
    """优先级：`record["id"]` > `record["legacy_id"]` > 合成兜底。"""

    if not isinstance(record, Mapping):
        return _synthesize_history_legacy_id({})
    for key in ("id", "legacy_id"):
        raw = record.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    return _synthesize_history_legacy_id(record)


def _derive_created_at(record: Mapping[str, Any]) -> _dt.datetime:
    """从 record 抽 `timestamp`（epoch seconds float）→ UTC datetime。

    legacy `save_to_history` 会给 record 加 `timestamp = time.time()`，
    所以大部分 record 都有；缺失时用当前 UTC 补齐。
    """

    if isinstance(record, Mapping):
        ts = record.get("timestamp")
        if isinstance(ts, (int, float)) and ts > 0:
            try:
                return _dt.datetime.fromtimestamp(float(ts), tz=_dt.timezone.utc)
            except (OverflowError, OSError, ValueError):  # pragma: no cover
                pass
    return _now_utc()


def _pick_str(record: Mapping[str, Any], *keys: str) -> str | None:
    """从 record 依序抽字符串字段（scalar 才收；dict/list 一律跳过）。

    这条约束防止 `_pick_str(record, "provider")` 类调用把整个 `provider` 嵌套
    dict `str()` 化后落入非 raw_json 列 —— 由于诊断列（provider_id / task_id
    等）不走 `_safe_history_record` 密钥剪枝，非 scalar 值必须严格拒绝，
    否则会导致 P0 密钥泄漏（T379 抗回归）。
    """

    for key in keys:
        value = record.get(key)
        if value is None:
            continue
        if isinstance(value, (dict, list, tuple, set)):
            # 非 scalar 直接跳过（诊断列只接受 scalar；raw_json 承载嵌套）
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _serialize_legacy_urls(record: Mapping[str, Any]) -> str | None:
    """legacy 常见的 `images: [url, ...]` / `urls: [url, ...]` 序列化。

    - 首选 `images`（legacy `get_history_api` 消费该字段）
    - 次选 `urls` / `output_urls`
    - 均缺失 → None
    """

    for key in ("images", "urls", "output_urls"):
        value = record.get(key)
        if isinstance(value, list) and value:
            try:
                return json.dumps(value, ensure_ascii=False)
            except (TypeError, ValueError):
                return None
    return None


def _build_row(
    record: Mapping[str, Any], legacy_id: str, imported_at: _dt.datetime
) -> dict[str, Any]:
    """Build UPSERT row（本 PR 每 record 一行；raw_json 承载完整 record）。"""

    safe_record = _safe_history_record(record)
    created_at = _derive_created_at(record)
    return {
        "legacy_id": legacy_id,
        "user_key": _pick_str(record, "user_key", "user_id"),
        "canvas_id": _pick_str(record, "canvas_id", "canvasId"),
        "node_id": _pick_str(record, "node_id", "nodeId"),
        "task_id": _pick_str(record, "task_id", "taskId"),
        "output_ref": _pick_str(record, "output_ref", "outputRef"),
        "legacy_urls": _serialize_legacy_urls(record) if isinstance(record, Mapping) else None,
        "prompt_summary": _pick_str(record, "prompt_summary", "prompt"),
        "provider_id": _pick_str(record, "provider_id", "providerId", "provider"),
        "model": _pick_str(record, "model"),
        "created_at": created_at,
        "raw_json": _serialize_raw_json(safe_record),
        "schema_version": "v1_legacy_json",
    }


# ---------------------------------------------------------------------------
# DB 主写
# ---------------------------------------------------------------------------


def save_history_db(record: dict) -> None:
    """DB 主写单条 GenerationHistory record（N-record UPSERT + trim oldest）。

    - `record` 结构：legacy `save_to_history` 消费的 dict（含 `timestamp` /
      `type` / `images` / `prompt` / `task_id` / ...）。
    - legacy_id 派生：`record["id"]` > `record["legacy_id"]` > 合成兜底
      （GM-14 圆桌授权 pattern）。
    - 单个事务：UPSERT 单行（ON CONFLICT legacy_id DO UPDATE）+
      DELETE 尾端 `count - HISTORY_MAX_RECORDS` 条最旧（`created_at ASC`）。
    - **P0 密钥剪枝**：`_safe_history_record` 深度剪枝黑名单后再入 raw_json。
    - 任何 DB 错误 → 原样上抛（**不吞异常、不 fallback 到 JSON 主写**）。
    """

    from sqlalchemy import delete, func, select
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.shared.ids import generate_id

    if not isinstance(record, dict):
        raise TypeError(
            f"save_history_db: expected dict record, got {type(record).__name__}"
        )

    imported_at = _now_utc()
    legacy_id = _derive_history_legacy_id(record)
    row = _build_row(record, legacy_id, imported_at)

    engine = get_engine()
    with engine.begin() as conn:
        stmt = sqlite_insert(t.generation_history).values(
            id=generate_id(), **row
        )
        update_cols = {
            "user_key": stmt.excluded.user_key,
            "canvas_id": stmt.excluded.canvas_id,
            "node_id": stmt.excluded.node_id,
            "task_id": stmt.excluded.task_id,
            "output_ref": stmt.excluded.output_ref,
            "legacy_urls": stmt.excluded.legacy_urls,
            "prompt_summary": stmt.excluded.prompt_summary,
            "provider_id": stmt.excluded.provider_id,
            "model": stmt.excluded.model,
            "created_at": stmt.excluded.created_at,
            "raw_json": stmt.excluded.raw_json,
            "schema_version": stmt.excluded.schema_version,
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["legacy_id"], set_=update_cols
        )
        conn.execute(stmt)

        # 5000 上限对齐：DELETE oldest until count == HISTORY_MAX_RECORDS。
        current_count = conn.execute(
            select(func.count()).select_from(t.generation_history)
        ).scalar_one()
        overflow = int(current_count) - HISTORY_MAX_RECORDS
        if overflow > 0:
            oldest_ids_stmt = (
                select(t.generation_history.c.id)
                .order_by(t.generation_history.c.created_at.asc())
                .limit(overflow)
            )
            oldest_ids = [
                row_.id for row_ in conn.execute(oldest_ids_stmt).fetchall()
            ]
            if oldest_ids:
                conn.execute(
                    delete(t.generation_history).where(
                        t.generation_history.c.id.in_(oldest_ids)
                    )
                )


def load_history_db(*, limit: int = HISTORY_MAX_RECORDS) -> list[dict] | None:
    """从 DB 读回 GenerationHistory records（DB 主模式下调用）。

    - `ORDER BY created_at DESC LIMIT` · 与 legacy `get_history_api` 排序契约
      一致（`sort_key(item) = item["timestamp"]` reverse=True）。
    - DB 空 → 返回 `None`（上层决定 fallback JSON · 参照 canvas_store.load_canvas
      pattern）。
    - raw_json 解析失败的行会被跳过（**不**中断整批）；上层若拿到部分数据
      也可用（legacy 语义容忍）。
    """

    from sqlalchemy import select

    from app.data_import import tables as t
    from app.db.engine import get_engine

    if limit <= 0:
        limit = HISTORY_MAX_RECORDS

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(t.generation_history.c.raw_json)
            .order_by(t.generation_history.c.created_at.desc())
            .limit(int(limit))
        ).fetchall()

    if not rows:
        return None

    records: list[dict] = []
    for row in rows:
        raw_json = row.raw_json
        if not raw_json:
            continue
        try:
            payload = json.loads(raw_json)
        except (TypeError, ValueError) as exc:  # pragma: no cover — 极端场景
            _LOG.warning(
                "history_writer.load_history_db: raw_json decode failed err=%s",
                exc,
            )
            continue
        if isinstance(payload, dict):
            records.append(payload)

    return records if records else None


def delete_history_db(record_id: str) -> bool:
    """按 `legacy_id` 或 `id`（UUID 字符串）删除单条 record。

    返回是否命中一行；上层 `/api/history/delete` 路由承接。

    实现细节：`id` 是 `Uuid` 类型，SQLAlchemy 会对入参做 UUID 转换 —
    对 legacy_id（可能是 SHA1 头 16 位 / 任意字符串）做直接匹配；只有当
    `record_id` 恰能解析为 UUID 时才把 id 分支纳入条件。
    """

    import uuid as _uuid

    from sqlalchemy import delete

    from app.data_import import tables as t
    from app.db.engine import get_engine

    if record_id is None:
        return False
    key = str(record_id).strip()
    if not key:
        return False

    parsed_uuid: _uuid.UUID | None = None
    try:
        parsed_uuid = _uuid.UUID(key)
    except (ValueError, AttributeError, TypeError):
        parsed_uuid = None

    engine = get_engine()
    with engine.begin() as conn:
        # 先按 legacy_id 匹配（覆盖 SHA1 兜底与显式提供两种）。
        result_legacy = conn.execute(
            delete(t.generation_history).where(
                t.generation_history.c.legacy_id == key
            )
        )
        hits_legacy = int(getattr(result_legacy, "rowcount", 0) or 0)
        hits_uuid = 0
        if parsed_uuid is not None:
            result_uuid = conn.execute(
                delete(t.generation_history).where(
                    t.generation_history.c.id == parsed_uuid
                )
            )
            hits_uuid = int(getattr(result_uuid, "rowcount", 0) or 0)
    return (hits_legacy + hits_uuid) > 0


# ---------------------------------------------------------------------------
# JSON 异步回写（fallback）
# ---------------------------------------------------------------------------


_JSON_FALLBACK_LOCK = threading.Lock()


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
    """把 JSON 回写失败落
    `data/shadow_diff/history_json_fallback/<yyyymmdd>.jsonl`。

    失败仅 warning，绝不 raise（隔离契约）。稳定键位
    `(ts, domain, error, fallback_reason)`——**不含内容体**（P0 硬约束 #5
    跨 domain 抗回归护栏）。
    """

    record = {
        "ts": _now_iso(),
        "domain": DOMAIN,
        "error": str(error),
        "fallback_reason": str(fallback_reason),
    }
    dir_path = os.path.join(_shadow_diff_root(), "history_json_fallback")
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
            "history_writer: json_fallback diff write failed err=%s", exc
        )
        return None


def _write_json_fallback_sync(record: Mapping[str, Any]) -> None:
    """同步复现 legacy `main.save_to_history` 的落盘字节（供异步 helper 内部调用）。

    - 复现：加载 `HISTORY_FILE` → `history.insert(0, record)` → 截取
      `history[:HISTORY_MAX_RECORDS]` → 覆盖写回（indent=4 · ensure_ascii=False）。
    - 与 legacy 差异：**不**修改 `record["timestamp"]`（legacy 是先写入 record 里
      再落盘 · 本回写路径 record 早已经过 legacy save 加过 timestamp · 若外部
      直接调 db-mode 也允许 record 无 timestamp · legacy save 会加）。
    - 失败仅 warning + shadow diff，绝不 raise（隔离契约）。
    """

    try:
        import main

        history: list[dict] = []
        if os.path.exists(main.HISTORY_FILE):
            try:
                with open(main.HISTORY_FILE, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                    if isinstance(loaded, list):
                        history = loaded
            except Exception:  # legacy `except: pass` 兼容
                history = []
        snapshot = dict(record) if isinstance(record, Mapping) else {}
        if "timestamp" not in snapshot:
            snapshot["timestamp"] = time.time()
        history.insert(0, snapshot)
        os.makedirs(os.path.dirname(main.HISTORY_FILE) or ".", exist_ok=True)
        with open(main.HISTORY_FILE, "w", encoding="utf-8") as fh:
            json.dump(history[:HISTORY_MAX_RECORDS], fh, ensure_ascii=False, indent=4)
    except Exception as exc:  # 隔离契约：写失败仅 warning，不 raise
        _LOG.warning("history_writer: json_fallback write failed err=%s", exc)
        try:
            _record_json_fallback_failure(
                error=str(exc), fallback_reason="json_write_error"
            )
        except Exception:  # pragma: no cover — nested failure guard
            _LOG.warning("history_writer: diff writer also failed")


def _async_write_json_fallback(record: Mapping[str, Any]) -> None:
    """异步把 record 回写到 `HISTORY_FILE`（DB 主写成功后触发）。

    - 优先 `asyncio.run_in_executor`；否则退化为 daemon thread。
    - 不阻塞主写路径；异常一律吞掉。
    """

    snapshot = dict(record) if isinstance(record, Mapping) else {}

    def _target() -> None:
        try:
            _write_json_fallback_sync(snapshot)
        except Exception as exc:  # pragma: no cover — nested guard
            _LOG.warning(
                "history_writer: async json_fallback target raised err=%s",
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
        except Exception:  # pragma: no cover — 事件循环拒绝调度
            pass

    threading.Thread(target=_target, daemon=True).start()


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


__all__ = [
    "save_history_db",
    "load_history_db",
    "delete_history_db",
    "HISTORY_MAX_RECORDS",
]
