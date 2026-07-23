"""`app.db.asset_library_writer` — 数据 PR-9 AssetLibrary DB 主写路径。

只有 `ASSET_LIBRARY_PRIMARY_WRITE=db` 时，`asset_library_store.save_asset_library`
才 import 本模块（`json` 路径**不 import**）。

**数据 PR-23**（Wave 3-N.5 主线 A · Batch 3 · M1 阶段 5 域反转最后一域）：
AssetLibrary 域默认反转 —— 未设 env / 空 env 时默认 DB 主写（GM-22 反转）；
回滚方式 = `export ASSET_LIBRARY_PRIMARY_WRITE=json` 立即生效（fail-fast
值域校验保留）。

关键契约（治理期）：

- **单文档 UPSERT**：AssetLibrary 的落盘 payload 是**单个 dict**
  （`{"active_library_id": ..., "libraries": [...], "updated_at": ...}`），
  与 canvas 单对象、projects 集合列表都不同。走"整个 payload 作为一条
  row 的 `raw_json` 存储"策略；`legacy_id = "__root__"` 固定值保证幂等
  UPSERT 单行（D-2=B 决策：`asset_categories` / `asset_items` 表 PR-9
  **不主写**，等文件对象专题 PR-3+ 承接 `file_ref` 时再展平）。
- **DB 主写失败必须上抛**（P0 硬约束 #4）：出错抛异常，不允许 fallback
  到 JSON 主写；仅 JSON 异步回写允许失败静默。
- **JSON 异步回写允许失败静默**：`_async_write_json_fallback` 内部异常仅
  warning + `data/shadow_diff/asset_library_json_fallback/*.jsonl`，不冒泡。
- **Provider 凭据零落 DB**（跨 domain 抗回归）：AssetLibrary 域本身**不涉及**
  Provider 凭据；`raw_json` 应保留原始 payload（含 `url` / `source_url` /
  `originalUrl` 等非敏感 URL 字段）；测试断言 `raw_json` 与 diff jsonl
  中不出现 `AKIA` / `Bearer` / `api_key` / `secret` 等 sentinel。

详见：

- [[40 实施计划/数据模型治理实施计划与PR清单]] PR-9
- [[60 讨论记录/2026-07-19 Wave 3-H 开工/2026-07-19 Wave 3-H 开工协调纲要]]
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import threading
from typing import Any, Mapping

_LOG = logging.getLogger(__name__)


DOMAIN = "asset_library"

# AssetLibrary 是"整个字典就是一个 payload"（不像 projects 是列表，也不像
# canvas 每个对象有独立 id），所以用固定 legacy_id 保证 UPSERT 落单行。
_ROOT_LEGACY_ID = "__root__"


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


def _derive_name(lib: Mapping[str, Any]) -> str | None:
    """从 payload 顶层派生 `name`（诊断字段；可为 None）。"""

    for key in ("name", "active_library_id"):
        value = lib.get(key)
        if value:
            return str(value)
    return None


def _derive_kind(lib: Mapping[str, Any]) -> str | None:
    """从 payload 顶层派生 `kind`（诊断字段；可为 None）。"""

    for key in ("kind", "type"):
        value = lib.get(key)
        if value:
            return str(value)
    return None


def _build_row(lib: Mapping[str, Any], imported_at: _dt.datetime) -> dict[str, Any]:
    """Build UPSERT row for the single asset library payload。

    - `legacy_id` = 固定 `"__root__"`（单文档单行契约）。
    - `raw_json` = 整个 payload（含 `active_library_id` / `libraries` /
      `categories` / `updated_at` 等）字节承载。
    """

    return {
        "legacy_id": _ROOT_LEGACY_ID,
        "name": _derive_name(lib),
        "kind": _derive_kind(lib),
        "raw_json": _serialize_raw_json(lib),
        "schema_version": "v1_legacy_json",
        "imported_at": imported_at,
        "created_at": imported_at,
        "updated_at": imported_at,
    }


# ---------------------------------------------------------------------------
# DB 主写
# ---------------------------------------------------------------------------


def save_asset_library_db(lib: dict) -> None:
    """DB 主写整个 AssetLibrary payload（单文档 UPSERT）。

    - `lib` 结构：`{active_library_id, libraries: [{id, name, categories: [...]}, ...]}`
      （`main.normalize_asset_library` 输出）。
    - 单个事务里 UPSERT 唯一 `legacy_id="__root__"` 行（`raw_json` 存
      整个 payload）；不需要 DELETE—单文档模型。
    - 任何 DB 错误 → 原样上抛（**不吞异常、不 fallback 到 JSON 主写**）。
    """

    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.shared.ids import generate_id

    if not isinstance(lib, dict):
        # 与其他 writer 一致：非 dict 传入不做修复，上抛让上层 legacy impl 处理
        raise TypeError(
            f"save_asset_library_db: expected dict payload, got {type(lib).__name__}"
        )

    imported_at = _now_utc()
    row = _build_row(lib, imported_at)

    engine = get_engine()
    with engine.begin() as conn:
        stmt = sqlite_insert(t.asset_libraries).values(id=generate_id(), **row)
        update_cols = {
            "name": stmt.excluded.name,
            "kind": stmt.excluded.kind,
            "raw_json": stmt.excluded.raw_json,
            "schema_version": stmt.excluded.schema_version,
            "updated_at": stmt.excluded.updated_at,
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["legacy_id"], set_=update_cols
        )
        conn.execute(stmt)


def load_asset_library_db() -> dict | None:
    """从 DB 读回 AssetLibrary payload（DB 主模式下调用）。

    - DB 有 `legacy_id="__root__"` 行 → 反序列化 `raw_json` 返回 dict。
    - DB 空 / raw_json 解析失败 → 返回 `None`（上层决定 fallback JSON）。
    """

    from sqlalchemy import select

    from app.data_import import tables as t
    from app.db.engine import get_engine

    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            select(t.asset_libraries.c.raw_json).where(
                t.asset_libraries.c.legacy_id == _ROOT_LEGACY_ID
            )
        ).fetchone()

    if not row or not row.raw_json:
        return None

    try:
        payload = json.loads(row.raw_json)
    except (TypeError, ValueError) as exc:  # pragma: no cover — 极端场景
        _LOG.warning(
            "asset_library_writer.load_asset_library_db: raw_json decode failed err=%s",
            exc,
        )
        return None

    if isinstance(payload, dict):
        return payload
    return None


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
    `data/shadow_diff/asset_library_json_fallback/<yyyymmdd>.jsonl`。

    失败仅 warning，绝不 raise（隔离契约）。稳定键位
    `(ts, domain, error, fallback_reason)`——**不含内容体**（跨 domain
    抗回归护栏，即使 AssetLibrary 域本身不涉及 provider 凭据）。
    """

    record = {
        "ts": _now_iso(),
        "domain": DOMAIN,
        "error": str(error),
        "fallback_reason": str(fallback_reason),
    }
    dir_path = os.path.join(_shadow_diff_root(), "asset_library_json_fallback")
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
            "asset_library_writer: json_fallback diff write failed err=%s", exc
        )
        return None


def _write_json_fallback_sync(lib: Mapping[str, Any]) -> None:
    """同步写 JSON 文件（供异步 helper 内部调用）。

    - 复现 `main.save_asset_library` 落盘字节：
      `normalize_asset_library` → `sort_asset_library_items` → 覆盖
      `updated_at = now_ms()` → `open(...).json.dump(indent=2)`。
    - 失败仅 warning + shadow diff，绝不 raise（隔离契约）。
    """

    try:
        import main

        # 复现老 save_asset_library 内部逻辑（不调 main.save_asset_library
        # 本身：wrapper `db` 模式下已直接走 DB 主写，同步调 legacy save
        # 会 (a) 双主写分叉 (b) 触发 broadcast_asset_library_updated 二次
        # WS 广播）。
        payload = main.normalize_asset_library(dict(lib))
        main.sort_asset_library_items(payload)
        payload["updated_at"] = main.now_ms()
        os.makedirs(main.DATA_DIR, exist_ok=True)
        with open(main.ASSET_LIBRARY_PATH, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    except Exception as exc:  # 隔离契约：写失败仅 warning，不 raise
        _LOG.warning(
            "asset_library_writer: json_fallback write failed err=%s", exc
        )
        try:
            _record_json_fallback_failure(
                error=str(exc), fallback_reason="json_write_error"
            )
        except Exception:  # pragma: no cover — nested failure guard
            _LOG.warning("asset_library_writer: diff writer also failed")


def _async_write_json_fallback(lib: Mapping[str, Any]) -> None:
    """异步把 AssetLibrary payload 回写到 JSON 文件（供 DB 主写成功后触发）。

    - 优先 `asyncio.run_in_executor`；否则退化为 daemon thread。
    - 不阻塞主写路径；异常一律吞掉。
    """

    snapshot = dict(lib) if isinstance(lib, dict) else {}

    def _target() -> None:
        try:
            _write_json_fallback_sync(snapshot)
        except Exception as exc:  # pragma: no cover — nested guard
            _LOG.warning(
                "asset_library_writer: async json_fallback target raised err=%s",
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
    "save_asset_library_db",
    "load_asset_library_db",
]
