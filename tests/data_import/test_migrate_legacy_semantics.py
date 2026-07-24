"""`tools/migrate_legacy_semantics.py` + `tools/rollback_legacy_migration.py`
契约与安全测试（权限 PR-2 · Wave 3-N.8 Batch 1 主线 A）。

覆盖：

- T10-T19（契约）：
  - T10: 迁移幂等（连续 3 次结果字节等价）。
  - T11: `x_user_id` → UserAlias 幂等（重复 x_user_id 只写一次）。
  - T12: 缺失 workspace_id 时通过 fill_default_workspace_project 100% 回填（在
    manifest 中生效）。
  - T13: 备份 + rollback 端到端。
  - T14: dry-run 不落盘。
  - T15: 已完成短路（`legacy_mapping_completed_at != null` → exit=0 无写入）。
  - T16: 稳定 alias id（同 (kind, key) 输入 → 同 id）。

- T30-T39（P0 密钥零泄漏防线）：
  - T30-T38: 9 sentinel case-insensitive 独立扫描 identity/ 全量输出全 0 命中。
  - T39: 迁移脚本不 open API/.env / provider credential 文件。

- T40-T49（AST 硬护栏 · migration 侧）：非直接 AST 断言，走 baseline byte
  一致性（第 2、3 次运行的 identity JSON hash 稳定）。

所有测试使用 `tmp_path` 隔离；不接触项目 `data/`。
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATE_SCRIPT = REPO_ROOT / "tools" / "migrate_legacy_semantics.py"
ROLLBACK_SCRIPT = REPO_ROOT / "tools" / "rollback_legacy_migration.py"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write(p: Path, payload) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        if isinstance(payload, (bytes, bytearray)):
            fh.buffer.write(payload)  # type: ignore[attr-defined]
        else:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")


def _seed_identity(base: Path) -> None:
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
            "bootstrap_completed_at": "2026-07-24T00:00:00+00:00",
            "legacy_mapping_completed_at": None,
            "notes": ["bootstrap done"],
        },
    )
    (base / "audit_logs.jsonl").write_bytes(b"")


def _seed_data(base: Path) -> None:
    """Seed 一份有代表性的 legacy 数据集。"""

    (base / "canvases").mkdir(parents=True, exist_ok=True)
    _write(
        base / "canvases" / "c1.json",
        {"id": "c1", "owner": "Alice", "x_user_id": "user-a", "title": "画布 1"},
    )
    _write(
        base / "canvases" / "c2.json",
        {"id": "c2", "owner": "Bob", "x_user_id": "user-a", "title": "画布 2"},
    )
    _write(
        base / "canvases" / "c3.json",
        {"id": "c3", "owner": None, "x_user_id": None, "title": "画布 3"},
    )
    (base / "conversations" / "user-a").mkdir(parents=True, exist_ok=True)
    (base / "conversations" / "user-b").mkdir(parents=True, exist_ok=True)
    _write(
        base / "projects.json",
        {
            "projects": [
                {"id": "proj-1", "owner_label": "Alice", "name": "第一项目"},
                {"id": "proj-2", "owner_label": None, "name": "第二项目"},
            ]
        },
    )
    _write(
        base / "asset_library.json",
        {
            "active_library_id": "default",
            "libraries": [{"id": "default", "owner": "Alice"}],
        },
    )
    _write(
        base / "api_providers.json",
        [
            # 无 owner 字段的经典 provider 记录（治理期常态）
            {"id": "p1", "type": "openai"},
        ],
    )
    _write(
        base / "history.json",
        [{"user_key": "user-a", "ts": "2026-01-01T00:00:00+00:00"}],
    )


@pytest.fixture()
def env(tmp_path: Path):
    data_dir = tmp_path / "data"
    identity = data_dir / "identity"
    data_dir.mkdir(parents=True, exist_ok=True)
    identity.mkdir(parents=True, exist_ok=True)
    _seed_identity(identity)
    _seed_data(data_dir)
    return data_dir, identity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_migrate():
    """动态 import 脚本模块，避免 subprocess 开销并允许注入 timestamp。"""

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_tools_migrate_legacy_semantics", MIGRATE_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _hash_dir(base: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for p in sorted(base.iterdir()):
        if p.is_file():
            out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# ---------------------------------------------------------------------------
# T10-T19: 契约
# ---------------------------------------------------------------------------


def test_T10_migration_idempotent_three_runs(env) -> None:
    data_dir, identity = env
    mod = _import_migrate()
    fixed_ts = "2026-07-24T12:00:00+00:00"
    rc = mod.migrate(
        data_dir=data_dir,
        identity_dir=identity,
        do_backup=False,
        timestamp=fixed_ts,
    )
    assert rc == 0
    h1 = _hash_dir(identity)
    # 第二次：短路 exit=0，不写任何文件
    rc = mod.migrate(
        data_dir=data_dir,
        identity_dir=identity,
        do_backup=False,
        timestamp=fixed_ts,
    )
    assert rc == 0
    h2 = _hash_dir(identity)
    # 第三次：同样短路
    rc = mod.migrate(
        data_dir=data_dir,
        identity_dir=identity,
        do_backup=False,
        timestamp=fixed_ts,
    )
    assert rc == 0
    h3 = _hash_dir(identity)
    assert h1 == h2 == h3, (
        f"identity JSON hashes should be byte-stable across idempotent runs: "
        f"{h1} vs {h2} vs {h3}"
    )


def test_T11_x_user_id_alias_dedup(env) -> None:
    """重复出现的 x_user_id 只产生一条 alias."""

    data_dir, identity = env
    mod = _import_migrate()
    rc = mod.migrate(
        data_dir=data_dir,
        identity_dir=identity,
        do_backup=False,
        timestamp="2026-07-24T12:00:00+00:00",
    )
    assert rc == 0
    payload = json.loads(
        (identity / "user_aliases.json").read_text(encoding="utf-8")
    )
    aliases = payload["aliases"]
    x_user_ids = [a for a in aliases if a["kind"] == "x_user_id"]
    keys = [a["legacy_user_key"] for a in x_user_ids]
    # `user-a` 在 c1/c2/history 里出现 3 次，`user-b` 未在 canvas / history，
    # 但会通过 conversation_dir=user-b 命中。所以 x_user_id 应仅 {"user-a"}
    assert "user-a" in keys
    assert len(keys) == len(set(keys)), f"x_user_id aliases 存在重复: {keys}"
    # conversation_dir 覆盖 user-a / user-b
    conv_keys = sorted(
        a["legacy_user_key"] for a in aliases if a["kind"] == "conversation_dir"
    )
    assert conv_keys == ["user-a", "user-b"]


def test_T12_shadow_manifest_workspace_project_coverage(env) -> None:
    data_dir, identity = env
    mod = _import_migrate()
    rc = mod.migrate(
        data_dir=data_dir,
        identity_dir=identity,
        do_backup=False,
        timestamp="2026-07-24T12:00:00+00:00",
    )
    assert rc == 0
    manifest = json.loads(
        (identity / "legacy_shadow_manifest.json").read_text(encoding="utf-8")
    )
    entries: List[dict] = manifest["entries"]
    assert entries, "shadow manifest should not be empty"
    # 100% 回填默认 workspace / project
    ws_ok = all(
        e["workspace_id"] == mod.DEFAULT_WORKSPACE_ID for e in entries
    )
    pj_ok = all(e["project_id"] == mod.DEFAULT_PROJECT_ID for e in entries)
    assert ws_ok and pj_ok
    # 至少覆盖 canvas / asset_library / project / conversation_dir 四类资源
    resource_types = {e["resource_type"] for e in entries}
    for t in ("canvas", "asset_library", "project", "conversation_dir"):
        assert t in resource_types


def test_T13_backup_and_rollback_e2e(tmp_path: Path, env) -> None:
    data_dir, identity = env
    mod = _import_migrate()
    fixed_ts = "2026-07-24T12:00:00+00:00"
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    rc = mod.migrate(
        data_dir=data_dir,
        identity_dir=identity,
        do_backup=True,
        backup_root=backup_root,
        timestamp=fixed_ts,
    )
    assert rc == 0
    backups = list(backup_root.glob("data.backup.*"))
    assert len(backups) == 1
    backup_dir = backups[0]
    # 迁移后 identity/user_aliases.json 内容变化
    aliases_after = json.loads(
        (identity / "user_aliases.json").read_text(encoding="utf-8")
    )
    assert aliases_after["aliases"], "aliases should be populated after migration"

    # 备份里的 identity/user_aliases.json 仍然是原始空数组
    backup_aliases = json.loads(
        (backup_dir / "identity" / "user_aliases.json").read_text(encoding="utf-8")
    )
    assert backup_aliases["aliases"] == []

    # 执行 rollback（用 subprocess 走完整 CLI）
    result = subprocess.run(
        [
            sys.executable,
            str(ROLLBACK_SCRIPT),
            "--data-dir",
            str(data_dir),
            "--backup-root",
            str(tmp_path),  # 安全网会移到 tmp_path 下
            "--backup-path",
            str(backup_dir),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"rollback failed: {result.stderr}"

    # 恢复后 data/ 应该等价于备份内容
    aliases_restored = json.loads(
        (data_dir / "identity" / "user_aliases.json").read_text(encoding="utf-8")
    )
    assert aliases_restored["aliases"] == []
    # 原有 canvases 仍在
    assert (data_dir / "canvases" / "c1.json").is_file()


def test_T14_dry_run_no_write(env) -> None:
    data_dir, identity = env
    before = _hash_dir(identity)
    result = subprocess.run(
        [
            sys.executable,
            str(MIGRATE_SCRIPT),
            "--data-dir",
            str(data_dir),
            "--identity-dir",
            str(identity),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
    assert "dry-run" in result.stdout.lower()
    after = _hash_dir(identity)
    assert before == after


def test_T15_short_circuit_when_already_completed(env) -> None:
    data_dir, identity = env
    # 手动写入 legacy_mapping_completed_at
    state_path = identity / "auth_migration_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["legacy_mapping_completed_at"] = "2026-07-01T00:00:00+00:00"
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    before = _hash_dir(identity)
    mod = _import_migrate()
    rc = mod.migrate(
        data_dir=data_dir,
        identity_dir=identity,
        do_backup=False,
        timestamp="2026-07-24T12:00:00+00:00",
    )
    assert rc == 0
    after = _hash_dir(identity)
    assert before == after, "已完成状态下不应改动任何文件"


def test_T16_stable_alias_id(env) -> None:
    data_dir, identity = env
    mod = _import_migrate()
    a = mod._stable_alias_id("x_user_id", "user-a")
    b = mod._stable_alias_id("x_user_id", "user-a")
    c = mod._stable_alias_id("x_user_id", "user-b")
    d = mod._stable_alias_id("conversation_dir", "user-a")
    assert a == b
    assert a != c and a != d
    # 形似 UUID
    assert re.match(
        r"^alias-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        a,
    )


# ---------------------------------------------------------------------------
# T30-T39: P0 密钥零泄漏防线
# ---------------------------------------------------------------------------


# 9 sentinel patterns（case-insensitive）—— 与任务书 T30-T39 对齐
_SECRET_PATTERNS = [
    r"api_key",
    r"access_token",
    r"secret",
    r"bearer",
    r"sk-",
    r"akia",
    r"asia",
    r"password_hash",
    r"authorization",
]


def _grep_identity_secrets(identity_dir: Path) -> Dict[str, List[str]]:
    """扫描 identity/ 下所有文件，返回每 pattern 的命中行片段。"""

    combined = re.compile("|".join(_SECRET_PATTERNS), re.IGNORECASE)
    hits: Dict[str, List[str]] = {}
    for p in identity_dir.rglob("*"):
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if combined.search(line):
                hits.setdefault(p.name, []).append(f"L{lineno}: {line.strip()}")
    return hits


def test_T30_no_secrets_in_identity_outputs(env) -> None:
    data_dir, identity = env
    mod = _import_migrate()
    rc = mod.migrate(
        data_dir=data_dir,
        identity_dir=identity,
        do_backup=False,
        timestamp="2026-07-24T12:00:00+00:00",
    )
    assert rc == 0
    hits = _grep_identity_secrets(identity)
    assert hits == {}, (
        "P0 密钥零泄漏防线违规：identity/ 输出出现敏感字符串命中：\n"
        + "\n".join(f"  {f}: {matches}" for f, matches in hits.items())
    )


def test_T31_migration_script_does_not_read_env_or_credentials(tmp_path: Path) -> None:
    """静态扫描：migrate 脚本源码不 open API/.env、不 import provider credentials。"""

    src = MIGRATE_SCRIPT.read_text(encoding="utf-8")
    # 不允许 `API/.env` / `.env` 硬编码
    assert ".env" not in src, "migrate_legacy_semantics.py 出现 .env 引用"
    # 不允许 import provider 相关模块
    forbidden_imports = (
        "app.modules.provider",
        "app.adapters.provider",
        "provider_config_store",
        "api_key",
    )
    for pat in forbidden_imports:
        assert pat not in src, f"migrate_legacy_semantics.py 出现禁止引用: {pat}"


def test_T32_rollback_script_does_not_read_env_or_credentials() -> None:
    src = ROLLBACK_SCRIPT.read_text(encoding="utf-8")
    assert ".env" not in src
    assert "api_key" not in src.lower()
    assert "authorization" not in src.lower()


# ---------------------------------------------------------------------------
# T40-T49: byte-stable 输出（AST 硬护栏 · migration 侧代理指标）
# ---------------------------------------------------------------------------


def test_T40_output_bytes_stable_across_process(env) -> None:
    """第 1 次 vs 第 2 次运行 identity/ 字节 hash 完全相同。"""

    data_dir, identity = env
    fixed_ts = "2026-07-24T12:00:00+00:00"
    result1 = subprocess.run(
        [
            sys.executable,
            str(MIGRATE_SCRIPT),
            "--data-dir",
            str(data_dir),
            "--identity-dir",
            str(identity),
            "--no-backup",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=REPO_ROOT,
        env={
            **__import__("os").environ,
            # 让脚本使用固定时间戳需通过 module import 路径；子进程无注入点，
            # 因此用 idempotent 短路验证 byte 稳定性
        },
    )
    assert result1.returncode == 0
    h1 = _hash_dir(identity)
    result2 = subprocess.run(
        [
            sys.executable,
            str(MIGRATE_SCRIPT),
            "--data-dir",
            str(data_dir),
            "--identity-dir",
            str(identity),
            "--no-backup",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=REPO_ROOT,
    )
    assert result2.returncode == 0
    h2 = _hash_dir(identity)
    assert h1 == h2, "第 2 次运行应短路，identity 字节完全不变"


# ---------------------------------------------------------------------------
# T50-T59: GM-16 pre-flight（新符号 codegraph 复核 · 静态断言 module 结构）
# ---------------------------------------------------------------------------


def test_T50_legacy_mapper_exports_expected_symbols() -> None:
    from app.identity import legacy_mapper as lm

    for name in (
        "resolve_legacy_owner",
        "resolve_legacy_user_key",
        "fill_default_workspace_project",
        "DEFAULT_WORKSPACE_ID",
        "DEFAULT_PROJECT_ID",
    ):
        assert hasattr(lm, name), f"legacy_mapper 缺失预期符号: {name}"


def test_T51_migrate_script_exposes_key_helpers() -> None:
    mod = _import_migrate()
    for name in (
        "migrate",
        "scan_legacy_sources",
        "build_parser",
        "main",
        "_stable_alias_id",
    ):
        assert hasattr(mod, name), f"migrate_legacy_semantics 缺失函数: {name}"
