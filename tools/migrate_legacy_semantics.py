"""Legacy semantics migration script — 权限 PR-2 承接（Wave 3-N.8 Batch 1 主线 A）。

对齐：
- [[40 实施计划/用户团队权限治理实施计划与PR清单]] PR-2 "弱语义承接"。
- [[50 决策记录/决策 - 主键类型]]（identity 全表 UUID + `legacy_owner_label`
  / `legacy_user_key`）。

任务
====

扫描以下 legacy JSON 数据源，将旧身份线索**影子写入** identity 表：

- `data/canvases/*.json` — `owner` / `x_user_id` 字段。
- `data/projects.json` — 分组 owner_label（若存在 `owner` / `owner_label`）。
- `data/conversations/<user_id>/` — 目录名派生 UserAlias（kind=conversation_dir）。
- `data/asset_library.json`（或 `data/asset_library/*.json` 兼容）— `owner`。
- `data/api_providers.json` — 若存在 owner 归属字段（治理期通常无此字段）。
- `data/history.json` — `user_key` 字段（若为对象 / 数组）。

产出
----

1. **`data/identity/user_aliases.json`** 追加 `UserAliasRecord` 条目
   （kind + legacy_user_key + workspace_id + created_at）；已存在同 (kind, key)
   条目则**跳过**（幂等）。
2. **`data/identity/auth_migration_state.json`**：
   - `legacy_mapping_completed_at` 写当前 ISO 时间戳；
   - `notes` 追加一条"由 migrate_legacy_semantics.py 于 <ts> 完成 legacy 承接"；
   - 幂等：读到 `legacy_mapping_completed_at != null` 直接 exit=0，不追加。
3. **影子归属清单** `data/identity/legacy_shadow_manifest.json`：
   记录每类资源的字段覆盖率与影子归属映射（`resource_type/resource_id →
   {workspace_id, project_id, legacy_owner_label}`）。不改原 JSON。
4. **对账 JSON** `data/identity/legacy_mapping_reconcile.json`：
   每类资源迁移前后记录数、字段覆盖率、alias 命中数。
5. **迁移前备份** `data.backup.<timestamp>/`（默认；`--no-backup` 关闭）：
   完整拷贝 `data/` → 备份路径，供 `tools/rollback_legacy_migration.py` 恢复。

约束
----

- **不删除任何旧字段**、**不改原 JSON 文件**（备份的目的是保证可回滚）。
- **不接入认证 / Session**（PR-3 承接）。
- **不读 API 目录下的 dotenv 文件**、**不读 provider credentials**（P0 密钥零泄漏防线）。
- **幂等**：第 2、3 次运行 identity JSON 与 auth_migration_state.notes 字节稳定。
- **原子替换**：稳定序列化（`ensure_ascii=False, indent=2, sort_keys=True` +
  尾随 `\n`），与 `JsonIdentityStore._write_json` / `migrate_identity_bootstrap.py`
  保持字节对齐。
- **零运行时依赖**：只用 stdlib。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# CB-P5-12 承接（identity PR-1 · Wave 3-M 主线 B）：Windows cp936 编码兜底。
if sys.platform == "win32":
    try:  # pragma: no cover — Windows-only defensive path
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "data"
DEFAULT_IDENTITY_DIR = DEFAULT_DATA_DIR / "identity"

SCHEMA_VERSION = 1

DEFAULT_WORKSPACE_ID = "ws-default-00000000-0000-0000-0000-000000000000"
DEFAULT_PROJECT_ID = "proj-default-00000000-0000-0000-0000-000000000000"

# ---------------------------------------------------------------------------
# 稳定 JSON I/O（与 migrate_identity_bootstrap.py / JsonIdentityStore 对齐）
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _read_json(p: Path) -> Any:
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json_atomic(p: Path, payload: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.write("\n")
    tmp.replace(p)


# ---------------------------------------------------------------------------
# 稳定 alias id 生成（幂等：相同 (kind, key) 生成相同 UUID）
# ---------------------------------------------------------------------------

_ALIAS_ID_NAMESPACE = "ic-legacy-alias-v1"


def _stable_alias_id(kind: str, legacy_user_key: str) -> str:
    """基于 (kind, legacy_user_key) 生成稳定的 UUID-like 字符串。

    使用 sha256 前 32 hex 拆成 8-4-4-4-12 段；同 (kind, key) 输入必然产出
    完全相同的 id，保证多次迁移的字节稳定性。
    """

    digest = hashlib.sha256(
        f"{_ALIAS_ID_NAMESPACE}:{kind}:{legacy_user_key}".encode("utf-8")
    ).hexdigest()[:32]
    return (
        f"alias-{digest[0:8]}-{digest[8:12]}-{digest[12:16]}-"
        f"{digest[16:20]}-{digest[20:32]}"
    )


# ---------------------------------------------------------------------------
# 数据源扫描
# ---------------------------------------------------------------------------


def _iter_canvas_files(canvas_dir: Path) -> List[Path]:
    if not canvas_dir.is_dir():
        return []
    return sorted(p for p in canvas_dir.iterdir() if p.suffix == ".json" and p.is_file())


def _iter_conversation_dirs(conv_dir: Path) -> List[Path]:
    if not conv_dir.is_dir():
        return []
    return sorted(p for p in conv_dir.iterdir() if p.is_dir())


def _safe_load_json(p: Path) -> Any:
    try:
        return _read_json(p)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def scan_legacy_sources(data_dir: Path) -> Dict[str, Any]:
    """扫描 data/ 下所有 legacy 数据源，返回聚合结果。

    返回结构：
    ```
    {
      "canvas_owners": [{resource_id, owner, x_user_id, path}],
      "conversation_dirs": [dir_name],
      "asset_owners": [{library_id, owner, path}],
      "projects_owner_labels": [{project_id, owner_label}],
      "provider_owners": [{provider_id, owner}],
      "history_user_keys": [user_key],
      "counts": {resource_type: total_records},
    }
    ```
    """

    canvas_dir = data_dir / "canvases"
    conv_dir = data_dir / "conversations"
    projects_file = data_dir / "projects.json"
    asset_library_file = data_dir / "asset_library.json"
    asset_library_dir = data_dir / "asset_library"
    api_providers_file = data_dir / "api_providers.json"
    history_file = data_dir / "history.json"

    canvas_owners: List[Dict[str, Any]] = []
    for cp in _iter_canvas_files(canvas_dir):
        payload = _safe_load_json(cp)
        if not isinstance(payload, dict):
            continue
        canvas_owners.append(
            {
                "resource_id": payload.get("id") or cp.stem,
                "owner": payload.get("owner"),
                "x_user_id": payload.get("x_user_id"),
                "path": str(cp.relative_to(data_dir)).replace("\\", "/"),
            }
        )

    conversation_dirs: List[str] = [p.name for p in _iter_conversation_dirs(conv_dir)]

    projects_owner_labels: List[Dict[str, Any]] = []
    if projects_file.is_file():
        payload = _safe_load_json(projects_file)
        # 兼容多种结构：list of projects / {"projects": [...]} / dict of groups
        candidates: List[Any] = []
        if isinstance(payload, list):
            candidates = payload
        elif isinstance(payload, dict):
            if isinstance(payload.get("projects"), list):
                candidates = payload["projects"]
            else:
                candidates = list(payload.values())
        for item in candidates:
            if not isinstance(item, dict):
                continue
            label = item.get("owner_label") or item.get("owner")
            if label is None:
                continue
            projects_owner_labels.append(
                {
                    "project_id": item.get("id") or item.get("project_id"),
                    "owner_label": label,
                }
            )

    asset_owners: List[Dict[str, Any]] = []
    if asset_library_file.is_file():
        payload = _safe_load_json(asset_library_file)
        if isinstance(payload, dict):
            libs = payload.get("libraries")
            if isinstance(libs, list):
                for lib in libs:
                    if isinstance(lib, dict) and lib.get("owner"):
                        asset_owners.append(
                            {
                                "library_id": lib.get("id"),
                                "owner": lib.get("owner"),
                                "path": "asset_library.json",
                            }
                        )
    if asset_library_dir.is_dir():
        for ap in sorted(asset_library_dir.iterdir()):
            if ap.suffix != ".json" or not ap.is_file():
                continue
            payload = _safe_load_json(ap)
            if isinstance(payload, dict) and payload.get("owner"):
                asset_owners.append(
                    {
                        "library_id": payload.get("id") or ap.stem,
                        "owner": payload.get("owner"),
                        "path": str(ap.relative_to(data_dir)).replace("\\", "/"),
                    }
                )

    provider_owners: List[Dict[str, Any]] = []
    if api_providers_file.is_file():
        payload = _safe_load_json(api_providers_file)
        candidates2: List[Any] = []
        if isinstance(payload, list):
            candidates2 = payload
        elif isinstance(payload, dict) and isinstance(payload.get("providers"), list):
            candidates2 = payload["providers"]
        for item in candidates2:
            if not isinstance(item, dict):
                continue
            owner = item.get("owner")
            if owner is None:
                continue
            provider_owners.append(
                {
                    "provider_id": item.get("id") or item.get("provider_id"),
                    "owner": owner,
                }
            )

    history_user_keys: List[str] = []
    if history_file.is_file():
        payload = _safe_load_json(history_file)
        # 兼容两种结构：list of entries or dict keyed by user_key
        if isinstance(payload, list):
            for entry in payload:
                if isinstance(entry, dict) and entry.get("user_key"):
                    history_user_keys.append(str(entry["user_key"]))
        elif isinstance(payload, dict):
            for k in payload.keys():
                # 顶层 key 可能就是 user_key（旧结构 {"<user_key>": [entries...]}）
                if isinstance(k, str) and k not in ("history", "entries"):
                    history_user_keys.append(k)

    counts = {
        "canvas": len(canvas_owners),
        "conversation_dir": len(conversation_dirs),
        "asset_library": len(asset_owners),
        "project": len(projects_owner_labels),
        "provider": len(provider_owners),
        "history": len(history_user_keys),
    }

    return {
        "canvas_owners": canvas_owners,
        "conversation_dirs": conversation_dirs,
        "asset_owners": asset_owners,
        "projects_owner_labels": projects_owner_labels,
        "provider_owners": provider_owners,
        "history_user_keys": history_user_keys,
        "counts": counts,
    }


# ---------------------------------------------------------------------------
# UserAlias 构造
# ---------------------------------------------------------------------------


def _aliases_from_scan(
    scan: Dict[str, Any],
    *,
    workspace_id: str,
    created_at: str,
) -> List[Dict[str, Any]]:
    """把扫描结果转成候选 UserAliasRecord 列表（去重、稳定排序）。

    去重规则：以 `(kind, legacy_user_key)` 唯一。
    """

    seen: set[Tuple[str, str]] = set()
    aliases: List[Dict[str, Any]] = []

    def _add(kind: str, key: Optional[Any]) -> None:
        if key is None:
            return
        text = str(key).strip()
        if not text:
            return
        pair = (kind, text)
        if pair in seen:
            return
        seen.add(pair)
        aliases.append(
            {
                "id": _stable_alias_id(kind, text),
                "user_id": None,
                "kind": kind,
                "legacy_user_key": text,
                "workspace_id": workspace_id,
                "created_at": created_at,
            }
        )

    # x_user_id：canvases + history
    for c in scan["canvas_owners"]:
        _add("x_user_id", c.get("x_user_id"))
    for k in scan["history_user_keys"]:
        _add("x_user_id", k)

    # conversation_dir：目录名
    for name in scan["conversation_dirs"]:
        _add("conversation_dir", name)

    # cookie_user：owner 字符串（画布 / 素材 / 项目 / provider）
    for c in scan["canvas_owners"]:
        _add("cookie_user", c.get("owner"))
    for a in scan["asset_owners"]:
        _add("cookie_user", a.get("owner"))
    for p in scan["projects_owner_labels"]:
        _add("cookie_user", p.get("owner_label"))
    for p in scan["provider_owners"]:
        _add("cookie_user", p.get("owner"))

    # 稳定输出：按 (kind, legacy_user_key) 排序，与 sort_keys=True 的字节稳定契约相容。
    aliases.sort(key=lambda a: (a["kind"], a["legacy_user_key"]))
    return aliases


# ---------------------------------------------------------------------------
# 影子归属 / 对账
# ---------------------------------------------------------------------------


def _build_shadow_manifest(
    scan: Dict[str, Any],
    *,
    workspace_id: str,
    project_id: str,
) -> Dict[str, Any]:
    """每类资源生成影子归属映射（不改原 JSON）。"""

    def _entry(
        resource_type: str, resource_id: Any, legacy_owner_label: Any
    ) -> Dict[str, Any]:
        return {
            "resource_type": resource_type,
            "resource_id": None if resource_id is None else str(resource_id),
            "workspace_id": workspace_id,
            "project_id": project_id,
            "legacy_owner_label": (
                None
                if legacy_owner_label is None
                else str(legacy_owner_label)
            ),
        }

    shadow: List[Dict[str, Any]] = []
    for c in scan["canvas_owners"]:
        shadow.append(
            _entry(
                "canvas",
                c.get("resource_id"),
                c.get("owner") or c.get("x_user_id"),
            )
        )
    for a in scan["asset_owners"]:
        shadow.append(_entry("asset_library", a.get("library_id"), a.get("owner")))
    for p in scan["projects_owner_labels"]:
        shadow.append(
            _entry("project", p.get("project_id"), p.get("owner_label"))
        )
    for p in scan["provider_owners"]:
        shadow.append(_entry("provider", p.get("provider_id"), p.get("owner")))
    for name in scan["conversation_dirs"]:
        shadow.append(_entry("conversation_dir", name, name))

    # 稳定排序
    shadow.sort(
        key=lambda s: (
            s["resource_type"],
            s["resource_id"] or "",
            s["legacy_owner_label"] or "",
        )
    )
    return {"_schema_version": SCHEMA_VERSION, "entries": shadow}


def _field_coverage(scan: Dict[str, Any]) -> Dict[str, Any]:
    """字段覆盖率：每类资源"有 owner/x_user_id 的记录数 / 总记录数"。"""

    canvas_total = len(scan["canvas_owners"])
    canvas_with_owner = sum(1 for c in scan["canvas_owners"] if c.get("owner"))
    canvas_with_xuid = sum(1 for c in scan["canvas_owners"] if c.get("x_user_id"))
    asset_total = len(scan["asset_owners"])
    project_total = len(scan["projects_owner_labels"])
    provider_total = len(scan["provider_owners"])
    history_total = len(scan["history_user_keys"])
    conversation_total = len(scan["conversation_dirs"])

    def _ratio(num: int, denom: int) -> float:
        if denom == 0:
            return 1.0
        return round(num / denom, 4)

    return {
        "canvas_total": canvas_total,
        "canvas_owner_coverage": _ratio(canvas_with_owner, canvas_total),
        "canvas_x_user_id_coverage": _ratio(canvas_with_xuid, canvas_total),
        "asset_library_total": asset_total,
        "project_total": project_total,
        "provider_total": provider_total,
        "history_total": history_total,
        "conversation_dir_total": conversation_total,
    }


# ---------------------------------------------------------------------------
# 备份 / 迁移主流程
# ---------------------------------------------------------------------------


_BACKUP_PREFIX = "data.backup."


def _make_backup(data_dir: Path, backup_root: Path, ts_slug: str) -> Path:
    """把 data/ 完整拷贝到 backup_root / (data.backup.<ts_slug>)。"""

    dest = backup_root / f"{_BACKUP_PREFIX}{ts_slug}"
    if dest.exists():
        raise FileExistsError(f"备份目录已存在：{dest}")
    shutil.copytree(data_dir, dest, symlinks=False)
    return dest


def _merge_aliases(
    existing: List[Dict[str, Any]],
    new_candidates: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], int]:
    """把 new_candidates 合入 existing；(kind, legacy_user_key) 去重。

    返回 (合并后列表, 新增条数)。已存在项**不覆盖**（保留原 user_id、
    workspace_id、created_at；本 PR 不做二次分配）。
    """

    index: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for a in existing:
        kind = str(a.get("kind") or "")
        key = str(a.get("legacy_user_key") or "")
        if kind and key:
            index[(kind, key)] = a
    added = 0
    for cand in new_candidates:
        pair = (str(cand["kind"]), str(cand["legacy_user_key"]))
        if pair in index:
            continue
        index[pair] = cand
        added += 1
    merged = list(index.values())
    merged.sort(key=lambda a: (str(a.get("kind")), str(a.get("legacy_user_key"))))
    return merged, added


def migrate(
    data_dir: Path,
    identity_dir: Path,
    *,
    dry_run: bool = False,
    do_backup: bool = True,
    backup_root: Optional[Path] = None,
    timestamp: Optional[str] = None,
) -> int:
    """幂等迁移入口。

    - `timestamp` 用于测试注入固定 ISO 字符串；生产运行取当前时间。
    - `backup_root` 默认与 `data_dir` 同级（`data_dir.parent`）。
    """

    if not data_dir.is_dir():
        print(f"[migrate-legacy] ERROR: data-dir 不存在：{data_dir}", file=sys.stderr)
        return 2
    if not identity_dir.is_dir():
        print(
            f"[migrate-legacy] ERROR: identity-dir 不存在：{identity_dir}",
            file=sys.stderr,
        )
        return 2

    state_file = identity_dir / "auth_migration_state.json"
    aliases_file = identity_dir / "user_aliases.json"
    manifest_file = identity_dir / "legacy_shadow_manifest.json"
    reconcile_file = identity_dir / "legacy_mapping_reconcile.json"

    if not state_file.is_file() or not aliases_file.is_file():
        print(
            "[migrate-legacy] ERROR: identity 基础 JSON 缺失（先跑 "
            "migrate_identity_bootstrap.py）",
            file=sys.stderr,
        )
        return 2

    state = _read_json(state_file)
    if not isinstance(state, dict) or state.get("_schema_version") != SCHEMA_VERSION:
        print(
            "[migrate-legacy] ERROR: auth_migration_state.json _schema_version 不匹配",
            file=sys.stderr,
        )
        return 2

    # 幂等短路：已完成则 exit=0，不改任何文件（notes 不追加）
    if state.get("legacy_mapping_completed_at"):
        print(
            "[migrate-legacy] 已完成（legacy_mapping_completed_at="
            f"{state['legacy_mapping_completed_at']!r}）；exit=0，无任何写入。"
        )
        return 0

    ts = timestamp or _now_iso()
    ts_slug = ts.replace(":", "").replace("+", "p").replace("-", "")

    # ---- 扫描 ----
    scan = scan_legacy_sources(data_dir)

    # ---- 构造 alias 候选 ----
    candidates = _aliases_from_scan(
        scan, workspace_id=DEFAULT_WORKSPACE_ID, created_at=ts
    )

    aliases_payload = _read_json(aliases_file)
    if not isinstance(aliases_payload, dict) or not isinstance(
        aliases_payload.get("aliases"), list
    ):
        print(
            "[migrate-legacy] ERROR: user_aliases.json 结构异常",
            file=sys.stderr,
        )
        return 2
    existing_aliases: List[Dict[str, Any]] = list(aliases_payload["aliases"])
    merged_aliases, added = _merge_aliases(existing_aliases, candidates)
    new_aliases_payload = {
        "_schema_version": SCHEMA_VERSION,
        "aliases": merged_aliases,
    }

    # ---- 影子归属清单 + 对账 ----
    manifest = _build_shadow_manifest(
        scan, workspace_id=DEFAULT_WORKSPACE_ID, project_id=DEFAULT_PROJECT_ID
    )
    coverage = _field_coverage(scan)
    reconcile = {
        "_schema_version": SCHEMA_VERSION,
        "generated_at": ts,
        "counts_before": scan["counts"],
        "counts_after": scan["counts"],  # 迁移不改原 JSON，前后计数一致
        "field_coverage": coverage,
        "aliases_added": added,
        "aliases_total_after": len(merged_aliases),
        "shadow_manifest_entries": len(manifest["entries"]),
    }

    new_state = {
        "_schema_version": SCHEMA_VERSION,
        "bootstrap_completed_at": state.get("bootstrap_completed_at"),
        "legacy_mapping_completed_at": ts,
        "notes": list(state.get("notes", []))
        + [f"由 migrate_legacy_semantics.py 于 {ts} 完成 legacy 承接"],
    }

    if dry_run:
        print("[migrate-legacy] --dry-run：以下变更将写入 identity/，但不落盘。")
        print(json.dumps(reconcile, ensure_ascii=False, indent=2, sort_keys=True))
        print(f"[dry-run] aliases 将新增 {added} 条，合并后共 {len(merged_aliases)} 条。")
        return 0

    # ---- 备份（在任何写入前） ----
    backup_dir_path: Optional[Path] = None
    if do_backup:
        root = backup_root or data_dir.parent
        try:
            backup_dir_path = _make_backup(data_dir, root, ts_slug)
        except FileExistsError as exc:
            print(f"[migrate-legacy] ERROR: {exc}", file=sys.stderr)
            return 3
        except OSError as exc:
            print(
                f"[migrate-legacy] ERROR: 备份失败 ({exc})；未做任何写入，安全退出。",
                file=sys.stderr,
            )
            return 3

    # ---- 落盘（原子写） ----
    _write_json_atomic(aliases_file, new_aliases_payload)
    _write_json_atomic(manifest_file, manifest)
    _write_json_atomic(reconcile_file, reconcile)
    _write_json_atomic(state_file, new_state)

    print(
        f"[migrate-legacy] OK: aliases +{added} → {len(merged_aliases)}；"
        f"shadow_entries={len(manifest['entries'])}；"
        f"legacy_mapping_completed_at={ts!r}。"
    )
    if backup_dir_path is not None:
        print(f"[migrate-legacy] backup: {backup_dir_path}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="migrate_legacy_semantics",
        description=(
            "Legacy semantics 迁移脚本（权限 PR-2，幂等 · 不删旧字段 · "
            "先备份 data/ 再落盘）。"
        ),
    )
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help=f"数据目录（默认 {DEFAULT_DATA_DIR}）",
    )
    parser.add_argument(
        "--identity-dir",
        default=str(DEFAULT_IDENTITY_DIR),
        help=f"identity 数据目录（默认 {DEFAULT_IDENTITY_DIR}）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印对账信息，不落盘、不备份。",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="跳过 data.backup.<ts>/ 备份（仅测试用；生产环境请勿使用）。",
    )
    parser.add_argument(
        "--backup-root",
        default=None,
        help="备份根目录（默认 data-dir 的父目录）。",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = Path(args.data_dir).resolve()
    identity_dir = Path(args.identity_dir).resolve()
    backup_root = Path(args.backup_root).resolve() if args.backup_root else None
    return migrate(
        data_dir=data_dir,
        identity_dir=identity_dir,
        dry_run=args.dry_run,
        do_backup=not args.no_backup,
        backup_root=backup_root,
    )


if __name__ == "__main__":
    sys.exit(main())
