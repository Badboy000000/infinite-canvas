"""OpenAPI baseline diff 校验脚本。

用法：
    python tools/openapi_diff.py --baseline tools/openapi_baseline.json

契约：
- 加载磁盘上的 baseline JSON 与运行时 `main.app.openapi()`。
- 结构化 diff：对比 `paths`、`components/schemas`、`components/securitySchemes`
  三块的键集合与内容，任何差异都以稳定 JSON 打印，退出码非 0。
- 完全一致时打印 `OK` 并退出 0。

首批 PR 协调纲要 "OpenAPI baseline 协议" 要求任一路由 / DTO 改动前先跑本脚本。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def _ensure_repo_on_syspath() -> None:
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _load_current() -> dict:
    _ensure_repo_on_syspath()
    os.chdir(REPO_ROOT)
    import main  # noqa: WPS433

    app = getattr(main, "app", None)
    if app is None:
        raise SystemExit("[openapi_diff] main.app 未定义")
    return app.openapi()


def _load_baseline(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"[openapi_diff] baseline 不存在: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or "paths" not in data:
        raise SystemExit(f"[openapi_diff] baseline 结构非法: {path}")
    return data


def _normalize(value: Any) -> Any:
    """把 openapi dict 归一化为可 hash 的稳定结构，便于对比。"""

    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def _diff_section(name: str, baseline: Any, current: Any) -> list[dict]:
    """按 name 对比两侧节，返回差异列表。差异条目 shape：
    {section, kind, key} 或 {section, kind, key, baseline, current}。
    """

    diffs: list[dict] = []
    if not isinstance(baseline, dict) or not isinstance(current, dict):
        if baseline != current:
            diffs.append({"section": name, "kind": "value_changed"})
        return diffs

    base_keys = set(baseline.keys())
    cur_keys = set(current.keys())
    for k in sorted(base_keys - cur_keys):
        diffs.append({"section": name, "kind": "removed", "key": k})
    for k in sorted(cur_keys - base_keys):
        diffs.append({"section": name, "kind": "added", "key": k})
    for k in sorted(base_keys & cur_keys):
        b = _normalize(baseline[k])
        c = _normalize(current[k])
        if b != c:
            diffs.append(
                {
                    "section": name,
                    "kind": "changed",
                    "key": k,
                    "baseline": b,
                    "current": c,
                }
            )
    return diffs


def main_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diff runtime OpenAPI against baseline.")
    parser.add_argument(
        "--baseline",
        default=str(REPO_ROOT / "tools" / "openapi_baseline.json"),
        help="baseline JSON 路径（默认 tools/openapi_baseline.json）",
    )
    args = parser.parse_args(argv)

    baseline = _load_baseline(Path(args.baseline).resolve())
    current = _load_current()

    all_diffs: list[dict] = []
    all_diffs.extend(_diff_section("paths", baseline.get("paths", {}), current.get("paths", {})))
    all_diffs.extend(
        _diff_section(
            "components.schemas",
            (baseline.get("components") or {}).get("schemas", {}),
            (current.get("components") or {}).get("schemas", {}),
        )
    )
    all_diffs.extend(
        _diff_section(
            "components.securitySchemes",
            (baseline.get("components") or {}).get("securitySchemes", {}),
            (current.get("components") or {}).get("securitySchemes", {}),
        )
    )

    if not all_diffs:
        print("[openapi_diff] OK: baseline == current")
        return 0

    print("[openapi_diff] MISMATCH:")
    print(json.dumps(all_diffs, ensure_ascii=False, indent=2, sort_keys=True))
    return 1


if __name__ == "__main__":
    sys.exit(main_cli())
