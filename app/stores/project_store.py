"""Project store facade — 数据模型治理 PR-0 + PR-4 shadow 双读 + PR-8 主写分派 + PR-20 反转默认。

包裹 `main.py` 中项目列表 JSON 读写函数 `load_projects` / `save_projects`。
签名与原函数一一对应，仅做委派，不改行为。

**数据 PR-4**（Wave 3-C）：`load_projects()` 在 JSON 读成功后惰性触发
`read_shadow()`；`SHADOW_READ_PROJECT=false`（默认）时零开销直接 return，
不 import DB 层、不构造 engine、不落盘任何 diff 文件。

**数据 PR-8**（Wave 3-G）：`save_projects()` 按 `PROJECT_PRIMARY_WRITE` env
分派：
- `"json"`（显式回滚开关）→ 完全等价 PR-4 行为（老 JSON 主写；shadow read 由
  `load_projects` 独立触发）。**必须**保证不 import `app.db.project_writer`，
  不构造 DB engine，不落任何 fallback 文件（P0 硬约束 #3）。
- `"db"`（数据 PR-20 反转后默认 · Wave 3-N.5 主线 B）→
  `app.db.project_writer.save_projects_db` DB 主写 + JSON 异步回写。
  DB 主写失败上抛（不 fallback 到 JSON 主写；P0 硬约束 #4）。

**数据 PR-20**（Wave 3-N.5 主线 B）：Project 域 M1 收官反转默认。
`_get_primary_write_mode` 未设 env / 空 env → `"db"`（既往为 `"json"`）；
`save_projects` 分派开关不变；仅 fallback 常量翻转（2 处单行 + AST 断言
zero-diff 于其余部分 · T255 覆盖）。

**回滚方式反转**：切回 PR-8 行为 = `export PROJECT_PRIMARY_WRITE=json`
立即生效（fail-fast 值域校验保留 · 参照 canvas 域 PR-15 pattern）。
"""
from __future__ import annotations

from typing import Any

from .legacy_snapshot import SchemaVersion, build_snapshot, read_json_source


DOMAIN = "project"

# 数据 PR-8 允许值域（其他值 fail-fast）。
_PRIMARY_WRITE_ALLOWED: frozenset[str] = frozenset({"json", "db"})


def _get_primary_write_mode(domain: str) -> str:
    """读 `PROJECT_PRIMARY_WRITE` env（现读，不缓存）。"""

    if domain != DOMAIN:
        return "json"
    import os

    raw = os.environ.get("PROJECT_PRIMARY_WRITE")
    if raw is None:
        return "db"
    value = str(raw).strip().lower()
    if not value:
        return "db"
    if value not in _PRIMARY_WRITE_ALLOWED:
        raise ValueError(
            f"Invalid PROJECT_PRIMARY_WRITE {raw!r}; expected one of: "
            + ", ".join(sorted(_PRIMARY_WRITE_ALLOWED))
        )
    return value


def load_projects(*args: Any, **kwargs: Any) -> Any:
    from main import load_projects as _impl
    result = _impl(*args, **kwargs)
    # 数据 PR-4 shadow read hook；env 关闭时零开销 return。
    read_shadow(result)
    return result


def save_projects(*args: Any, **kwargs: Any) -> Any:
    """`save_projects(projects)` wrapper。

    - `PROJECT_PRIMARY_WRITE=json`（默认）→ 老 `main.save_projects`；
      **不 import** `app.db.project_writer`。
    - `PROJECT_PRIMARY_WRITE=db` → `save_projects_db` DB 主写 + JSON 异步回写。
    """

    mode = _get_primary_write_mode(DOMAIN)
    if mode == "db":
        projects = _extract_projects(args, kwargs)
        if projects is None:
            # 非 list 传入：走老 impl 让它自己抛错（保持既有语义）。
            from main import save_projects as _impl

            return _impl(*args, **kwargs)
        # 懒 import：仅在 db 模式下才拉起 project_writer 命名空间。
        from app.db.project_writer import (
            save_projects_db,
            _async_write_json_fallback,
        )

        save_projects_db(projects)
        _async_write_json_fallback(projects)
        return None

    # 默认 mode == "json"：完全等价 PR-4 行为。
    from main import save_projects as _impl
    return _impl(*args, **kwargs)


def _extract_projects(args: tuple, kwargs: dict) -> list[dict] | None:
    """把 `save_projects(projects)` 的位置/关键字参数还原为 list。"""

    if args:
        candidate = args[0]
    else:
        candidate = kwargs.get("projects")
    if isinstance(candidate, list):
        return candidate
    return None


def read_shadow(json_snapshot: Any, *, request_id: str | None = None) -> None:
    """Shadow-read entry；JSON 主读成功后调用。

    - 门禁：`SHADOW_READ_PROJECT` env truthy 才继续。
    - 结果永不进入 HTTP 响应；只影响 `data/shadow_diff/project/*.jsonl` 落盘。
    - 失败隔离：任何异常仅记 warning。
    """

    # 零开销 short-circuit：只 import runner 命名空间，不触发 DB 层。
    from app.shadow_read.runner import is_shadow_read_enabled, run_shadow_read

    if not is_shadow_read_enabled(DOMAIN):
        return
    run_shadow_read(DOMAIN, json_snapshot, request_id=request_id)


def snapshot() -> dict[str, Any]:
    from main import PROJECTS_PATH

    payload, raw_json = read_json_source(PROJECTS_PATH, [])
    return build_snapshot(
        payload,
        raw_json=raw_json,
        schema_version=SchemaVersion.PROJECT,
        legacy_path=PROJECTS_PATH,
    )
