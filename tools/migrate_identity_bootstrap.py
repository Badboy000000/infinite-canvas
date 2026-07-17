"""identity bootstrap 迁移脚本（权限 PR-0）。

用途
====

在 `data/identity/` 首次建立：

1. **default-workspace**（`workspaces.json`）：
   `id="ws-default-00000000-0000-0000-0000-000000000000"` /
   `name="默认工作区"` / `default_project_id="proj-default-..."`。

2. **system_admin 空位**（`users.json`）：
   `id="user-sysadmin-00000000-0000-0000-0000-000000000000"` /
   `username="system_admin"` / `password_hash=null` /
   `status="bootstrap_pending"`。真正的密码 hash 由权限 PR-3 认证入口写入。

3. **workspace_membership**（`memberships.json`）：
   把 system_admin 挂到 default-workspace 的 `workspace_admin` 角色。

4. **auth_migration_state.json**：`bootstrap_completed_at` 写当前 ISO 时间戳，
   `notes` 追加一条"由 migrate_identity_bootstrap.py 于 <ts> 完成"。

设计约束
========

- **幂等**：读到 `bootstrap_completed_at != null` 直接 exit=0 打印"已完成"，
  **不写任何文件**、**不追加 notes**。第二、三次运行产生**字节完全相同**的
  `data/identity/*.json`（sha256 稳定）。
- **稳定序列化**：所有写入走 `json.dumps(..., ensure_ascii=False, indent=2,
  sort_keys=True)` + 尾随 `\n`，保证跨机器 / 跨运行字节一致。
- **原子替换**：先写 `.tmp` 再 `rename`，避免半写状态。
- **零运行时依赖**：只用 stdlib（argparse / json / uuid / datetime / pathlib）。
  **不 import app.identity.store**，避免脚本依赖 store facade 内部实现细节；
  但**所有输出格式必须与 `JsonIdentityStore._write_json` 一致**（indent=2 +
  sort_keys=True + `\n` 结尾），否则 store 再次写入时会与本脚本输出字节不同。
- **--force**：**未实现**（本 PR 时间紧；如需重跑 bootstrap，请手动删除
  `data/identity/auth_migration_state.json` 里 `bootstrap_completed_at` 字段并
  重跑）。argparse 里保留 `--force` 参数占位并 stderr 提示 TODO；避免下游脚本
  假设该参数已生效。

不做
====

- 不接入认证、不写密码 hash、不发登录 URL。
- 不落权限矩阵（`role_permissions.json` 保持空 map；PR-4 承接）。
- 不写任何 legacy_alias（PR-2 承接）。
- 不创建独立 `projects.json`（default-project 只在 workspaces.json 内标注
  `default_project_id` 字段；如未来方案明确要求独立表，走单独 PR）。

对齐
====

- [[40 实施计划/用户团队权限治理实施计划与PR清单]] PR-0
- [[50 决策记录/决策 - 主键类型]]（identity 全表 UUID + `legacy_owner_label` /
  `legacy_user_key`）
- [[60 讨论记录/2026-07-17 第二批开工/2026-07-17 第二批 PR 开工协调纲要]]
  §"目录与文件路径硬约定"
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_IDENTITY_DIR = REPO_ROOT / "data" / "identity"

# 固定 UUID 常量（本 bootstrap 脚本产出的 default-workspace / default-project /
# system_admin 三条记录使用**固定 UUID**，便于调试与跨机器对账）。
DEFAULT_WORKSPACE_ID = "ws-default-00000000-0000-0000-0000-000000000000"
DEFAULT_PROJECT_ID = "proj-default-00000000-0000-0000-0000-000000000000"
SYSTEM_ADMIN_USER_ID = "user-sysadmin-00000000-0000-0000-0000-000000000000"

SCHEMA_VERSION = 1


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string with `+00:00` suffix."""
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _read_json(p: Path) -> Any:
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json_atomic(p: Path, payload: Any) -> None:
    """Atomically write `payload` as JSON with stable serialization.

    Same shape as `JsonIdentityStore._write_json` — must match byte-for-byte:
    `ensure_ascii=False` + `indent=2` + `sort_keys=True` + trailing `\n`.
    """
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.write("\n")
    tmp.replace(p)


def _print_diff(label: str, payload: Any) -> None:
    """Print what *would* be written under `--dry-run`."""
    print(f"\n[dry-run] {label}:")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def bootstrap(identity_dir: Path, dry_run: bool = False) -> int:
    """Idempotent bootstrap.

    Returns exit code (0 = success or already completed).
    """

    state_file = identity_dir / "auth_migration_state.json"
    users_file = identity_dir / "users.json"
    workspaces_file = identity_dir / "workspaces.json"
    memberships_file = identity_dir / "memberships.json"

    for required in (
        state_file,
        users_file,
        workspaces_file,
        memberships_file,
        identity_dir / "roles.json",
        identity_dir / "role_permissions.json",
        identity_dir / "resource_acl.json",
        identity_dir / "user_aliases.json",
    ):
        if not required.is_file():
            print(
                f"[bootstrap] ERROR: identity 初始文件缺失：{required}\n"
                f"           先建立 `data/identity/` 目录与 8 个初始 JSON（"
                f"权限 PR-0 提交物应已包含）。",
                file=sys.stderr,
            )
            return 2

    # ---- 幂等短路：已完成则直接 exit=0 -----------------------------------

    state = _read_json(state_file)
    if not isinstance(state, dict):
        print(
            f"[bootstrap] ERROR: {state_file} 顶层必须是 object", file=sys.stderr
        )
        return 2
    if state.get("_schema_version") != SCHEMA_VERSION:
        print(
            f"[bootstrap] ERROR: {state_file}._schema_version 必须是 "
            f"{SCHEMA_VERSION}，实际得到 {state.get('_schema_version')!r}",
            file=sys.stderr,
        )
        return 2

    if state.get("bootstrap_completed_at"):
        print(
            f"[bootstrap] 已完成（bootstrap_completed_at="
            f"{state['bootstrap_completed_at']!r}）；exit=0，无任何写入。"
        )
        return 0

    # ---- 生成新内容 --------------------------------------------------------

    ts = _now_iso()

    # Workspaces：仅追加 default-workspace，不动其它记录（应为空）
    workspaces_payload = _read_json(workspaces_file)
    if not isinstance(workspaces_payload, dict):
        print(
            f"[bootstrap] ERROR: {workspaces_file} 顶层必须是 object",
            file=sys.stderr,
        )
        return 2
    workspaces_map: Dict[str, Any] = dict(workspaces_payload.get("workspaces", {}))
    workspaces_map[DEFAULT_WORKSPACE_ID] = {
        "id": DEFAULT_WORKSPACE_ID,
        "name": "默认工作区",
        "description": "由 migrate_identity_bootstrap.py 创建的默认工作区，"
        "承接历史资源（画布 / 素材 / 对话 / Provider 等）的归属。",
        "default_project_id": DEFAULT_PROJECT_ID,
        "legacy_owner_label": None,
        "created_at": ts,
        "updated_at": None,
    }
    new_workspaces = {
        "_schema_version": SCHEMA_VERSION,
        "workspaces": workspaces_map,
    }

    # Users：追加 system_admin 空位（status=bootstrap_pending）
    users_payload = _read_json(users_file)
    if not isinstance(users_payload, dict):
        print(
            f"[bootstrap] ERROR: {users_file} 顶层必须是 object", file=sys.stderr
        )
        return 2
    users_map: Dict[str, Any] = dict(users_payload.get("users", {}))
    users_map[SYSTEM_ADMIN_USER_ID] = {
        "id": SYSTEM_ADMIN_USER_ID,
        "username": "system_admin",
        "password_hash": None,
        "email": None,
        "display_name": "系统管理员",
        "status": "bootstrap_pending",
        "created_at": ts,
        "updated_at": None,
        "legacy_owner_label": None,
    }
    new_users = {
        "_schema_version": SCHEMA_VERSION,
        "users": users_map,
    }

    # Memberships：追加 (default-workspace, system_admin, workspace_admin)
    memberships_payload = _read_json(memberships_file)
    if not isinstance(memberships_payload, dict):
        print(
            f"[bootstrap] ERROR: {memberships_file} 顶层必须是 object",
            file=sys.stderr,
        )
        return 2
    ws_memberships: List[Dict[str, Any]] = list(
        memberships_payload.get("workspace_memberships", [])
    )
    ws_memberships.append(
        {
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "user_id": SYSTEM_ADMIN_USER_ID,
            "role": "workspace_admin",
            "created_at": ts,
        }
    )
    proj_memberships: List[Dict[str, Any]] = list(
        memberships_payload.get("project_memberships", [])
    )
    new_memberships = {
        "_schema_version": SCHEMA_VERSION,
        "workspace_memberships": ws_memberships,
        "project_memberships": proj_memberships,
    }

    # auth_migration_state：写 bootstrap_completed_at + 追加一条 notes
    new_state = {
        "_schema_version": SCHEMA_VERSION,
        "bootstrap_completed_at": ts,
        "legacy_mapping_completed_at": state.get("legacy_mapping_completed_at"),
        "notes": list(state.get("notes", []))
        + [f"由 migrate_identity_bootstrap.py 于 {ts} 完成 identity bootstrap"],
    }

    # ---- Dry-run 输出 ------------------------------------------------------

    if dry_run:
        print("[bootstrap] --dry-run：以下内容将写入 4 个文件，但不落盘。")
        _print_diff(str(workspaces_file), new_workspaces)
        _print_diff(str(users_file), new_users)
        _print_diff(str(memberships_file), new_memberships)
        _print_diff(str(state_file), new_state)
        return 0

    # ---- 实际写入 ----------------------------------------------------------

    _write_json_atomic(workspaces_file, new_workspaces)
    _write_json_atomic(users_file, new_users)
    _write_json_atomic(memberships_file, new_memberships)
    _write_json_atomic(state_file, new_state)

    print(
        f"[bootstrap] OK: default-workspace + system_admin 空位落盘完成；"
        f"bootstrap_completed_at={ts!r}。"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="migrate_identity_bootstrap",
        description="Identity bootstrap 迁移脚本（权限 PR-0，幂等）。",
    )
    parser.add_argument(
        "--identity-dir",
        default=str(DEFAULT_IDENTITY_DIR),
        help=f"identity 数据目录（默认 {DEFAULT_IDENTITY_DIR}）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印将写入的内容，不落盘。",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="[TODO/未实现] 强制重跑 bootstrap（忽略 bootstrap_completed_at）。"
        "本 PR（权限 PR-0）先不实现；如需重跑请手动改 "
        "auth_migration_state.json 后再运行。",
    )
    return parser


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    identity_dir = Path(args.identity_dir).resolve()

    if args.force:
        print(
            "[bootstrap] WARNING: --force 参数已保留占位，但本 PR（权限 PR-0）"
            "未实现该逻辑。脚本将按普通幂等路径执行；如需强制重跑，请手动清空 "
            "`auth_migration_state.json` 的 `bootstrap_completed_at` 字段再运行。",
            file=sys.stderr,
        )

    return bootstrap(identity_dir=identity_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
