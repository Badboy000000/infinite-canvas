"""`app.shadow_write.diff_writer` — Canvas shadow write 失败事件落盘。

- 路径：`data/shadow_diff/canvas_write/<yyyymmdd>.jsonl`
- 记录 schema（稳定键位）：

```json
{
  "ts": "2026-07-19T02:15:33.123456+00:00",
  "domain": "canvas",
  "legacy_id": "c1",
  "error": "OperationalError(...)",
  "request_id": "01J..."
}
```

失败隔离：任何写盘异常仅记 warning，绝不 raise。
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import threading
from typing import Any

_LOG = logging.getLogger(__name__)
_WRITE_LOCK = threading.Lock()

WRITE_FAILURE_KEYS: tuple[str, ...] = (
    "ts",
    "domain",
    "legacy_id",
    "error",
    "request_id",
)


def _shadow_diff_root() -> str:
    """Return `<DATA_DIR>/shadow_diff`；DATA_DIR 走 Settings 读时求值。"""

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


def build_write_failure(
    *,
    domain: str,
    legacy_id: str,
    error: str,
    request_id: str | None = None,
    ts: str | None = None,
) -> dict[str, Any]:
    """Build the stable-key failure record dict."""

    return {
        "ts": ts or _now_iso(),
        "domain": str(domain),
        "legacy_id": str(legacy_id),
        "error": str(error),
        "request_id": request_id,
    }


def write_write_failure(
    *,
    domain: str,
    legacy_id: str,
    error: str,
    request_id: str | None = None,
) -> str | None:
    """Append a failure line to `<DATA_DIR>/shadow_diff/<domain>_write/<yyyymmdd>.jsonl`.

    - `domain` = `canvas` → 目录 `canvas_write/`（与 shadow_read `canvas/` 隔离）。
    - 幂等 mkdir 父目录。
    - 失败仅 warning，绝不 raise。
    """

    record = build_write_failure(
        domain=domain,
        legacy_id=legacy_id,
        error=error,
        request_id=request_id,
    )
    subdir = f"{domain}_write"
    root = _shadow_diff_root()
    dir_path = os.path.join(root, subdir)
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
            "shadow_write.diff_writer: write failed domain=%s path=%s err=%s",
            domain,
            file_path,
            exc,
        )
        return None


__all__ = [
    "WRITE_FAILURE_KEYS",
    "build_write_failure",
    "write_write_failure",
]
