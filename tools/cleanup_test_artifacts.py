#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试残留清理脚本。

用途
====
每次执行完保活烟测、契约测试、临时 curl 验证之后，把仓库回退到"只有正式代
码"的状态。默认只做 dry-run（列出将删除什么），加 ``--apply`` 才真正动手。

覆盖的残留类别
==============
1. **Python 缓存**：递归 ``__pycache__/``、``*.pyc``、``.pytest_cache/``。
2. **顶层散落空目录**：``X/`` / ``Y/`` / ``Z/`` 之类只在临时 curl / adhoc
   脚本时被创建的空字母目录（仅在**为空**时删除）。
3. **烟测污染的数据文件**：
   - ``data/api_providers.json`` 内 ``id`` 以 ``__smoke`` 开头的 provider
     条目（来自 backend-smoke item #6 ``PUT /api/providers`` 烟测）；
   - ``data/canvases/*.json`` 内 ``title`` 以 ``__smoke`` 开头 **或** ``title``
     恰为 ``smoke`` 的画布文件（来自 backend-smoke item #7 canvas 409 烟测）。
4. **烟测建的空 output 子目录**：``output/input/`` / ``output/output/``
   （仅在**为空**时删除；一旦你在里面有真实生成结果，就不会误删）。

不覆盖的类别
============
- ``data/`` 内除 ``api_providers.json`` 与 ``canvases/`` 之外的任何东西
  （素材库、会话、历史）——避免误伤真实用户数据。
- ``API/.env`` / ``.env*``——密钥文件。
- ``docs/`` / ``tests/`` / ``tools/`` 内任何文件——这些是**正式产物**，不是
  测试残留。
- ``packages/``、``assets/``、``static/`` 等目录——正式发布物。

CLI
===
::

    # 默认 dry-run，仅打印
    python tools/cleanup_test_artifacts.py

    # 真正执行
    python tools/cleanup_test_artifacts.py --apply

    # 只清缓存（不动 data 与 output）
    python tools/cleanup_test_artifacts.py --apply --skip-data --skip-output

    # 静默模式（用于 pre-commit / CI）
    python tools/cleanup_test_artifacts.py --apply --quiet

退出码
======
- ``0``：执行完成（dry-run 与 apply 都算成功）。
- ``2``：命令行参数错误。
- ``3``：apply 阶段任意一项因文件锁 / 权限失败（其他项仍尽力清理）。

治理规范
========
本脚本对齐 [[AGENTS.md]] / [[CLAUDE.md]] "测试残留清理" 章节。任何 subagent
在完成保活烟测 / 契约测试后必须先跑 ``--apply`` 再 `git status`，避免仓库
被 ``__smoke__`` / ``__pycache__`` / 空 X-Y-Z 目录污染。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

# 顶层散落空目录候选：只在这些目录**为空**时才删；有内容一律保留。
TOP_LEVEL_STRAY_EMPTY_DIRS = ("X", "Y", "Z")

# 烟测建的 output 子目录候选：只在为空时删。
OUTPUT_STRAY_EMPTY_SUBDIRS = ("output/input", "output/output")

# 需要清理的顶层缓存目录（无条件递归删）。
CACHE_DIRS_TOP = (".pytest_cache",)

# 需要递归清理的目录名。
CACHE_DIRS_ANY_DEPTH = ("__pycache__",)

# 需要递归清理的文件后缀。
CACHE_FILE_SUFFIXES = (".pyc", ".pyo")

# data 目录内被烟测污染的具体文件与判据。
API_PROVIDERS_FILE = REPO_ROOT / "data" / "api_providers.json"
CANVASES_DIR = REPO_ROOT / "data" / "canvases"

# 任务 PR-0 追加：`data/app.db` SQLite 文件由测试或 CLI 烟测生成。
# 判据（`--skip-data` 不影响本项，另有 `--skip-appdb` 单独开关）：
# - 文件为空（0 字节）或仅含 `alembic_version` 系统表（无业务数据）：清理；
# - 含任一业务表 (`tasks` / `node_runs` / `provider_tasks` / `task_events`
#   / `artifacts` 等)：**保留**（视为真实数据，防误删）。
APP_DB_FILE = REPO_ROOT / "data" / "app.db"

# 保护路径：脚本永远不会 rm -rf 这些目录（哪怕误传参数）。
NEVER_TOUCH_ROOTS = {
    REPO_ROOT / "API",
    REPO_ROOT / "app",
    REPO_ROOT / "docs",
    REPO_ROOT / "packages",
    REPO_ROOT / "static",
    REPO_ROOT / "tests",
    REPO_ROOT / "tools",
    REPO_ROOT / "workflows",
    REPO_ROOT / ".git",
    REPO_ROOT / ".claude",
    REPO_ROOT / ".trae",
    REPO_ROOT / "assets",
    REPO_ROOT / "CLI",
    REPO_ROOT / "API",
}


class Reporter:
    def __init__(self, apply: bool, quiet: bool) -> None:
        self.apply = apply
        self.quiet = quiet
        self.removed_paths: List[str] = []
        self.removed_data_entries: List[str] = []
        self.failed: List[Tuple[str, str]] = []

    def note(self, msg: str) -> None:
        if not self.quiet:
            print(msg)

    def would_remove_path(self, path: Path, kind: str) -> None:
        rel = path.relative_to(REPO_ROOT).as_posix() if path.is_absolute() else str(path)
        marker = "REMOVE" if self.apply else "DRY-RUN"
        self.note(f"[{marker}] [{kind}] {rel}")
        self.removed_paths.append(rel)

    def would_remove_entry(self, file_rel: str, entry_desc: str) -> None:
        marker = "REMOVE" if self.apply else "DRY-RUN"
        self.note(f"[{marker}] [data] {file_rel} :: {entry_desc}")
        self.removed_data_entries.append(f"{file_rel} :: {entry_desc}")

    def fail(self, path: Path, reason: str) -> None:
        rel = path.relative_to(REPO_ROOT).as_posix() if path.is_absolute() else str(path)
        self.note(f"[FAIL] {rel}: {reason}")
        self.failed.append((rel, reason))


def _safe_under_repo(p: Path) -> bool:
    """确认路径在仓库根下、并且不在保护根之下。"""
    try:
        resolved = p.resolve()
    except OSError:
        return False
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError:
        return False
    for guard in NEVER_TOUCH_ROOTS:
        try:
            resolved.relative_to(guard)
            return False
        except ValueError:
            continue
    return True


def _rm_dir(path: Path, reporter: Reporter, kind: str) -> None:
    reporter.would_remove_path(path, kind)
    if not reporter.apply:
        return
    if not _safe_under_repo(path) and kind not in {"cache"}:
        reporter.fail(path, "落在保护根内或不在仓库根下，跳过")
        return
    try:
        shutil.rmtree(path)
    except OSError as exc:
        reporter.fail(path, f"{type(exc).__name__}: {exc}")


def _rm_file(path: Path, reporter: Reporter, kind: str) -> None:
    reporter.would_remove_path(path, kind)
    if not reporter.apply:
        return
    try:
        path.unlink()
    except OSError as exc:
        reporter.fail(path, f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# 1. Python 缓存
# ---------------------------------------------------------------------------

def clean_python_caches(reporter: Reporter) -> None:
    # 1a. 顶层 .pytest_cache
    for name in CACHE_DIRS_TOP:
        p = REPO_ROOT / name
        if p.is_dir():
            _rm_dir(p, reporter, "cache")

    # 1b. 递归 __pycache__
    for root, dirs, _files in os.walk(REPO_ROOT):
        root_path = Path(root)
        # 跳过 .git 与保护根内递归（.git 尤其重要，别走进去）
        if any(part in {".git", "node_modules"} for part in root_path.parts):
            dirs[:] = []
            continue
        for d in list(dirs):
            if d in CACHE_DIRS_ANY_DEPTH:
                _rm_dir(root_path / d, reporter, "cache")
                dirs.remove(d)

    # 1c. 递归 *.pyc / *.pyo
    for root, dirs, files in os.walk(REPO_ROOT):
        root_path = Path(root)
        if any(part in {".git", "node_modules"} for part in root_path.parts):
            dirs[:] = []
            continue
        for f in files:
            if f.endswith(CACHE_FILE_SUFFIXES):
                _rm_file(root_path / f, reporter, "cache")


# ---------------------------------------------------------------------------
# 2. 顶层散落空目录
# ---------------------------------------------------------------------------

def clean_top_level_stray_empty_dirs(reporter: Reporter) -> None:
    for name in TOP_LEVEL_STRAY_EMPTY_DIRS:
        p = REPO_ROOT / name
        if not p.is_dir():
            continue
        try:
            has_content = any(p.iterdir())
        except OSError as exc:
            reporter.fail(p, f"{type(exc).__name__}: {exc}")
            continue
        if has_content:
            reporter.note(f"[SKIP] [stray-dir] {name}/ 非空，保留（如需清理请人工检查）")
            continue
        _rm_dir(p, reporter, "stray-dir")


# ---------------------------------------------------------------------------
# 3. 空 output 子目录
# ---------------------------------------------------------------------------

def clean_empty_output_subdirs(reporter: Reporter) -> None:
    for rel in OUTPUT_STRAY_EMPTY_SUBDIRS:
        p = REPO_ROOT / rel
        if not p.is_dir():
            continue
        try:
            has_content = any(p.iterdir())
        except OSError as exc:
            reporter.fail(p, f"{type(exc).__name__}: {exc}")
            continue
        if has_content:
            reporter.note(f"[SKIP] [output-empty] {rel}/ 非空，保留")
            continue
        _rm_dir(p, reporter, "output-empty")


# ---------------------------------------------------------------------------
# 4. 烟测污染的 data 文件
# ---------------------------------------------------------------------------

def _is_smoke_provider(entry: dict) -> bool:
    if not isinstance(entry, dict):
        return False
    pid = str(entry.get("id", ""))
    name = str(entry.get("name", ""))
    if pid.startswith("__smoke"):
        return True
    if name.lower() in {"smoke", "smoke-test", "__smoke__"}:
        return True
    return False


def clean_smoke_providers(reporter: Reporter) -> None:
    if not API_PROVIDERS_FILE.is_file():
        return
    try:
        with API_PROVIDERS_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        reporter.fail(API_PROVIDERS_FILE, f"读失败：{type(exc).__name__}: {exc}")
        return
    if not isinstance(data, list):
        # 兼容 shape 变化，不动
        return
    kept: List[dict] = []
    dropped_desc: List[str] = []
    for entry in data:
        if _is_smoke_provider(entry):
            dropped_desc.append(f'id={entry.get("id")!r} name={entry.get("name")!r}')
        else:
            kept.append(entry)
    if not dropped_desc:
        return
    rel = API_PROVIDERS_FILE.relative_to(REPO_ROOT).as_posix()
    for desc in dropped_desc:
        reporter.would_remove_entry(rel, f"provider {desc}")
    if not reporter.apply:
        return
    try:
        with API_PROVIDERS_FILE.open("w", encoding="utf-8") as f:
            json.dump(kept, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError as exc:
        reporter.fail(API_PROVIDERS_FILE, f"写失败：{type(exc).__name__}: {exc}")


def _is_smoke_canvas(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    title = str(payload.get("title", ""))
    cid = str(payload.get("id", ""))
    if title.startswith("__smoke"):
        return True
    if title == "smoke":
        return True
    if cid.startswith("__smoke"):
        return True
    return False


def clean_smoke_canvases(reporter: Reporter) -> None:
    if not CANVASES_DIR.is_dir():
        return
    for canvas_file in sorted(CANVASES_DIR.glob("*.json")):
        try:
            with canvas_file.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            # 损坏文件不属于烟测残留判定范围，跳过
            continue
        if _is_smoke_canvas(payload):
            _rm_file(canvas_file, reporter, "smoke-canvas")


# ---------------------------------------------------------------------------
# 5. data/app.db 空/仅系统表 —— 任务 PR-0 追加
# ---------------------------------------------------------------------------


def _app_db_is_empty_or_system_only(path: Path) -> bool:
    """判断 `data/app.db` 是否为"空 sqlite 或仅含 `alembic_version` 系统表"。

    - 文件不存在或 0 字节：视为空。
    - 打开失败（非 sqlite / 权限）：**返回 False**（保留，不误删）。
    - 表清单为空 或 只有 `alembic_version`：视为空。
    - 含任一业务表：**返回 False**（保留）。
    """
    import sqlite3

    try:
        if not path.is_file():
            return True
        if path.stat().st_size == 0:
            return True
        conn = sqlite3.connect(str(path))
        try:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            names = {row[0] for row in cur.fetchall()}
        finally:
            conn.close()
    except (sqlite3.DatabaseError, OSError):
        return False
    business = names - {"alembic_version"}
    return not business


def clean_empty_app_db(reporter: Reporter) -> None:
    """清理"空 / 仅含 alembic_version"的 `data/app.db`。

    真实用户数据一旦落进业务表（`tasks` / `node_runs` / ...），本函数保留。
    """
    if not APP_DB_FILE.exists():
        return
    if _app_db_is_empty_or_system_only(APP_DB_FILE):
        _rm_file(APP_DB_FILE, reporter, "empty-app-db")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cleanup_test_artifacts",
        description="清理仓库内测试残留（Python 缓存 / 空临时目录 / 烟测污染的 data 条目）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="真正执行清理（默认只做 dry-run 打印将要删除的内容）",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="不打印每条动作（仅打印汇总）",
    )
    p.add_argument(
        "--skip-cache",
        action="store_true",
        help="跳过 Python 缓存清理（__pycache__、.pytest_cache、*.pyc）",
    )
    p.add_argument(
        "--skip-stray",
        action="store_true",
        help="跳过顶层空散落目录（X/、Y/、Z/）",
    )
    p.add_argument(
        "--skip-output",
        action="store_true",
        help="跳过空 output 子目录（output/input/、output/output/）",
    )
    p.add_argument(
        "--skip-data",
        action="store_true",
        help="跳过 data/ 内烟测数据清理（api_providers.json 与 canvases/）",
    )
    p.add_argument(
        "--skip-appdb",
        action="store_true",
        help="跳过 data/app.db 空文件清理（任务 PR-0 追加）",
    )
    return p


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    reporter = Reporter(apply=args.apply, quiet=args.quiet)

    if not args.skip_cache:
        clean_python_caches(reporter)
    if not args.skip_stray:
        clean_top_level_stray_empty_dirs(reporter)
    if not args.skip_output:
        clean_empty_output_subdirs(reporter)
    if not args.skip_data:
        clean_smoke_providers(reporter)
        clean_smoke_canvases(reporter)
    if not args.skip_appdb:
        clean_empty_app_db(reporter)

    # 汇总（无论 quiet 都打印）
    mode = "APPLY" if args.apply else "DRY-RUN"
    total_paths = len(reporter.removed_paths)
    total_entries = len(reporter.removed_data_entries)
    total_failed = len(reporter.failed)
    print(
        f"[cleanup_test_artifacts] {mode} 完成："
        f"路径 {total_paths} 项 / 数据条目 {total_entries} 项 / 失败 {total_failed} 项"
    )
    if not args.apply and (total_paths or total_entries):
        print("[cleanup_test_artifacts] 上述均为 dry-run，加 --apply 真正执行。")
    if total_failed:
        for rel, reason in reporter.failed:
            print(f"  FAIL: {rel} :: {reason}")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
