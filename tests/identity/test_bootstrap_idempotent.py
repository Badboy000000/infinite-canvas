"""Bootstrap 幂等测试（权限 PR-0）。

连续调用 3 次 `tools/migrate_identity_bootstrap.py`：
- 第 1 次：完成 bootstrap，写入 4 个 JSON 文件；
- 第 2、3 次：读到 `bootstrap_completed_at != null`，直接 exit=0，
  **不写任何文件**、**不追加 notes**；
- 3 次运行后 8 个 identity JSON 的 sha256 稳定（第 2 次 hash == 第 1 次 hash）。

测试隔离：用 `tmp_path` 建临时 identity 目录，**不污染** 项目 `data/identity/`。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BOOTSTRAP_SCRIPT = REPO_ROOT / "tools" / "migrate_identity_bootstrap.py"


def _write(p: Path, payload) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")


def _seed_identity_dir(base: Path) -> None:
    """Seed the 8 initial JSON files + audit_logs.jsonl (matches PR-0 提交物)."""
    _write(base / "users.json", {"_schema_version": 1, "users": {}})
    _write(base / "user_aliases.json", {"_schema_version": 1, "aliases": []})
    _write(base / "workspaces.json", {"_schema_version": 1, "workspaces": {}})
    _write(
        base / "memberships.json",
        {
            "_schema_version": 1,
            "workspace_memberships": [],
            "project_memberships": [],
        },
    )
    _write(base / "roles.json", {"_schema_version": 1, "roles": {}})
    _write(
        base / "role_permissions.json",
        {"_schema_version": 1, "role_permissions": {}},
    )
    _write(base / "resource_acl.json", {"_schema_version": 1, "acl": []})
    _write(
        base / "auth_migration_state.json",
        {
            "_schema_version": 1,
            "bootstrap_completed_at": None,
            "legacy_mapping_completed_at": None,
            "notes": [],
        },
    )
    (base / "audit_logs.jsonl").write_bytes(b"")


def _hash_dir(base: Path) -> dict[str, str]:
    """Return sha256 hex for each JSON file in `base` (stable across runs)."""
    out = {}
    for p in sorted(base.iterdir()):
        if p.is_file():
            out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _run_bootstrap(identity_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP_SCRIPT),
            "--identity-dir",
            str(identity_dir),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def test_bootstrap_three_runs_are_idempotent(tmp_path: Path) -> None:
    identity = tmp_path / "identity"
    _seed_identity_dir(identity)

    # 第一次运行：完成 bootstrap
    r1 = _run_bootstrap(identity)
    assert r1.returncode == 0, (
        f"first run failed: stdout={r1.stdout!r} stderr={r1.stderr!r}"
    )
    assert "OK" in r1.stdout or "bootstrap_completed_at" in r1.stdout
    h1 = _hash_dir(identity)

    # 第二次运行：读到 bootstrap_completed_at 非 null，短路 exit=0
    r2 = _run_bootstrap(identity)
    assert r2.returncode == 0
    assert "已完成" in r2.stdout
    h2 = _hash_dir(identity)

    # 第三次运行：同样短路
    r3 = _run_bootstrap(identity)
    assert r3.returncode == 0
    assert "已完成" in r3.stdout
    h3 = _hash_dir(identity)

    # 三次哈希完全相同（含 auth_migration_state.notes 不追加）
    assert h1 == h2 == h3, (
        f"identity JSON hashes changed across idempotent runs: "
        f"h1={h1} h2={h2} h3={h3}"
    )


def test_bootstrap_dry_run_writes_nothing(tmp_path: Path) -> None:
    identity = tmp_path / "identity"
    _seed_identity_dir(identity)
    before = _hash_dir(identity)

    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP_SCRIPT),
            "--identity-dir",
            str(identity),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
    assert "dry-run" in result.stdout.lower()
    after = _hash_dir(identity)
    assert before == after, "dry-run 应该不落盘，但文件哈希变了"


def test_bootstrap_writes_default_workspace_and_admin(tmp_path: Path) -> None:
    identity = tmp_path / "identity"
    _seed_identity_dir(identity)

    result = _run_bootstrap(identity)
    assert result.returncode == 0

    # 验证 workspaces.json 落了 default-workspace
    ws = json.loads((identity / "workspaces.json").read_text(encoding="utf-8"))
    assert (
        "ws-default-00000000-0000-0000-0000-000000000000"
        in ws["workspaces"]
    )
    default_ws = ws["workspaces"][
        "ws-default-00000000-0000-0000-0000-000000000000"
    ]
    assert default_ws["name"] == "默认工作区"
    assert (
        default_ws["default_project_id"]
        == "proj-default-00000000-0000-0000-0000-000000000000"
    )

    # 验证 users.json 落了 system_admin 空位
    users = json.loads((identity / "users.json").read_text(encoding="utf-8"))
    admin = users["users"][
        "user-sysadmin-00000000-0000-0000-0000-000000000000"
    ]
    assert admin["username"] == "system_admin"
    assert admin["password_hash"] is None
    assert admin["status"] == "bootstrap_pending"

    # 验证 memberships.json
    memberships = json.loads(
        (identity / "memberships.json").read_text(encoding="utf-8")
    )
    assert len(memberships["workspace_memberships"]) == 1
    m = memberships["workspace_memberships"][0]
    assert m["role"] == "workspace_admin"
    assert m["user_id"] == "user-sysadmin-00000000-0000-0000-0000-000000000000"

    # 验证 auth_migration_state.json
    state = json.loads(
        (identity / "auth_migration_state.json").read_text(encoding="utf-8")
    )
    assert state["bootstrap_completed_at"] is not None
    assert any(
        "migrate_identity_bootstrap.py" in note for note in state["notes"]
    )


def test_bootstrap_fails_on_missing_seed_files(tmp_path: Path) -> None:
    """seed 文件缺失时脚本应 exit != 0 并打印错误。"""
    empty = tmp_path / "empty-identity"
    empty.mkdir()

    result = _run_bootstrap(empty)
    assert result.returncode != 0
    assert "缺失" in result.stderr or "ERROR" in result.stderr


def test_bootstrap_force_flag_prints_warning(tmp_path: Path) -> None:
    """`--force` 目前只是占位；不落盘 + 打印 warning。"""
    identity = tmp_path / "identity"
    _seed_identity_dir(identity)
    # 先跑一次让 state 完成
    r1 = _run_bootstrap(identity)
    assert r1.returncode == 0
    h1 = _hash_dir(identity)

    # 再用 --force 跑一次
    result = subprocess.run(
        [
            sys.executable,
            str(BOOTSTRAP_SCRIPT),
            "--identity-dir",
            str(identity),
            "--force",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
    assert "--force" in result.stderr and "未实现" in result.stderr
    h2 = _hash_dir(identity)
    assert h1 == h2  # --force 未实现，行为等同幂等短路
