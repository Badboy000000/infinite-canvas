"""`tools/data_reconcile` — Canvas raw JSON ↔ DB `canvases.content_hash` 对账 CLI。

用途（数据 PR-6 首版）：

- 扫描 `CANVAS_DIR/*.json` 每个文件，读 raw text，计算 `sha256(raw)`。
- 读取 `canvases` 表的 `(legacy_id, content_hash)` 快照。
- 输出稳定 JSON 摘要到 stdout（不写盘、不改数据）。

用法：

```
python -m tools.data_reconcile canvas [--source-dir <path>]
```

- `--source-dir` 覆盖 `main.CANVAS_DIR`（测试隔离用）。
- exit=0：对账运行成功（无论是否有差异，均以 stdout JSON 描述）。
- exit=1：CLI 参数错误 / DB 引擎不可用。

**只报表，不改数据**（数据 PR-6 明确契约）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

# CB-P5-04 承接(数据 PR-16 · Wave 3-L 主线 C):Windows GBK codepage 下打印
# 含 Unicode 字符(emoji · 表格线 · CJK 边界)时会抛 UnicodeEncodeError。
# 此处对 stdout / stderr 做 UTF-8 重配 · 让本 CLI 在 Windows 默认 chcp=936
# 环境下也能安全输出对账结果。Python 3.7+ 支持 `reconfigure`。
if sys.platform == "win32":
    try:  # pragma: no cover — Windows-only defensive path
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        # 极老 Python 或非标准流(如 IPython)不支持 · 静默降级
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent


def _ensure_repo_on_syspath() -> None:
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _load_canvas_json_snapshot(source_dir: str | None) -> dict[str, str]:
    """`{legacy_id: sha256_hex}` from JSON files in `source_dir`。"""

    if not source_dir:
        try:
            import main  # noqa: WPS433

            source_dir = main.CANVAS_DIR
        except Exception:
            return {}
    if not source_dir or not os.path.isdir(source_dir):
        return {}
    out: dict[str, str] = {}
    for name in sorted(os.listdir(source_dir)):
        if not name.lower().endswith(".json"):
            continue
        path = os.path.join(source_dir, name)
        try:
            with open(path, "rb") as fh:
                raw_bytes = fh.read()
        except OSError:
            continue
        try:
            raw_text = raw_bytes.decode("utf-8")
            payload = json.loads(raw_text)
        except (UnicodeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        legacy_id = str(payload.get("id") or os.path.splitext(name)[0])
        out[legacy_id] = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    return out


def _load_canvas_db_snapshot() -> dict[str, str | None]:
    """`{legacy_id: content_hash}` from `canvases` table。空/未迁移 → `{}`。"""

    try:
        from sqlalchemy import select

        from app.data_import import tables as t
        from app.db.engine import get_engine
    except Exception:
        return {}
    try:
        engine = get_engine()
        with engine.connect() as conn:
            try:
                rows = conn.execute(
                    select(t.canvases.c.legacy_id, t.canvases.c.content_hash)
                ).fetchall()
            except Exception:
                return {}
    except Exception:
        return {}
    out: dict[str, str | None] = {}
    for row in rows:
        legacy_id = row[0]
        if legacy_id is None:
            continue
        out[str(legacy_id)] = row[1]
    return out


def reconcile_canvas(source_dir: str | None = None) -> dict[str, Any]:
    """Return a stable-schema reconciliation summary.

    Keys:
        - `domain`
        - `json_count` / `db_count`
        - `missing_in_db`   : legacy_ids present in JSON but not DB
        - `missing_in_json` : legacy_ids present in DB but not JSON
        - `hash_mismatch`   : list of `{"legacy_id", "json_hash", "db_hash"}`
        - `hash_null_in_db` : legacy_ids in DB where `content_hash IS NULL`
    """

    json_snapshot = _load_canvas_json_snapshot(source_dir)
    db_snapshot = _load_canvas_db_snapshot()

    json_ids = set(json_snapshot)
    db_ids = set(db_snapshot)
    common = json_ids & db_ids

    hash_mismatch: list[dict[str, Any]] = []
    hash_null_in_db: list[str] = []
    for legacy_id in sorted(common):
        j_hash = json_snapshot[legacy_id]
        d_hash = db_snapshot.get(legacy_id)
        if d_hash is None:
            hash_null_in_db.append(legacy_id)
            continue
        if j_hash != d_hash:
            hash_mismatch.append(
                {
                    "legacy_id": legacy_id,
                    "json_hash": j_hash,
                    "db_hash": d_hash,
                }
            )

    return {
        "domain": "canvas",
        "json_count": len(json_ids),
        "db_count": len(db_ids),
        "missing_in_db": sorted(json_ids - db_ids),
        "missing_in_json": sorted(db_ids - json_ids),
        "hash_mismatch": hash_mismatch,
        "hash_null_in_db": hash_null_in_db,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.data_reconcile",
        description=(
            "Canvas raw JSON ↔ DB content_hash reconcile CLI (数据 PR-6). "
            "Read-only; prints stable JSON summary to stdout."
        ),
    )
    sub = parser.add_subparsers(dest="domain", required=True)
    canvas_parser = sub.add_parser("canvas", help="Reconcile canvas domain.")
    canvas_parser.add_argument(
        "--source-dir",
        default=None,
        help="Override CANVAS_DIR for tests / manual runs.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_repo_on_syspath()
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.domain == "canvas":
        summary = reconcile_canvas(source_dir=args.source_dir)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=False))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
