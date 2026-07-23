"""Prompt library store facade — 数据模型治理 PR-0 + PR-4 shadow 双读 + PR-8 主写分派 + PR-21 反转默认。

包裹 `main.py` 中提示词库 JSON 读写函数
`load_prompt_libraries` / `save_prompt_libraries`。
签名与原函数一一对应，仅做委派，不改行为。

**数据 PR-4**（Wave 3-C）：`load_prompt_libraries()` 在 JSON 读成功后惰性触发
`read_shadow()`；`SHADOW_READ_PROMPT_LIBRARY=false`（默认）时零开销 return。

**数据 PR-8**（Wave 3-G）：`save_prompt_libraries()` 按 `PROMPT_LIBRARY_PRIMARY_WRITE`
env 分派：
- `"json"`（显式回滚开关）→ 完全等价 PR-4 行为。**必须**保证不 import
  `app.db.prompt_library_writer`，不构造 DB engine，不落 fallback 文件。
- `"db"`（数据 PR-21 反转后默认 · Wave 3-N.5 主线 A）→
  `save_prompt_libraries_db` DB 主写 + JSON 异步回写。DB 主写失败上抛（不 fallback）。
  D-2=B 决策：整个 `{active_library_id, libraries: [...]}` payload 全塞
  `prompt_libraries.raw_json`；`prompt_items` 表 PR-8 不主写。

**数据 PR-21**（Wave 3-N.5 主线 A）：PromptLibrary 域 M1 收官反转默认。
`_get_primary_write_mode` 未设 env / 空 env → `"db"`（既往为 `"json"`）；
`save_prompt_libraries` 分派开关不变；仅 fallback 常量翻转（2 处单行）。

**回滚方式反转**：切回 PR-8 行为 = `export PROMPT_LIBRARY_PRIMARY_WRITE=json`
立即生效（fail-fast 值域校验保留 · 参照 canvas 域 PR-15 / project 域 PR-20 pattern）。
"""
from __future__ import annotations

from typing import Any

from .legacy_snapshot import SchemaVersion, build_snapshot, read_json_source


DOMAIN = "prompt_library"

_PRIMARY_WRITE_ALLOWED: frozenset[str] = frozenset({"json", "db"})


def _get_primary_write_mode(domain: str) -> str:
    """读 `PROMPT_LIBRARY_PRIMARY_WRITE` env（现读，不缓存）。"""

    if domain != DOMAIN:
        return "json"
    import os

    raw = os.environ.get("PROMPT_LIBRARY_PRIMARY_WRITE")
    if raw is None:
        return "db"
    value = str(raw).strip().lower()
    if not value:
        return "db"
    if value not in _PRIMARY_WRITE_ALLOWED:
        raise ValueError(
            f"Invalid PROMPT_LIBRARY_PRIMARY_WRITE {raw!r}; expected one of: "
            + ", ".join(sorted(_PRIMARY_WRITE_ALLOWED))
        )
    return value


def load_prompt_libraries(*args: Any, **kwargs: Any) -> Any:
    from main import load_prompt_libraries as _impl
    result = _impl(*args, **kwargs)
    read_shadow(result)
    return result


def save_prompt_libraries(*args: Any, **kwargs: Any) -> Any:
    """`save_prompt_libraries(data)` wrapper。

    - `PROMPT_LIBRARY_PRIMARY_WRITE=json`（默认）→ 老 `main.save_prompt_libraries`；
      **不 import** `app.db.prompt_library_writer`。返回归一化后的 payload
      （与老实现签名一致）。
    - `PROMPT_LIBRARY_PRIMARY_WRITE=db` → 先走 `main.normalize_prompt_libraries`
      + `updated_at=now_ms()` 复刻老实现的 normalize 语义（保持 `system/readonly/
      version` 字节等价），随后 `save_prompt_libraries_db` DB 主写 +
      `_async_write_json_fallback` 异步 JSON 回写。**不调用** `main.save_prompt_libraries`
      本身（否则 JSON 会被同步主写；违反"DB 是主写、JSON 是异步回退"契约）。
    """

    mode = _get_primary_write_mode(DOMAIN)
    if mode == "db":
        payload = _extract_payload(args, kwargs)
        if payload is None:
            from main import save_prompt_libraries as _impl

            return _impl(*args, **kwargs)
        # 懒 import：仅在 db 模式下才拉起 prompt_library_writer 命名空间。
        # 走 `main.normalize_prompt_libraries` 获得归一化后的 payload，
        # 保持 `system/readonly/version` 语义与老实现字节等价。**不调用**
        # `main.save_prompt_libraries`（会同步落 JSON，违反 DB 主写契约）。
        import main

        normalized = main.normalize_prompt_libraries(payload)
        normalized["updated_at"] = main.now_ms()

        from app.db.prompt_library_writer import (
            save_prompt_libraries_db,
            _async_write_json_fallback,
        )

        save_prompt_libraries_db(normalized)
        _async_write_json_fallback(normalized)
        return normalized

    # 默认 mode == "json"：完全等价 PR-4 行为。
    from main import save_prompt_libraries as _impl
    return _impl(*args, **kwargs)


def _extract_payload(args: tuple, kwargs: dict) -> dict | None:
    if args:
        candidate = args[0]
    else:
        candidate = kwargs.get("data")
    if isinstance(candidate, dict):
        return candidate
    return None


def read_shadow(json_snapshot: Any, *, request_id: str | None = None) -> None:
    """Shadow-read entry；`load_prompt_libraries` 读成功后调用。"""

    from app.shadow_read.runner import is_shadow_read_enabled, run_shadow_read

    if not is_shadow_read_enabled(DOMAIN):
        return
    run_shadow_read(DOMAIN, json_snapshot, request_id=request_id)


def snapshot() -> dict[str, Any]:
    from main import PROMPT_LIBRARY_PATH

    payload, raw_json = read_json_source(PROMPT_LIBRARY_PATH, {})
    return build_snapshot(
        payload,
        raw_json=raw_json,
        schema_version=SchemaVersion.PROMPT_LIBRARY,
        legacy_path=PROMPT_LIBRARY_PATH,
    )
