"""`app.shadow_read.diff_writer` — 差异 JSONL 落盘 helper。

日志按 `data/shadow_diff/<domain>/<yyyymmdd>.jsonl` 结构存放；每行一条
`json.dumps(record)`。稳定键位（下游 grep / 对账工具依赖）：

```json
{
  "ts": "2026-07-19T02:15:33.123456+00:00",
  "domain": "provider_config",
  "request_id": "01J...",
  "missing_in_db":   ["<legacy_id_1>", ...],
  "missing_in_json": ["<legacy_id_2>", ...],
  "field_diffs":     [{"legacy_id": "...", "field": "name",
                       "json_value": "old", "db_value": "new"}, ...]
}
```

失败隔离：任何写盘异常仅 warning，绝不 raise。
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import threading
from typing import Any, Iterable


_LOG = logging.getLogger(__name__)
_WRITE_LOCK = threading.Lock()

# 稳定键位（`test_diff_jsonl_schema.py` 抗回归）。修改前必须同步更新数据
# PR-4 / PR-5+ 契约、下游 grep 与文档。
DIFF_RECORD_KEYS: tuple[str, ...] = (
    "ts",
    "domain",
    "request_id",
    "missing_in_db",
    "missing_in_json",
    "field_diffs",
)


def _shadow_diff_root() -> str:
    """Return `<DATA_DIR>/shadow_diff`；DATA_DIR 走 Settings 读时求值。"""

    try:
        from app.shared.settings import get_settings

        settings = get_settings()
        base = settings.data_dir
    except Exception:  # pragma: no cover — settings 不可用时回退
        base = os.path.join(os.getcwd(), "data")
    return os.path.join(base, "shadow_diff")


def _today_utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d")


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def build_diff_record(
    *,
    domain: str,
    missing_in_db: Iterable[str],
    missing_in_json: Iterable[str],
    field_diffs: Iterable[dict[str, Any]],
    request_id: str | None = None,
    ts: str | None = None,
) -> dict[str, Any]:
    """构造稳定键位的 diff 记录。字段顺序即 `DIFF_RECORD_KEYS`。"""

    return {
        "ts": ts or _now_iso(),
        "domain": str(domain),
        "request_id": request_id,
        "missing_in_db": sorted(str(x) for x in missing_in_db),
        "missing_in_json": sorted(str(x) for x in missing_in_json),
        "field_diffs": list(field_diffs),
    }


def write_diff_record(record: dict[str, Any]) -> str | None:
    """把一条 diff 记录追加到 `data/shadow_diff/<domain>/<yyyymmdd>.jsonl`。

    - 幂等 mkdir 父目录。
    - 追加写；`os.O_APPEND` 语义在多进程下也安全（无跨行交错要求）。
    - 失败仅 warning，绝不 raise。
    - 返回写入的文件路径；失败返回 `None`。
    """

    domain = str(record.get("domain") or "unknown")
    root = _shadow_diff_root()
    dir_path = os.path.join(root, domain)
    file_path = os.path.join(dir_path, f"{_today_utc()}.jsonl")
    line = json.dumps(record, ensure_ascii=False, sort_keys=False) + "\n"
    try:
        os.makedirs(dir_path, exist_ok=True)
        with _WRITE_LOCK:
            with open(file_path, "a", encoding="utf-8") as fh:
                fh.write(line)
        return file_path
    except Exception as exc:  # pragma: no cover — 失败隔离契约
        _LOG.warning(
            "shadow_diff write failed domain=%s path=%s err=%s",
            domain,
            file_path,
            exc,
        )
        return None


__all__ = [
    "DIFF_RECORD_KEYS",
    "build_diff_record",
    "write_diff_record",
]
