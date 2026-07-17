"""OpenAPI baseline 生成脚本。

用法：
    python tools/openapi_snapshot.py --out tools/openapi_baseline.json

契约：
- 通过 `import main` 加载当前后端，调用 FastAPI `app.openapi()` 得到 dict。
- 稳定序列化为 JSON（UTF-8、2 空格缩进、sort_keys=True），确保 diff 可比。
- 脚本必须能独立运行；exit code 0 表示成功。

首批 PR 协调纲要要求：PR-BE-01 首次落地 `tools/openapi_baseline.json` 后，
后续任何触碰路由 / DTO 的 PR 都须先跑 `tools/openapi_diff.py`。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _ensure_repo_on_syspath() -> None:
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _load_openapi() -> dict:
    _ensure_repo_on_syspath()
    # 切到仓库根目录后再 import main，避免 main.py 内的相对路径
    # （BASE_DIR / STORAGE_SETTINGS_FILE 等）与调用方 cwd 混淆。
    os.chdir(REPO_ROOT)
    import main  # noqa: WPS433 - 主动 import 目标模块以拿到 FastAPI 实例

    app = getattr(main, "app", None)
    if app is None:
        raise SystemExit("[openapi_snapshot] main.app 未定义，无法生成 baseline")
    schema = app.openapi()
    if not isinstance(schema, dict) or "paths" not in schema:
        raise SystemExit("[openapi_snapshot] openapi() 返回不含 paths，异常")
    return schema


def _dump(schema: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(schema, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")


def main_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Snapshot FastAPI OpenAPI schema.")
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "tools" / "openapi_baseline.json"),
        help="输出路径（默认 tools/openapi_baseline.json）",
    )
    args = parser.parse_args(argv)

    schema = _load_openapi()
    out_path = Path(args.out).resolve()
    _dump(schema, out_path)
    print(f"[openapi_snapshot] wrote {out_path} ({len(schema.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
