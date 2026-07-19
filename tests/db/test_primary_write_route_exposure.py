"""数据 PR-8 承接强化补丁 · `*_PRIMARY_WRITE` 不可通过 HTTP 修改契约。

承接 PR-8 Test Results Analyzer 观察项 P0-6:

`CANVAS_PRIMARY_WRITE` / `PROJECT_PRIMARY_WRITE` / `PROMPT_LIBRARY_PRIMARY_WRITE`
/ `WORKFLOW_DEFINITION_PRIMARY_WRITE` 是数据 M2 主写迁移的运维开关,严禁通过
HTTP body 修改;PR-7/PR-8 中"HTTP 不可修改"契约靠代码 shape(没有路由接受这类
字段)保证,无黑盒负测。本文件提供双层防线:

- **结构性防线**(未来加了 CRUD 路由也拦):枚举 `main.app.routes`,断言无变更
  方法(POST/PUT/PATCH/DELETE)的路由 path 或 body 参数名包含 `primary_write`。
- **黑盒负测**(已知 settings-adjacent 路由):`PATCH /api/storage-settings` /
  `PUT /api/providers` / `PUT /api/comfyui/instances` 各塞 `*_PRIMARY_WRITE`
  字段,断言 (a) 状态码不炸 (b) `main.*_PRIMARY_WRITE` 常量前后不变
  (c) `get_settings().*_primary_write` 前后不变。

**隔离契约**(P0):黑盒测试必须 monkeypatch 所有 settings-adjacent 路由会写
的真实文件路径到 tmp_path;必须 monkeypatch `sync_static_html_versions` 为
no-op,否则 TestClient `with` 触发 `on_event("startup")` 会写真实 `static/*.html`。
不加隔离会污染工作树。
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

FLAG_CONSTS = (
    "CANVAS_PRIMARY_WRITE",
    "PROJECT_PRIMARY_WRITE",
    "PROMPT_LIBRARY_PRIMARY_WRITE",
    "WORKFLOW_DEFINITION_PRIMARY_WRITE",
    "ASSET_LIBRARY_PRIMARY_WRITE",
)
FLAG_SETTINGS_FIELDS = tuple(f.lower() for f in FLAG_CONSTS)
FLAG_PATTERN = re.compile(r"primary_write", re.IGNORECASE)
MUTATE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


# ---------------------------------------------------------------------------
# 1. 结构性防线:未来加了 CRUD 路由也拦
# ---------------------------------------------------------------------------


def test_no_mutating_route_exposes_primary_write_switch() -> None:
    """枚举 `main.app.routes`,断言没有变更方法的路由 path 或 body 参数名
    包含 `primary_write`(case-insensitive)。

    结构性防御深度:未来若加了 `PATCH /api/config/*` 类新路由并意外让 body
    接受 `canvas_primary_write` 字段 → 本测试爆红。
    """

    import main

    offenders: list[str] = []
    for route in main.app.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = set(route.methods or [])
        if not (methods & MUTATE_METHODS):
            continue
        # path check
        if FLAG_PATTERN.search(route.path):
            offenders.append(f"path {sorted(methods)} {route.path}")
            continue
        # body params check (FastAPI 版本兼容,失败降级到 path-only)
        try:
            for param in route.dependant.body_params:
                if FLAG_PATTERN.search(param.name):
                    offenders.append(
                        f"body_param {sorted(methods)} {route.path}:{param.name}"
                    )
        except Exception:  # pragma: no cover — API 版本兼容兜底
            pass

    assert not offenders, (
        f"P0-6 契约破裂:变更方法的路由暴露了 *_PRIMARY_WRITE:{offenders}"
    )


# ---------------------------------------------------------------------------
# 2. 黑盒负测隔离 fixture:所有真实文件写入必须重定向到 tmp_path
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_settings_paths(tmp_path, monkeypatch):
    """把 settings-adjacent 路由会写的所有真实文件路径重定向到 tmp_path。

    settings-adjacent 路由触发的真实写入点:
    - `save_api_providers` 写 `main.API_PROVIDERS_FILE`(默认 `data/api_providers.json`)
    - `save_storage_settings` 写 `main.STORAGE_SETTINGS_FILE` + `makedirs` 目录
    - 相关路由可能触碰 `STATIC_RUNNINGHUB_API_PROVIDERS_FILE` / `API_ENV_FILE`

    另外必须 monkeypatch `sync_static_html_versions` 为 no-op —— TestClient
    `with` 块触发 `on_event("startup")` 会调用它,直接改写 `static/*.html`,
    污染工作树。
    """

    import main

    # 重定向所有真实文件到 tmp_path
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        main, "API_PROVIDERS_FILE", str(tmp_path / "api_providers.json")
    )
    monkeypatch.setattr(
        main, "STORAGE_SETTINGS_FILE", str(tmp_path / "storage_settings.json")
    )
    monkeypatch.setattr(
        main,
        "STATIC_RUNNINGHUB_API_PROVIDERS_FILE",
        str(tmp_path / "static_rh_api_providers.json"),
    )
    monkeypatch.setattr(main, "API_ENV_FILE", str(tmp_path / ".env"))

    # startup 事件里的 sync_static_html_versions 会写真实 static/*.html
    monkeypatch.setattr(main, "sync_static_html_versions", lambda: None)

    yield tmp_path


# ---------------------------------------------------------------------------
# 3. 黑盒负测:已知 settings-adjacent 路由塞 *_PRIMARY_WRITE 字段,验常量不变
# ---------------------------------------------------------------------------


def _snapshot_flags() -> dict[str, Any]:
    """当前 `main.*_PRIMARY_WRITE` 常量 + `get_settings().*_primary_write` 字段快照。"""

    import main

    from app.shared.settings import get_settings

    settings = get_settings()
    return {
        **{f"main.{name}": getattr(main, name, None) for name in FLAG_CONSTS},
        **{
            f"settings.{field}": getattr(settings, field, None)
            for field in FLAG_SETTINGS_FIELDS
        },
    }


@pytest.mark.parametrize(
    "method,path,body,label",
    [
        (
            "PATCH",
            "/api/storage-settings",
            {
                "upload": "custom/uploads",
                "canvas_primary_write": "db",
                "PROJECT_PRIMARY_WRITE": "db",
                "ASSET_LIBRARY_PRIMARY_WRITE": "db",
            },
            "storage_settings",
        ),
        (
            "PUT",
            "/api/providers",
            [
                {
                    "id": "test-provider",
                    "name": "Test",
                    "protocol": "openai",
                    "base_url": "https://example.com",
                    "canvas_primary_write": "db",
                    "PROMPT_LIBRARY_PRIMARY_WRITE": "db",
                }
            ],
            "providers",
        ),
        (
            "PUT",
            "/api/comfyui/instances",
            {
                "instances": [],
                "workflow_definition_primary_write": "db",
                "WORKFLOW_DEFINITION_PRIMARY_WRITE": "db",
                "asset_library_primary_write": "db",
                "ASSET_LIBRARY_PRIMARY_WRITE": "db",
            },
            "comfyui_instances",
        ),
    ],
    ids=["storage_settings", "providers", "comfyui_instances"],
)
def test_known_settings_routes_do_not_mutate_primary_write(
    isolated_settings_paths, method: str, path: str, body: Any, label: str
) -> None:
    """已知 settings-adjacent 路由收到 `*_PRIMARY_WRITE` 字段时:

    - 状态码 ∈ {200, 400, 401, 403, 422}(接受路由自身处理,不炸即可)
    - `main.*_PRIMARY_WRITE` 4 个常量前后完全不变
    - `get_settings().*_primary_write` 4 个字段前后完全不变

    通过 `isolated_settings_paths` fixture 隔离所有真实文件写入。
    """

    import main

    before = _snapshot_flags()
    with TestClient(main.app) as client:
        resp = client.request(method, path, json=body)

    assert resp.status_code in (200, 400, 401, 403, 422), (
        f"{label}:{method} {path} 返回 {resp.status_code},超出容忍范围;"
        f" body={resp.text[:200]}"
    )

    after = _snapshot_flags()
    assert before == after, (
        f"P0-6 契约破裂:{method} {path} 修改了 *_PRIMARY_WRITE;\n"
        f"  before = {before}\n"
        f"  after  = {after}"
    )
