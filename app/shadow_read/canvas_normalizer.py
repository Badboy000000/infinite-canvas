"""`app.shadow_read.canvas_normalizer` — 数据 PR-15 · CB-P5-08b 承接。

Canvas 域 shadow_read diff 语义在 PR-5 起就存在**结构非对称**观察项
（CB-P5-08b）：`load_canvas(canvas_id)` 单-id 加载，`_normalize_json_canvas`
只返回该 id 的 JSON snapshot；但 `_load_db_snapshot("canvas")` 会读整表
返回所有 canvas。当 `_compare_snapshots` 直接对集合差集时，DB 里其它所有
canvas 都会进 `missing_in_json`，长期开启 `SHADOW_READ_CANVAS=true` 会持续
产生**假 missing 记录**污染 `data/shadow_diff/canvas/*.jsonl`。

数据 PR-15 内嵌承接 CB-P5-08b 的修法：**单-id load 路径只对该 id 判定**，
不 O(N) 扫描其它 canvas。

- `normalize_json_canvas(payload)` — 与原 `_normalize_json_canvas` 相同签名
  与语义（保留字节等价），供 runner 分派使用。
- `scope_db_snapshot_to_json(json_snapshot, db_snapshot)` — 在 canvas 域下把
  DB snapshot 收敛到 JSON snapshot 覆盖的 legacy_id 集合内。这样：
  * `missing_in_db` = JSON 有但 DB 没有的 legacy_id（=0 或 1）；
  * `missing_in_json` = 收敛后差集，语义上"只在这一次 load 看到的 id 上判定"，
    不再把 DB 里其它 canvas 视为噪声。
  * `field_diffs` 只覆盖交集（即 json_snapshot 中的 id）。

**契约**：本模块只关心 diff 语义，不改门禁、不改 DB engine 构造、不改字段
稳定集；对齐 `app/shadow_read/runner.py` 的失败隔离与延迟上限（P95 ≤ 20ms）。

关联：

- [[70 开发过程跟踪/缺陷追踪/CB-P5-08b - shadow_read canvas normalizer 结构非对称]]
- [[40 实施计划/数据模型治理实施计划与PR清单#PR-15 canvas 域 M1 反转默认]]
"""

from __future__ import annotations

from typing import Any, Mapping


def normalize_json_canvas(payload: Any) -> dict[str, dict[str, Any]]:
    """`load_canvas()` 返回单个 canvas dict；映射 `project` → `project_legacy_id`，
    `owner` → `owner_label` 以对齐 DB 表列名。

    与 `runner._normalize_json_canvas` 保持字节等价，作为 PR-15 内嵌承接
    重构的迁移入口（后续可将 runner 内的函数改为对本函数的薄包装）。
    """

    if not isinstance(payload, dict):
        return {}
    legacy_id = payload.get("id")
    if not legacy_id:
        return {}
    return {
        str(legacy_id): {
            "id": payload.get("id"),
            "title": payload.get("title"),
            "kind": payload.get("kind"),
            "project_legacy_id": payload.get("project"),
            "owner_label": payload.get("owner"),
            "pinned": bool(payload.get("pinned", False)),
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
            "deleted_at": payload.get("deleted_at"),
            "revision": payload.get("revision", 0),
            "base_updated_at": payload.get("base_updated_at"),
        }
    }


def scope_db_snapshot_to_json(
    json_snapshot: Mapping[str, dict[str, Any]],
    db_snapshot: Mapping[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """把 DB snapshot 收敛到 JSON snapshot 覆盖的 legacy_id 集合内。

    - `json_snapshot` 为空 → 返回空 dict（`load_canvas` 极端场景 · payload 无 id
      / 类型异常时，本函数不越界）。
    - `json_snapshot` 非空 → 只保留 DB 中同一批 legacy_id 的记录。

    调用方在 canvas 域下用本函数的返回值替换原 db_snapshot 传给
    `_compare_snapshots`，从而消除 O(N) 假 missing 噪声。
    """

    if not json_snapshot:
        return {}
    scope: set[str] = {str(k) for k in json_snapshot.keys()}
    return {str(k): v for k, v in db_snapshot.items() if str(k) in scope}


__all__ = [
    "normalize_json_canvas",
    "scope_db_snapshot_to_json",
]
