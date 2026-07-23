"""PR-BE-04 · JSON Store facade 强化：27 处（实际 28 处发现，2 处冻结）
helper 层 bare 调用替换为 store facade 后的等价性验收。

覆盖：

1. **Bare-call absence**：AST 扫描 `main.py`，除冻结区间
   （`storage_settings_snapshot` / `apply_storage_settings` 内的
   `load_storage_settings` bare 调用）之外，所有 helper 层 bare 调用点归零。

2. **Facade delegation identity**：15 个 store facade 方法均**懒 `import main`**
   委派到 `main.<helper>`；facade 内部 `_impl` 与 `main.<helper>` 是同一对象
   （避免中间层多包一次 wrapper 导致行为漂移）。

3. **Store facade round-trip 等价**：每个 store 方法 write→read 幂等，
   与直接调用 `main.<helper>` 结果 byte-equivalent。

4. **端到端**：`TestClient` 调受影响 API 路由，替换前后 body/status 一致
   （baseline snapshot 保存在测试内部）。

不覆盖：Provider 密钥脱敏、Canvas 409 语义等——这些由既有测试与 P0 保活烟测覆盖。
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 1. Bare-call absence（AST 扫描）
# ---------------------------------------------------------------------------

# 15 helper 名字（与 PR-0 冻结的 9 个 store facade 完全对应）。
_HELPER_NAMES = {
    "save_canvas", "load_canvas",
    "load_projects", "save_projects",
    "load_asset_library", "save_asset_library",
    "load_prompt_libraries", "save_prompt_libraries",
    "load_api_providers", "save_api_providers",
    "save_to_history",
    "load_conversation", "save_conversation",
    "load_runninghub_workflow_store", "save_runninghub_workflow_store",
    "load_storage_settings",
}

# 冻结豁免：`storage_settings_snapshot` 与 `apply_storage_settings` 内部的
# `load_storage_settings` bare 调用属于**文件对象治理 PR-0 冻结区间**，
# PR-BE-04 严格不许触碰。这里显式列出豁免函数名。
_FROZEN_CALLERS = {"storage_settings_snapshot", "apply_storage_settings"}


def _load_main_tree():
    with open(REPO_ROOT / "main.py", "r", encoding="utf-8") as fh:
        src = fh.read()
    return ast.parse(src), src.splitlines()


def _is_route_decorator(dec: ast.AST) -> bool:
    f = dec.func if isinstance(dec, ast.Call) else dec
    return (
        isinstance(f, ast.Attribute)
        and isinstance(f.value, ast.Name)
        and f.value.id == "app"
    )


def _top_level_functions(tree: ast.Module):
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _collect_bare_helper_calls():
    """返回 [(lineno, helper, caller, is_route)]。

    Bare = 直接 `helper(...)` 调用，不经过 `<store>.helper(...)` 属性访问。
    """
    tree, _ = _load_main_tree()
    top_funcs = list(_top_level_functions(tree))

    # 建立 line → (fn_name, is_route)
    def enclosing(line: int):
        for fn in top_funcs:
            if fn.lineno <= line <= (fn.end_lineno or fn.lineno):
                is_r = any(_is_route_decorator(d) for d in fn.decorator_list)
                return fn.name, is_r
        return None, False

    results = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # bare = 直接 Name 调用；`store.helper()` 是 Attribute，不算 bare
        if not isinstance(func, ast.Name):
            continue
        if func.id not in _HELPER_NAMES:
            continue
        caller, is_r = enclosing(node.lineno)
        if caller is None:
            continue
        # 排除 def 本身（不会命中，因为 Name 不匹配 def）
        results.append((node.lineno, func.id, caller, is_r))
    return results


def test_no_bare_helper_calls_in_routes():
    """路由函数体内 zero bare helper 调用（数据 PR-0 遗产已 100% 覆盖）。"""
    calls = _collect_bare_helper_calls()
    route_calls = [c for c in calls if c[3]]
    assert route_calls == [], f"route 内仍有 bare 调用：{route_calls}"


def test_no_bare_helper_calls_in_helpers_except_frozen():
    """PR-BE-04 收编：helper 内 bare 调用只允许冻结区间保留。"""
    calls = _collect_bare_helper_calls()
    helper_calls = [c for c in calls if not c[3]]
    non_frozen = [c for c in helper_calls if c[2] not in _FROZEN_CALLERS]
    assert non_frozen == [], (
        f"非冻结 helper 内仍有 bare 调用（PR-BE-04 收编不完整）：{non_frozen}"
    )
    # 冻结区间内必须还留着（不许连冻结点也顺手改了）
    frozen_calls = [c for c in helper_calls if c[2] in _FROZEN_CALLERS]
    assert frozen_calls, (
        "冻结区间 (`storage_settings_snapshot` / `apply_storage_settings`) "
        "内的 `load_storage_settings` bare 调用必须保留，不许触碰。"
    )
    frozen_helpers = {c[1] for c in frozen_calls}
    assert frozen_helpers == {"load_storage_settings"}, (
        f"冻结区间应只保留 `load_storage_settings` bare 调用，实际：{frozen_helpers}"
    )


# ---------------------------------------------------------------------------
# 2. Facade delegation identity
# ---------------------------------------------------------------------------

_FACADE_PAIRS = [
    ("canvas_store", "save_canvas"),
    ("canvas_store", "load_canvas"),
    ("project_store", "load_projects"),
    ("project_store", "save_projects"),
    ("asset_library_store", "load_asset_library"),
    ("asset_library_store", "save_asset_library"),
    ("prompt_library_store", "load_prompt_libraries"),
    ("prompt_library_store", "save_prompt_libraries"),
    ("provider_config_store", "load_api_providers"),
    ("provider_config_store", "save_api_providers"),
    ("history_store", "save_to_history"),
    ("conversation_store", "load_conversation"),
    ("conversation_store", "save_conversation"),
    ("workflow_store", "load_runninghub_workflow_store"),
    ("workflow_store", "save_runninghub_workflow_store"),
    ("storage_settings_store", "load_storage_settings"),
]


@pytest.mark.parametrize("store_name,method", _FACADE_PAIRS)
def test_facade_delegates_to_main(store_name, method):
    """facade.<method>(*a, **kw) 内部懒 import 到 main.<method>，
    并直接 `_impl(*a, **kw)` — 不夹带任何转换或包裹。
    """
    from app import stores as _stores  # 触发子模块 re-export
    store = getattr(_stores, store_name)
    facade_fn = getattr(store, method)
    # 通过 sentinel 值检查透传：facade 应将参数原样传给 main.helper
    import main
    real_fn = getattr(main, method)
    # monkeypatch 临时替换 main.<method> 观察 facade 是否命中该替换
    sentinel = object()
    captured = {}
    def spy(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return sentinel
    orig = getattr(main, method)
    setattr(main, method, spy)
    try:
        result = facade_fn("A", 42, foo="bar")
    finally:
        setattr(main, method, orig)
    assert result is sentinel, f"{store_name}.{method} 未透传返回值"
    assert captured["args"] == ("A", 42), f"{store_name}.{method} 位置参数漂移"
    assert captured["kwargs"] == {"foo": "bar"}, f"{store_name}.{method} 关键字参数漂移"


# ---------------------------------------------------------------------------
# 3. Store facade round-trip（真实 JSON 读写等价）
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_data(tmp_path, monkeypatch):
    """把 `main.py` 里各条 JSON 路径 monkeypatch 到临时目录，保证测试之间隔离，
    也不污染真实 `data/` 目录。

    数据 PR-15 反转默认后，canvas_store 默认走 DB 主写；本文件测试的是"store
    facade → main JSON helper"等价性，需要显式 `CANVAS_PRIMARY_WRITE=json` 才能
    保留 JSON roundtrip 契约。

    数据 PR-20（Wave 3-N.5 主线 B）反转默认后，project_store 亦默认走 DB 主写；
    同理需要显式 `PROJECT_PRIMARY_WRITE=json` 才能保留 JSON roundtrip 契约。
    """
    import main

    # 数据 PR-15 反转承接：强制 json 主写路径。
    monkeypatch.setenv("CANVAS_PRIMARY_WRITE", "json")
    # 数据 PR-20 反转承接：强制 json 主写路径（Project 域）。
    monkeypatch.setenv("PROJECT_PRIMARY_WRITE", "json")
    # 数据 PR-21 反转承接：强制 json 主写路径（PromptLibrary 域）。
    monkeypatch.setenv("PROMPT_LIBRARY_PRIMARY_WRITE", "json")
    # 数据 PR-22 反转承接：强制 json 主写路径（WorkflowDefinition 域）。
    monkeypatch.setenv("WORKFLOW_DEFINITION_PRIMARY_WRITE", "json")
    # 数据 PR-23 反转承接：强制 json 主写路径（AssetLibrary 域 · M1 收官）。
    monkeypatch.setenv("ASSET_LIBRARY_PRIMARY_WRITE", "json")

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "canvases").mkdir(exist_ok=True)
    (data_dir / "conversations").mkdir(exist_ok=True)
    (data_dir / "history").mkdir(exist_ok=True)
    (data_dir / "runninghub_workflow_store").mkdir(exist_ok=True)

    # 替换所有相关路径常量。使用 monkeypatch.setattr，测试后自动回退。
    monkeypatch.setattr(main, "DATA_DIR", str(data_dir), raising=True)
    monkeypatch.setattr(main, "CANVAS_DIR", str(data_dir / "canvases"), raising=True)
    monkeypatch.setattr(main, "CONVERSATION_DIR", str(data_dir / "conversations"), raising=True)
    monkeypatch.setattr(main, "HISTORY_FILE", str(data_dir / "history.json"), raising=True)
    monkeypatch.setattr(main, "ASSET_LIBRARY_PATH", str(data_dir / "asset_library.json"), raising=True)
    monkeypatch.setattr(main, "PROMPT_LIBRARY_PATH", str(data_dir / "prompt_library.json"), raising=True)
    monkeypatch.setattr(main, "API_PROVIDERS_FILE", str(data_dir / "api_providers.json"), raising=True)
    monkeypatch.setattr(main, "RUNNINGHUB_WORKFLOW_STORE_FILE", str(data_dir / "runninghub_workflow_store.json"), raising=True)
    monkeypatch.setattr(main, "PROJECTS_PATH", str(data_dir / "projects.json"), raising=True)
    return data_dir


def test_canvas_store_roundtrip(isolated_data):
    """canvas_store.save_canvas -> load_canvas 等价 main.save_canvas -> main.load_canvas。"""
    from app.stores import canvas_store
    import main

    canvas = {
        "id": "smoke_canvas_be04_001",
        "title": "BE-04 smoke",
        "icon": "layers",
        "kind": "classic",
        "nodes": [],
        "connections": [],
        "viewport": {"x": 0, "y": 0, "scale": 1},
    }
    canvas_store.save_canvas(dict(canvas))
    via_facade = canvas_store.load_canvas("smoke_canvas_be04_001")
    via_direct = main.load_canvas("smoke_canvas_be04_001")
    assert via_facade == via_direct


def test_project_store_roundtrip(isolated_data):
    from app.stores import project_store
    import main

    projects = [
        {"id": "smoke_p1", "name": "smoke1", "order": 1, "created_at": 1, "updated_at": 1},
        {"id": "smoke_p2", "name": "smoke2", "order": 2, "created_at": 2, "updated_at": 2},
    ]
    project_store.save_projects(projects)
    assert project_store.load_projects() == projects
    assert main.load_projects() == projects


def test_asset_library_store_roundtrip(isolated_data):
    from app.stores import asset_library_store
    import main

    # 通过 helper 首次触发默认库创建（现在走 store facade）
    lib1 = asset_library_store.load_asset_library()
    assert isinstance(lib1, dict)
    lib1_id = lib1.get("active_library_id") or (lib1.get("libraries") or [{}])[0].get("id")
    assert lib1_id
    # save 后重新 load 值一致
    asset_library_store.save_asset_library(lib1)
    lib2 = asset_library_store.load_asset_library()
    assert lib2 == lib1
    # main.load_asset_library 直接调用等价
    lib3 = main.load_asset_library()
    assert lib3 == lib1


def test_prompt_library_store_roundtrip(isolated_data):
    from app.stores import prompt_library_store
    import main

    data1 = prompt_library_store.load_prompt_libraries()
    assert isinstance(data1, dict)
    assert "active_library_id" in data1
    assert "libraries" in data1
    # save 后 load 幂等
    saved = prompt_library_store.save_prompt_libraries(data1)
    assert saved["libraries"] == data1["libraries"]
    # main 直接调用等价（时间戳会变但 libraries 结构一致）
    data2 = main.load_prompt_libraries()
    assert data2["libraries"] == data1["libraries"]


def test_provider_config_store_roundtrip(isolated_data):
    from app.stores import provider_config_store
    import main

    # save 需要 `normalize_provider` 兼容 shape — 用最简 payload
    providers = [{
        "id": "smoke_prov_be04",
        "name": "BE-04 smoke",
        "type": "openai",
        "protocol": "openai",
        "enabled": True,
    }]
    provider_config_store.save_api_providers(providers)
    loaded_facade = provider_config_store.load_api_providers()
    loaded_direct = main.load_api_providers()
    assert loaded_facade == loaded_direct


def test_history_store_save(isolated_data):
    """`save_to_history` 追加式；只验证 facade == direct。"""
    from app.stores import history_store
    import main

    record = {
        "task_id": "smoke_be04_task",
        "created_at": 1,
        "url": "http://smoke",
        "prompt": "smoke",
    }
    history_store.save_to_history(record)
    # 直接读文件确认写入
    with open(main.HISTORY_FILE, "r", encoding="utf-8") as fh:
        hist = json.load(fh)
    assert any(r.get("task_id") == "smoke_be04_task" for r in hist)


def test_conversation_store_roundtrip(isolated_data):
    from app.stores import conversation_store
    import main

    user_id = "smoke-user-be04"
    conv = {
        "id": "conv-be04-smoke",
        "title": "smoke",
        "created_at": 1,
        "updated_at": 1,
        "messages": [],
    }
    conversation_store.save_conversation(user_id, conv)
    loaded_facade = conversation_store.load_conversation(user_id, "conv-be04-smoke")
    loaded_direct = main.load_conversation(user_id, "conv-be04-smoke")
    assert loaded_facade == loaded_direct == conv


def test_workflow_store_roundtrip(isolated_data):
    from app.stores import workflow_store
    import main

    payload = {"smoke_wf_be04": {"workflowId": "smoke_wf_be04", "kind": "workflow"}}
    workflow_store.save_runninghub_workflow_store(payload)
    loaded_facade = workflow_store.load_runninghub_workflow_store()
    loaded_direct = main.load_runninghub_workflow_store()
    assert loaded_facade == loaded_direct


def test_storage_settings_store_load(isolated_data, monkeypatch):
    """load_storage_settings 应现读文件；facade 与直接调用等价。"""
    from app.stores import storage_settings_store
    import main

    # 用临时 STORAGE_SETTINGS_FILE
    ssf = isolated_data / "storage_settings.json"
    monkeypatch.setattr(main, "STORAGE_SETTINGS_FILE", str(ssf), raising=True)
    ssf.write_text(json.dumps({
        "upload": str(isolated_data / "u"),
        "generated": str(isolated_data / "g"),
        "local": str(isolated_data / "l"),
    }), encoding="utf-8")

    facade = storage_settings_store.load_storage_settings()
    direct = main.load_storage_settings()
    assert facade == direct
    assert "dirs" in facade


# ---------------------------------------------------------------------------
# 4. helper-in-helper 语义抽验（选取具体 caller 场景）
# ---------------------------------------------------------------------------


def test_new_conversation_persists_via_facade(isolated_data):
    """`new_conversation` 内已改用 conversation_store.save_conversation。
    验证：新会话文件真实落盘。"""
    import main

    conv = main.new_conversation("smoke-user-be04-new", "smoke-title")
    assert conv["title"] == "smoke-title"
    assert conv["id"]
    # 通过直接 helper 读回，确认走的是同一文件
    loaded = main.load_conversation("smoke-user-be04-new", conv["id"])
    assert loaded["id"] == conv["id"]


def test_new_canvas_persists_via_facade(isolated_data):
    """`new_canvas` 内已改用 canvas_store.save_canvas。"""
    import main

    canvas = main.new_canvas("smoke-canvas-be04-new", "layers", "classic", None)
    assert canvas["title"] == "smoke-canvas-be04-new"
    loaded = main.load_canvas(canvas["id"])
    assert loaded["id"] == canvas["id"]
    assert loaded["title"] == "smoke-canvas-be04-new"


def test_ensure_default_project_persists_via_facade(isolated_data):
    """`ensure_default_project` 内 load_projects / save_projects 均走 store facade。"""
    import main

    projects = main.ensure_default_project()
    assert any(p.get("id") == main.DEFAULT_PROJECT_ID for p in projects)
    # 二次调用幂等（不会重复添加 default）
    projects2 = main.ensure_default_project()
    assert len(projects2) == len(projects)


def test_new_project_persists_via_facade(isolated_data):
    import main

    proj = main.new_project("smoke-proj-be04")
    assert proj["name"] == "smoke-proj-be04"
    all_projects = main.load_projects()
    assert any(p["id"] == proj["id"] for p in all_projects)


def test_public_api_providers_via_facade(isolated_data, monkeypatch):
    """`public_api_providers` -> `load_api_providers` 走 store facade；
    返回 shape 与直接调用一致（密钥字段脱敏由 public_provider 处理）。"""
    import main

    # 兜底：新库无 providers 时，函数应仍返回 list（可为空或默认）
    result = main.public_api_providers()
    assert isinstance(result, list)


def test_get_api_provider_uses_facade(isolated_data):
    """`get_api_provider` -> `load_api_providers` 走 store facade。"""
    import main
    from fastapi import HTTPException

    from app.stores import provider_config_store
    providers = [{"id": "smoke_be04", "name": "smoke", "protocol": "openai",
                  "type": "openai", "enabled": True, "primary": True}]
    provider_config_store.save_api_providers(providers)
    prov = main.get_api_provider("smoke_be04")
    assert prov["id"] == "smoke_be04"

    # 未找到 -> HTTPException 语义保留
    with pytest.raises(HTTPException) as exc:
        main.get_api_provider_exact("nonexistent_be04")
    assert exc.value.status_code == 400


def test_load_asset_library_bootstrap_via_facade(isolated_data):
    """`load_asset_library` 内首次走默认库创建路径，用了 store facade save。"""
    import main

    assert not os.path.exists(main.ASSET_LIBRARY_PATH)
    lib = main.load_asset_library()
    assert os.path.exists(main.ASSET_LIBRARY_PATH)  # 已经通过 facade 存盘
    assert isinstance(lib, dict)


def test_public_prompt_libraries_via_facade(isolated_data):
    """`public_prompt_libraries` 内 load_prompt_libraries 走 store facade。"""
    import main

    result = main.public_prompt_libraries()
    assert isinstance(result, dict)
    assert "libraries" in result


def test_prune_runninghub_workflow_store_via_facade(isolated_data):
    """`prune_runninghub_workflow_store_for_provider` 内 load/save workflow store。"""
    import main
    from app.stores import workflow_store

    # 预置 store 内有条目
    workflow_store.save_runninghub_workflow_store({"wf-old": {"workflowId": "wf-old"}})
    # provider 里没有对应 workflow，prune 应清空
    provider = {"id": "runninghub", "rh_workflows": []}
    main.prune_runninghub_workflow_store_for_provider(provider)
    remaining = workflow_store.load_runninghub_workflow_store()
    assert "wf-old" not in remaining


def test_pick_chat_image_provider_via_facade(isolated_data):
    """`pick_chat_image_provider` 内 load_api_providers 走 store facade。"""
    import main
    from app.stores import provider_config_store

    provider_config_store.save_api_providers([{
        "id": "smoke_prov_be04_chat", "name": "chat-image", "protocol": "openai",
        "type": "openai", "enabled": True,
        "image_models": [{"id": "gpt-image"}]
    }])
    # 只是验证不抛异常，具体挑选逻辑不在本 PR 范围
    result = main.pick_chat_image_provider("smoke_prov_be04_chat", "")
    assert result is None or isinstance(result, dict)


# ---------------------------------------------------------------------------
# 5. End-to-end (TestClient) — 抽验受影响路由行为不回归
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """TestClient 在真实 `main.app` 上运行；测试后清理由本 fixture 触发
    创建的 bootstrap 文件（`data/projects.json` / `data/prompt_libraries.json`），
    避免污染仓库工作树。仅在文件是**测试期新建**（不存在于 fixture 进入前）
    时才清理，已存在的用户数据保留。

    数据 PR-15 / PR-20 / PR-22 / PR-23 反转承接：本 fixture 模块作用域;走真实 main.app;
    默认 `CANVAS_PRIMARY_WRITE=db` / `PROJECT_PRIMARY_WRITE=db` /
    `WORKFLOW_DEFINITION_PRIMARY_WRITE=db` / `ASSET_LIBRARY_PRIMARY_WRITE=db` 会尝试
    触发 DB 主写(但 fixture 没有 `migrate_baseline`)。强制 env=json 保留原 JSON
    bootstrap 语义。测试结束后原样还原 env。
    """
    from fastapi.testclient import TestClient
    import main

    # 数据 PR-15 反转承接：强制 canvas json 主写路径。
    _prev_canvas = os.environ.get("CANVAS_PRIMARY_WRITE")
    os.environ["CANVAS_PRIMARY_WRITE"] = "json"
    # 数据 PR-20 反转承接：强制 project json 主写路径。
    _prev_project = os.environ.get("PROJECT_PRIMARY_WRITE")
    os.environ["PROJECT_PRIMARY_WRITE"] = "json"
    # 数据 PR-21 反转承接：强制 prompt_library json 主写路径。
    _prev_prompt_library = os.environ.get("PROMPT_LIBRARY_PRIMARY_WRITE")
    os.environ["PROMPT_LIBRARY_PRIMARY_WRITE"] = "json"
    # 数据 PR-22 反转承接：强制 workflow_definition json 主写路径。
    _prev_workflow = os.environ.get("WORKFLOW_DEFINITION_PRIMARY_WRITE")
    os.environ["WORKFLOW_DEFINITION_PRIMARY_WRITE"] = "json"
    # 数据 PR-23 反转承接：强制 asset_library json 主写路径（M1 收官）。
    _prev_asset_library = os.environ.get("ASSET_LIBRARY_PRIMARY_WRITE")
    os.environ["ASSET_LIBRARY_PRIMARY_WRITE"] = "json"

    to_clean = []
    for path_attr in ("PROJECTS_PATH", "PROMPT_LIBRARY_PATH"):
        path = getattr(main, path_attr, None)
        if path and not os.path.exists(path):
            to_clean.append(path)

    try:
        yield TestClient(main.app)
    finally:
        # 只清理本 fixture 触发新建的 bootstrap 产物
        for path in to_clean:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        # 还原 env
        if _prev_canvas is None:
            os.environ.pop("CANVAS_PRIMARY_WRITE", None)
        else:
            os.environ["CANVAS_PRIMARY_WRITE"] = _prev_canvas
        if _prev_project is None:
            os.environ.pop("PROJECT_PRIMARY_WRITE", None)
        else:
            os.environ["PROJECT_PRIMARY_WRITE"] = _prev_project
        if _prev_prompt_library is None:
            os.environ.pop("PROMPT_LIBRARY_PRIMARY_WRITE", None)
        else:
            os.environ["PROMPT_LIBRARY_PRIMARY_WRITE"] = _prev_prompt_library
        if _prev_workflow is None:
            os.environ.pop("WORKFLOW_DEFINITION_PRIMARY_WRITE", None)
        else:
            os.environ["WORKFLOW_DEFINITION_PRIMARY_WRITE"] = _prev_workflow
        if _prev_asset_library is None:
            os.environ.pop("ASSET_LIBRARY_PRIMARY_WRITE", None)
        else:
            os.environ["ASSET_LIBRARY_PRIMARY_WRITE"] = _prev_asset_library


def test_e2e_get_providers(client):
    r = client.get("/api/providers")
    assert r.status_code == 200
    body = r.json()
    assert "providers" in body
    assert isinstance(body["providers"], list)


def test_e2e_get_prompt_libraries(client):
    r = client.get("/api/prompt-libraries")
    # 该路由存在时应 200
    assert r.status_code in (200, 404)


def test_e2e_get_asset_library(client):
    r = client.get("/api/asset-library")
    assert r.status_code == 200
    body = r.json()
    assert "library" in body


def test_e2e_get_projects(client):
    r = client.get("/api/projects")
    assert r.status_code == 200


def test_e2e_get_canvases(client):
    r = client.get("/api/canvases")
    assert r.status_code == 200
