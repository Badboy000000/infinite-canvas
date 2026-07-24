"""Legacy migration rollback — 权限 PR-2 承接（Wave 3-N.8 Batch 1 主线 A）。

从 `data.backup.<timestamp>/` 目录恢复 `data/`，撤销
`tools/migrate_legacy_semantics.py` 造成的所有 identity 侧变更。

用法
====

- 列出可用备份：`python tools/rollback_legacy_migration.py --list`
- 指定备份名恢复：
  `python tools/rollback_legacy_migration.py --backup-name data.backup.<ts>`
- 从任意路径恢复：
  `python tools/rollback_legacy_migration.py --backup-path /path/to/data.backup.<ts>`

约束
====

- **默认行为**：先把当前 `data/` 移动到 `data.rollback_from.<ts>/` 作为安全网，
  再拷贝备份到 `data/`；`--force` 跳过安全网并直接覆盖。
- **只用 stdlib**（`argparse` / `shutil` / `pathlib`）。
- **不改任何其它路径**（`app/` / `tests/` / `packages/` 等一概不动）。
- **零 credential 读取**：从不 open provider credential / cookie 文件；只做目录级 shutil 拷贝。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

if sys.platform == "win32":
    try:  # pragma: no cover — Windows-only defensive path
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "data"
_BACKUP_PREFIX = "data.backup."
_ROLLBACK_SAFETY_PREFIX = "data.rollback_from."


def _now_slug() -> str:
    return (
        datetime.now(tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace(":", "")
        .replace("+", "p")
        .replace("-", "")
    )


def _list_backups(backup_root: Path) -> List[Path]:
    if not backup_root.is_dir():
        return []
    return sorted(
        p
        for p in backup_root.iterdir()
        if p.is_dir() and p.name.startswith(_BACKUP_PREFIX)
    )


def rollback(
    data_dir: Path,
    backup_path: Path,
    *,
    force: bool = False,
) -> int:
    """从 backup_path 恢复到 data_dir。"""

    if not backup_path.is_dir():
        print(
            f"[rollback-legacy] ERROR: 备份目录不存在：{backup_path}",
            file=sys.stderr,
        )
        return 2

    data_dir = data_dir.resolve()
    backup_path = backup_path.resolve()
    if data_dir == backup_path:
        print(
            "[rollback-legacy] ERROR: data-dir 与 backup-path 相同",
            file=sys.stderr,
        )
        return 2

    if data_dir.exists():
        if force:
            shutil.rmtree(data_dir)
            print(f"[rollback-legacy] --force：已删除当前 {data_dir}")
        else:
            safety = data_dir.parent / f"{_ROLLBACK_SAFETY_PREFIX}{_now_slug()}"
            shutil.move(str(data_dir), str(safety))
            print(f"[rollback-legacy] 已把当前 {data_dir} 移到 {safety}（安全网）")

    shutil.copytree(backup_path, data_dir, symlinks=False)
    print(f"[rollback-legacy] OK: 已从 {backup_path} 恢复到 {data_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rollback_legacy_migration",
        description="Legacy migration rollback（权限 PR-2）：从 data.backup.<ts>/ 恢复 data/。",
    )
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help=f"数据目录（默认 {DEFAULT_DATA_DIR}）",
    )
    parser.add_argument(
        "--backup-root",
        default=None,
        help="备份根目录（默认 data-dir 的父目录）。",
    )
    parser.add_argument(
        "--backup-name",
        default=None,
        help=f"备份目录名（如 {_BACKUP_PREFIX}<ts>）；与 --backup-path 二选一。",
    )
    parser.add_argument(
        "--backup-path",
        default=None,
        help="备份目录完整路径；与 --backup-name 二选一。",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出可用备份并退出。",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="跳过安全网直接删除当前 data-dir；否则先移到 data.rollback_from.<ts>/。",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = Path(args.data_dir).resolve()
    backup_root = (
        Path(args.backup_root).resolve()
        if args.backup_root
        else data_dir.parent
    )

    if args.list:
        found = _list_backups(backup_root)
        if not found:
            print(f"[rollback-legacy] {backup_root} 下无可用备份。")
            return 0
        print(f"[rollback-legacy] {backup_root} 下的备份：")
        for p in found:
            print(f"  {p.name}")
        return 0

    if args.backup_path:
        backup_path = Path(args.backup_path).resolve()
    elif args.backup_name:
        backup_path = (backup_root / args.backup_name).resolve()
    else:
        print(
            "[rollback-legacy] ERROR: 请提供 --backup-name 或 --backup-path，或使用 --list。",
            file=sys.stderr,
        )
        return 2

    return rollback(data_dir=data_dir, backup_path=backup_path, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
