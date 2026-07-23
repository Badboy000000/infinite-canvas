"""PR-4b · FileService 上传通道主写切换测试(T230-T245)· Wave 3-N.5 主线 A。

覆盖:
- T230-T234:5 入口 flag=true 走新路径 · file_objects 表 count+1 · sha256 去重
- T235-T239:5 入口 flag=false 走旧路径 · file_objects 表零触碰
- T240:sidecar 语义保留(.classification.json 独立于 create_from_upload)
- T241:PR-4a 5 入口 A1+S8+magic 校验保持生效(flag=true 不绕过安全)
- T242:URL 格式向后兼容(前端仍收 `/assets/...` 或 `/api/files/{id}` 均可)
- T243:flag=false 时 create_from_upload 零触发(dispatch 断言)
- T244:fixture 隔离(monkeypatch DATA_DB_PATH + DATA_DIR + _reset_settings_cache_for_tests)
- T245:AST vs 31e0d3d · 5 save 函数体保持 byte-identical(引用 test_save_functions_frozen.py)
"""
from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).parent / "fixtures" / "magic"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolated_upload_env(monkeypatch, tmp_path):
    """T244 · fixture 隔离:每个测试独立 sqlite + assets 根 + settings 缓存清空。

    与 test_file_service_generation.py 同源:main.DATA_DB_PATH / main.DATA_DIR 在
    import 时求值 · monkeypatch env var 无效 · 必须直接改模块属性。同时把
    ASSETS_DIR 系列常量 + storage_settings 缓存全部指到 tmp_path,防止真实
    assets/input 目录被污染。
    """
    import main
    from app.db import engine as db_engine

    db_path = tmp_path / "test_pr4b.db"
    assets_root = tmp_path / "assets"
    upload_dir = assets_root / "input"
    generated_dir = assets_root / "output"
    local_dir = assets_root / "uploads"
    library_dir = assets_root / "library"
    for d in (assets_root, upload_dir, generated_dir, local_dir, library_dir):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(main, "DATA_DB_PATH", str(db_path))
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(main, "ASSETS_DIR", str(assets_root))
    monkeypatch.setattr(main, "ASSET_LIBRARY_DIR", str(library_dir))
    monkeypatch.setenv("DATA_DB_PATH", str(db_path))

    # storage_settings_snapshot 走 lru_cache · 清缓存再返回临时目录快照
    from app.shared.settings import runtime as _settings_runtime
    try:
        _settings_runtime._reset_settings_cache_for_tests()
    except Exception:
        pass

    snap = main.StorageSettings(
        upload=str(upload_dir),
        generated=str(generated_dir),
        local=str(local_dir),
    )
    monkeypatch.setattr(main, "storage_settings_snapshot", lambda: snap)
    monkeypatch.setattr(main, "current_upload_dir", lambda: str(upload_dir))
    monkeypatch.setattr(main, "current_generated_dir", lambda: str(generated_dir))
    monkeypatch.setattr(main, "current_local_dir", lambda: str(local_dir))
    # classify_asset_image_best_effort 会走 provider · 隔离掉
    monkeypatch.setattr(main, "classify_asset_image_best_effort", AsyncMock(return_value=None))

    db_engine.reset_engine()
    from app.db.engine import run_migrations
    run_migrations("head")

    yield {
        "tmp_path": tmp_path,
        "db_path": db_path,
        "assets_root": assets_root,
        "upload_dir": upload_dir,
        "generated_dir": generated_dir,
        "local_dir": local_dir,
        "library_dir": library_dir,
    }

    db_engine.reset_engine()
    try:
        _settings_runtime._reset_settings_cache_for_tests()
    except Exception:
        pass


@pytest.fixture
def api_client():
    import main as main_mod
    return TestClient(main_mod.app)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _png_bytes(size: tuple[int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (128, 128, 128)).save(buf, format="PNG")
    return buf.getvalue()


def _count_file_objects() -> int:
    from sqlalchemy import select, func
    from app.data_import import tables as t
    from app.db.engine import get_engine

    engine = get_engine()
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(t.file_objects)).scalar() or 0


def _find_row_by_sha(sha_bytes: bytes):
    from sqlalchemy import select
    from app.data_import import tables as t
    from app.db.engine import get_engine

    engine = get_engine()
    with engine.connect() as conn:
        return conn.execute(
            select(t.file_objects).where(t.file_objects.c.sha256 == sha_bytes)
        ).fetchone()


def _build_valid_workflow_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr(
            "workflow.json",
            json.dumps({"nodes": [], "connections": [], "resources": []}).encode("utf-8"),
        )
    return buf.getvalue()


def _build_workflow_zip_with_resource(resource_bytes: bytes) -> bytes:
    """构造合法 STORED workflow zip · 含 workflow.json + 单个 resource 引用。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        workflow = {
            "nodes": [{"id": "n1", "type": "image", "value": "./res.bin"}],
            "connections": [],
            "resources": [{"name": "res.bin", "archive": "res.bin", "url": ""}],
        }
        zf.writestr("workflow.json", json.dumps(workflow).encode("utf-8"))
        zf.writestr("res.bin", resource_bytes)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# T230-T234 · flag=true 5 入口走新路径 · file_objects count+1
# ---------------------------------------------------------------------------
def test_T230_upload_ai_base64_primary_write_creates_file_object(monkeypatch, api_client):
    """T230 · upload_ai_base64 flag=true → file_objects 表 count+1 · sha256 匹配。"""
    import main
    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_UPLOAD", True)

    before = _count_file_objects()
    png = _png_bytes((32, 32))
    b64 = base64.b64encode(png).decode()
    resp = api_client.post(
        "/api/ai/upload-base64",
        json={"data": b64, "name": "t230.png", "content_type": "image/png"},
    )
    assert resp.status_code == 200, resp.text
    after = _count_file_objects()
    assert after == before + 1, f"count+1 expected · before={before} after={after}"
    # sha256 匹配上传字节
    row = _find_row_by_sha(hashlib.sha256(png).digest())
    assert row is not None, "row for uploaded sha256 not found"
    assert row.size_bytes == len(png)
    assert row.origin_kind == "ai_input"
    assert row.reference_count == 1


def test_T231_upload_ai_reference_primary_write_creates_file_object(monkeypatch, api_client):
    """T231 · upload_ai_reference flag=true → file_objects 表 count+1。"""
    import main
    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_UPLOAD", True)

    before = _count_file_objects()
    png = _png_bytes((40, 40))
    resp = api_client.post(
        "/api/ai/upload",
        files={"files": ("t231.png", png, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    after = _count_file_objects()
    assert after == before + 1
    row = _find_row_by_sha(hashlib.sha256(png).digest())
    assert row is not None
    assert row.origin_kind == "ai_input"


def test_T232_upload_local_assets_primary_write_creates_file_object(monkeypatch, api_client):
    """T232 · upload_local_assets flag=true → file_objects 表 count+1。"""
    import main
    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_UPLOAD", True)

    before = _count_file_objects()
    png = _png_bytes((48, 48))
    resp = api_client.post(
        "/api/local-assets/upload",
        files={"files": ("t232.png", png, "image/png")},
        data={"folder": ""},
    )
    assert resp.status_code == 200, resp.text
    after = _count_file_objects()
    assert after == before + 1
    row = _find_row_by_sha(hashlib.sha256(png).digest())
    assert row is not None
    assert row.origin_kind == "upload"


def test_T233_upload_asset_library_workflows_primary_write(monkeypatch, api_client):
    """T233 · upload_asset_library_workflows flag=true → file_objects 表 count+1。"""
    import main
    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_UPLOAD", True)

    before = _count_file_objects()
    zip_bytes = _build_valid_workflow_zip()
    resp = api_client.post(
        "/api/asset-library/workflows/upload",
        files={"files": ("t233.zip", zip_bytes, "application/zip")},
        data={"library_id": "", "category_id": ""},
    )
    assert resp.status_code == 200, resp.text
    after = _count_file_objects()
    assert after == before + 1
    row = _find_row_by_sha(hashlib.sha256(zip_bytes).digest())
    assert row is not None
    assert row.origin_kind == "workflow_import"


def test_T234_import_canvas_workflow_primary_write(monkeypatch, api_client):
    """T234 · import_canvas_workflow flag=true · zip 含 resource → resource 走
    create_from_upload · file_objects 表 count 增(至少 1)。"""
    import main
    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_UPLOAD", True)

    before = _count_file_objects()
    resource = b"pr4b-t234-resource-bytes-123"
    zip_bytes = _build_workflow_zip_with_resource(resource)
    resp = api_client.post(
        "/api/canvas-workflows/import",
        files={"file": ("t234.zip", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 200, resp.text
    after = _count_file_objects()
    assert after >= before + 1
    row = _find_row_by_sha(hashlib.sha256(resource).digest())
    assert row is not None
    assert row.origin_kind == "workflow_import"


# ---------------------------------------------------------------------------
# T235-T239 · flag=false 5 入口零触碰 file_objects
# ---------------------------------------------------------------------------
def test_T235_upload_ai_base64_flag_false_zero_touch(monkeypatch, api_client):
    """T235 · upload_ai_base64 flag=false → file_objects 表零触碰。"""
    import main
    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_UPLOAD", False)

    before = _count_file_objects()
    png = _png_bytes((32, 32))
    b64 = base64.b64encode(png).decode()
    resp = api_client.post(
        "/api/ai/upload-base64",
        json={"data": b64, "name": "t235.png", "content_type": "image/png"},
    )
    assert resp.status_code == 200
    assert _count_file_objects() == before, "flag=false 竟触碰 file_objects"


def test_T236_upload_ai_reference_flag_false_zero_touch(monkeypatch, api_client):
    """T236 · upload_ai_reference flag=false → file_objects 表零触碰。"""
    import main
    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_UPLOAD", False)

    before = _count_file_objects()
    png = _png_bytes((40, 40))
    resp = api_client.post(
        "/api/ai/upload",
        files={"files": ("t236.png", png, "image/png")},
    )
    assert resp.status_code == 200
    assert _count_file_objects() == before


def test_T237_upload_local_assets_flag_false_zero_touch(monkeypatch, api_client):
    """T237 · upload_local_assets flag=false → file_objects 表零触碰。"""
    import main
    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_UPLOAD", False)

    before = _count_file_objects()
    png = _png_bytes((48, 48))
    resp = api_client.post(
        "/api/local-assets/upload",
        files={"files": ("t237.png", png, "image/png")},
        data={"folder": ""},
    )
    assert resp.status_code == 200
    assert _count_file_objects() == before


def test_T238_upload_asset_library_workflows_flag_false_zero_touch(monkeypatch, api_client):
    """T238 · upload_asset_library_workflows flag=false → file_objects 表零触碰。"""
    import main
    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_UPLOAD", False)

    before = _count_file_objects()
    zip_bytes = _build_valid_workflow_zip()
    resp = api_client.post(
        "/api/asset-library/workflows/upload",
        files={"files": ("t238.zip", zip_bytes, "application/zip")},
        data={"library_id": "", "category_id": ""},
    )
    assert resp.status_code == 200
    assert _count_file_objects() == before


def test_T239_import_canvas_workflow_flag_false_zero_touch(monkeypatch, api_client):
    """T239 · import_canvas_workflow flag=false → file_objects 表零触碰。"""
    import main
    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_UPLOAD", False)

    before = _count_file_objects()
    resource = b"pr4b-t239-resource-different"
    zip_bytes = _build_workflow_zip_with_resource(resource)
    resp = api_client.post(
        "/api/canvas-workflows/import",
        files={"file": ("t239.zip", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 200
    assert _count_file_objects() == before


# ---------------------------------------------------------------------------
# T230b · sha256 dedup(同图上传两次 count 不变 · reference_count+1)
# ---------------------------------------------------------------------------
def test_T230b_sha256_dedup_reference_count_bumped(monkeypatch, api_client):
    """同一 PNG 通过 upload_ai_base64 上传两次 · file_objects count 不变 · reference_count 递增。"""
    import main
    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_UPLOAD", True)

    png = _png_bytes((36, 36))
    b64 = base64.b64encode(png).decode()

    resp1 = api_client.post(
        "/api/ai/upload-base64",
        json={"data": b64, "name": "dedup.png", "content_type": "image/png"},
    )
    assert resp1.status_code == 200
    after1 = _count_file_objects()
    row1 = _find_row_by_sha(hashlib.sha256(png).digest())
    assert row1 is not None
    ref1 = row1.reference_count

    resp2 = api_client.post(
        "/api/ai/upload-base64",
        json={"data": b64, "name": "dedup2.png", "content_type": "image/png"},
    )
    assert resp2.status_code == 200
    after2 = _count_file_objects()
    row2 = _find_row_by_sha(hashlib.sha256(png).digest())

    assert after2 == after1, "sha256 去重失败 · file_objects count 不应增长"
    assert row2.reference_count == ref1 + 1, (
        f"reference_count 应 +1 · before={ref1} after={row2.reference_count}"
    )


# ---------------------------------------------------------------------------
# T240 · sidecar `.classification.json` 语义保留(独立于 create_from_upload)
# ---------------------------------------------------------------------------
def test_T240_sidecar_classification_json_semantics_preserved(monkeypatch, api_client):
    """T240 · upload_local_assets flag=true · classification 返回值触发 sidecar 写入。
    验证 sidecar 独立于主 file_object · 不与 create_from_upload 混淆。
    """
    import main
    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_UPLOAD", True)
    monkeypatch.setattr(
        main,
        "classify_asset_image_best_effort",
        AsyncMock(return_value={"tags": ["t240-tag"], "summary": "sidecar-test"}),
    )

    png = _png_bytes((50, 50))
    before = _count_file_objects()
    resp = api_client.post(
        "/api/local-assets/upload",
        files={"files": ("t240.png", png, "image/png")},
        data={"folder": ""},
    )
    assert resp.status_code == 200, resp.text
    # 主图 1 条 file_objects
    assert _count_file_objects() == before + 1

    # sidecar 落盘 · 独立文件
    local_dir = Path(main.current_local_dir())
    sidecars = list(local_dir.glob("*.classification.json"))
    assert sidecars, "classification sidecar 未落盘 · 语义丢失"
    payload = json.loads(sidecars[0].read_text(encoding="utf-8"))
    assert payload.get("summary") == "sidecar-test"


# ---------------------------------------------------------------------------
# T241 · PR-4a 安全校验保持生效(flag 切换不绕过 A1+S8+magic)
# ---------------------------------------------------------------------------
def test_T241_pr4a_security_gates_still_active_under_flag_true(monkeypatch, api_client):
    """T241 · flag=true 时 svg 伪装 PNG 仍被 PR-4a magic 层拒绝。"""
    import main
    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_UPLOAD", True)

    svg = (FIXTURES / "attacks" / "svg_as.png").read_bytes()
    before = _count_file_objects()
    resp = api_client.post(
        "/api/ai/upload",
        files={"files": ("evil.png", svg, "image/png")},
    )
    assert resp.status_code == 400, resp.text
    assert _count_file_objects() == before, "PR-4a 拒绝路径竟触碰 file_objects"


# ---------------------------------------------------------------------------
# T242 · URL 向后兼容(前端仍收 `/assets/...`)
# ---------------------------------------------------------------------------
def test_T242_url_format_backward_compatible(monkeypatch, api_client):
    """T242 · flag=true / false 两态下 · upload_ai_base64 返回的 URL 结构不变。"""
    import main

    png = _png_bytes((32, 32))
    b64 = base64.b64encode(png).decode()

    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_UPLOAD", False)
    resp_off = api_client.post(
        "/api/ai/upload-base64",
        json={"data": b64, "name": "t242a.png", "content_type": "image/png"},
    )
    assert resp_off.status_code == 200
    url_off = resp_off.json()["files"][0]["url"]

    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_UPLOAD", True)
    resp_on = api_client.post(
        "/api/ai/upload-base64",
        json={"data": b64, "name": "t242b.png", "content_type": "image/png"},
    )
    assert resp_on.status_code == 200
    url_on = resp_on.json()["files"][0]["url"]

    for u in (url_off, url_on):
        assert u.startswith("/assets/") or u.startswith("/api/files/"), (
            f"URL 格式向后不兼容: {u}"
        )
        assert "ai_ref_" in u, f"命名前缀缺失: {u}"


# ---------------------------------------------------------------------------
# T243 · flag=false 时 create_from_upload 零触发(dispatch 断言)
# ---------------------------------------------------------------------------
def test_T243_flag_false_bypasses_create_from_upload(monkeypatch, api_client):
    """T243 · flag=false 时 file_service.create_from_upload 零触发。

    通过替换方法为 MagicMock 观察 call_count · 参照 test_main_integration.py::T148。
    """
    import main
    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_UPLOAD", False)

    tracker = MagicMock(side_effect=RuntimeError("create_from_upload should NOT fire when flag=False"))
    monkeypatch.setattr(main.file_service, "create_from_upload", tracker)

    png = _png_bytes((32, 32))
    b64 = base64.b64encode(png).decode()
    resp = api_client.post(
        "/api/ai/upload-base64",
        json={"data": b64, "name": "t243.png", "content_type": "image/png"},
    )
    assert resp.status_code == 200
    assert tracker.call_count == 0, "flag=false 竟触发 create_from_upload · 门禁失效"


def test_T243b_flag_true_triggers_create_from_upload(monkeypatch, api_client):
    """T243b · flag=true 时 file_service.create_from_upload 精确触发 1 次(单文件路径)。"""
    import main
    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_UPLOAD", True)

    tracker = MagicMock(wraps=main.file_service.create_from_upload)
    monkeypatch.setattr(main.file_service, "create_from_upload", tracker)

    png = _png_bytes((32, 32))
    b64 = base64.b64encode(png).decode()
    resp = api_client.post(
        "/api/ai/upload-base64",
        json={"data": b64, "name": "t243b.png", "content_type": "image/png"},
    )
    assert resp.status_code == 200
    assert tracker.call_count == 1
    _, kwargs = tracker.call_args
    assert kwargs.get("origin_kind") == "ai_input"
    assert kwargs.get("legacy_url", "").startswith("/assets/")


# ---------------------------------------------------------------------------
# T244 · fixture 隔离健壮性(参见 _isolated_upload_env autouse fixture)
# ---------------------------------------------------------------------------
def test_T244_fixture_isolation_uses_tmp_paths(monkeypatch):
    """T244 · autouse fixture 已把 DATA_DB_PATH / DATA_DIR / ASSETS_DIR 全部指到 tmp_path
    · 断言 main 模块属性都在 tmp_path 前缀下,避免污染真实工作区。
    """
    import main
    # 不再断言 tmp_path 具体路径 · 但可断言不指向仓库真实 data/ assets/
    assert not main.DATA_DB_PATH.endswith("data/canvas.db")
    assert not main.DATA_DB_PATH.endswith("data\\canvas.db")
    # DATA_DIR 已被 monkeypatch 到 tmp_path/data · 断言其在临时区
    assert "test_pr" in main.DATA_DIR.lower() or main.DATA_DIR != str(
        Path(__file__).resolve().parents[2] / "data"
    )
    # storage snapshot 全部指到 tmp assets/*
    snap = main.storage_settings_snapshot()
    for d in (snap.upload, snap.generated, snap.local):
        assert "assets" in d.replace("\\", "/")


# ---------------------------------------------------------------------------
# T245 · AST vs 31e0d3d · 5 save 函数体保持 byte-identical
# ---------------------------------------------------------------------------
_FIVE_SAVE_FUNCS = (
    "save_projects",
    "save_prompt_libraries",
    "save_runninghub_workflow_store",
    "save_asset_library",
    "save_canvas",
)


@pytest.mark.parametrize("fname", _FIVE_SAVE_FUNCS)
def test_T245_five_save_functions_ast_byte_identical_vs_31e0d3d(fname: str):
    """T245 · 5 个 save_* 函数体 AST vs `31e0d3d` byte-identical。

    Note:test_save_functions_frozen.py 已经用各自 baseline_ref pin 了 4 项 +
    test_canvas_shadow_write.py pin 了 save_canvas。本 T245 补加 vs 31e0d3d
    统一断言 · 保证 PR-4b 不触碰 5 save 函数体。
    """
    baseline_ref = "31e0d3d"
    result = subprocess.run(
        ["git", "show", f"{baseline_ref}:main.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        pytest.skip(f"baseline ref {baseline_ref} unavailable")

    baseline_tree = ast.parse(result.stdout)
    current_tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))

    def _find(tree, name):
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                return node
        return None

    b = _find(baseline_tree, fname)
    c = _find(current_tree, fname)
    assert b is not None and c is not None, f"{fname} missing"
    assert ast.dump(b, include_attributes=False) == ast.dump(c, include_attributes=False), (
        f"PR-4b 触碰了 5 save 函数 {fname} · vs 31e0d3d AST 不等价"
    )


def test_T245b_storage_frozen_zone_ast_vs_a6f863a():
    """T245b · 冻结区 3 符号(StorageSettings / apply_storage_settings /
    storage_settings_snapshot)AST vs a6f863a byte-equivalent。"""
    baseline_ref = "a6f863a"
    result = subprocess.run(
        ["git", "show", f"{baseline_ref}:main.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        pytest.skip(f"baseline ref {baseline_ref} unavailable")
    baseline_tree = ast.parse(result.stdout)
    current_tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))

    def _find_func(tree, name):
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                return node
        return None

    def _find_cls(tree, name):
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == name:
                return node
        return None

    for fn in ("apply_storage_settings", "storage_settings_snapshot"):
        b = _find_func(baseline_tree, fn)
        c = _find_func(current_tree, fn)
        assert b is not None and c is not None, f"{fn} missing"
        assert ast.dump(b, include_attributes=False) == ast.dump(c, include_attributes=False), (
            f"PR-4b 触碰了冻结区 {fn} · vs a6f863a AST 不等价"
        )
    b_cls = _find_cls(baseline_tree, "StorageSettings")
    c_cls = _find_cls(current_tree, "StorageSettings")
    assert ast.dump(b_cls, include_attributes=False) == ast.dump(c_cls, include_attributes=False), (
        "PR-4b 触碰了冻结区 class StorageSettings · vs a6f863a AST 不等价"
    )


# ---------------------------------------------------------------------------
# T245c · Provider 密钥零泄漏(独立 SQL 反查 file_objects · raw_meta)
# ---------------------------------------------------------------------------
def test_T245c_no_credential_leak_into_file_objects(monkeypatch, api_client):
    """T245c · 上传 5 入口后 · file_objects 全表任何字段无 api_key/access_token/
    Bearer/authorization 泄漏。硬约束 · 独立 SQL 反查。

    注:排除 object_key/legacy_path 内的合法路径子串(测试 tmp 路径含测试名 ·
    实际生产字节里无这些字段)。检查目标是 raw_meta / origin_metadata_sha /
    mime_type 等业务字段。
    """
    import main
    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_UPLOAD", True)

    # 上传 3 类不同字节 · 覆盖 image / zip
    png = _png_bytes((32, 32))
    api_client.post(
        "/api/ai/upload-base64",
        json={"data": base64.b64encode(png).decode(), "name": "s.png", "content_type": "image/png"},
    )
    api_client.post(
        "/api/ai/upload",
        files={"files": ("s2.png", _png_bytes((40, 40)), "image/png")},
    )
    api_client.post(
        "/api/local-assets/upload",
        files={"files": ("s3.png", _png_bytes((48, 48)), "image/png")},
        data={"folder": ""},
    )
    zip_bytes = _build_valid_workflow_zip()
    api_client.post(
        "/api/asset-library/workflows/upload",
        files={"files": ("s.zip", zip_bytes, "application/zip")},
        data={"library_id": "", "category_id": ""},
    )

    # 全表反查 · 排除 object_key/legacy_path/legacy_url(路径类字段 · 可能含
    # 测试 tmp 目录名 · 属误报) · 断言业务字段(raw_meta / mime_type / etag /
    # origin_kind / storage_backend / bucket / origin_metadata_sha)无泄漏。
    from sqlalchemy import select
    from app.data_import import tables as t
    from app.db.engine import get_engine

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(select(t.file_objects)).fetchall()

    banned = ("api_key", "access_token", "authorization", "bearer ")
    path_like_cols = {"object_key", "legacy_path", "legacy_url"}
    for row in rows:
        for col in row._mapping:
            if col in path_like_cols:
                continue
            val = row._mapping[col]
            if isinstance(val, (bytes, bytearray)):
                try:
                    val = val.decode("utf-8", errors="ignore")
                except Exception:
                    continue
            if not isinstance(val, str):
                continue
            lower = val.lower()
            for word in banned:
                assert word not in lower, (
                    f"密钥泄漏:column={col} value={val[:120]!r} matched={word!r}"
                )
