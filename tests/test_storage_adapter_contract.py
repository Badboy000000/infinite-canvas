"""StorageAdapter 契约测试（文件对象与 MinIO 治理 PR-1 / PR-3）。

参数化 fixture：`adapter` 参数化到 `LocalDirAdapter` 与 `MinioAdapter`
两个后端。

- `local` 分支：CI 默认跑，保留 PR-1 全部契约。
- `minio` 分支：由环境变量 `MINIO_INTEGRATION=1` 门控（默认 skip）。
  开发者本地跑集成测试时设置：
      MINIO_INTEGRATION=1
      MINIO_ENDPOINT=http://localhost:9000
      MINIO_ACCESS_KEY=...
      MINIO_SECRET_KEY=...
      MINIO_BUCKET=infinite-canvas-test
  单元测试（不需真连）见 `tests/files/test_minio_adapter_unit.py`。

覆盖：
- 写入-读回
- 写入-head
- 写入-删除
- 覆盖写
- `PartialUpload` 模拟
- `InvalidKey` 拒绝
- `list_prefix` 分页与 cursor
- `copy` 幂等
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.adapters.storage.base import (
    ObjectMeta,
    StorageAdapter,
    StorageError,
    StorageErrorKind,
    WritableObjectStream,
)
from app.adapters.storage.local_dir import LocalDirAdapter


# ---------------------------------------------------------------------------
# fixture 参数化：Local + Minio（后者由 MINIO_INTEGRATION env 门控）
# ---------------------------------------------------------------------------


_MINIO_INTEGRATION = os.environ.get("MINIO_INTEGRATION", "").strip().lower() in (
    "1",
    "true",
    "yes",
)


BACKENDS = [
    pytest.param("local", id="local"),
    pytest.param(
        "minio",
        id="minio",
        marks=pytest.mark.skipif(
            not _MINIO_INTEGRATION,
            reason="set MINIO_INTEGRATION=1 to run MinioAdapter contract tests",
        ),
    ),
]


@pytest.fixture(params=BACKENDS)
def adapter(request, tmp_path: Path) -> StorageAdapter:
    backend = request.param
    if backend == "local":
        return LocalDirAdapter(root=tmp_path, url_prefix="/assets")
    if backend == "minio":  # pragma: no cover - 需要真 MinIO 集成环境
        from app.adapters.storage.minio_adapter import build_minio_adapter_from_env

        return build_minio_adapter_from_env()
    raise RuntimeError(f"unknown backend {backend!r}")


# ---------------------------------------------------------------------------
# 基础：写入 - 读回 - head - 删除
# ---------------------------------------------------------------------------


def _read_all(adapter: StorageAdapter, key: str) -> bytes:
    return b"".join(adapter.get_stream(key))


def test_put_and_get_roundtrip(adapter: StorageAdapter):
    payload = b"hello-infinite-canvas-\xe4\xb8\xad\xe6\x96\x87"
    meta = adapter.put("dir1/file.bin", payload, mime_type="application/octet-stream")
    assert isinstance(meta, ObjectMeta)
    assert meta.key == "dir1/file.bin"
    assert meta.size == len(payload)
    assert meta.etag
    body = _read_all(adapter, "dir1/file.bin")
    assert body == payload


def test_put_and_head(adapter: StorageAdapter):
    payload = b"x" * 4096
    put_meta = adapter.put("a/b/c/file.txt", payload)
    head_meta = adapter.head("a/b/c/file.txt")
    assert head_meta.size == put_meta.size
    assert head_meta.etag == put_meta.etag
    assert head_meta.key == "a/b/c/file.txt"


def test_put_then_delete(adapter: StorageAdapter):
    adapter.put("todelete.bin", b"payload")
    adapter.delete("todelete.bin")
    with pytest.raises(StorageError) as ei:
        adapter.head("todelete.bin")
    assert ei.value.kind == StorageErrorKind.NOT_FOUND.value


def test_delete_missing_raises_notfound(adapter: StorageAdapter):
    with pytest.raises(StorageError) as ei:
        adapter.delete("never/existed.bin")
    assert ei.value.kind == StorageErrorKind.NOT_FOUND.value


def test_delete_missing_ok(adapter: StorageAdapter):
    # 不 raise
    adapter.delete("never/existed.bin", missing_ok=True)


def test_get_missing_raises_notfound(adapter: StorageAdapter):
    with pytest.raises(StorageError) as ei:
        _read_all(adapter, "missing.bin")
    assert ei.value.kind == StorageErrorKind.NOT_FOUND.value


def test_head_missing_raises_notfound(adapter: StorageAdapter):
    with pytest.raises(StorageError) as ei:
        adapter.head("missing.bin")
    assert ei.value.kind == StorageErrorKind.NOT_FOUND.value
    # 提供 HTTP status hint 供路由层参考
    assert ei.value.http_status_hint == 404


# ---------------------------------------------------------------------------
# 覆盖写 & if_match_etag
# ---------------------------------------------------------------------------


def test_overwrite_semantics(adapter: StorageAdapter):
    adapter.put("dup.bin", b"v1")
    # overwrite=True (默认) 允许覆盖
    meta2 = adapter.put("dup.bin", b"v2-longer", overwrite=True)
    assert meta2.size == len(b"v2-longer")
    body = _read_all(adapter, "dup.bin")
    assert body == b"v2-longer"


def test_overwrite_false_rejects_existing(adapter: StorageAdapter):
    adapter.put("dup2.bin", b"v1")
    with pytest.raises(StorageError) as ei:
        adapter.put("dup2.bin", b"v2", overwrite=False)
    assert ei.value.kind == StorageErrorKind.ALREADY_EXISTS.value


def test_if_match_etag_mismatch_precondition(adapter: StorageAdapter):
    meta = adapter.put("etagged.bin", b"aaa")
    with pytest.raises(StorageError) as ei:
        adapter.put(
            "etagged.bin",
            b"bbb",
            if_match_etag="0" * len(meta.etag),
        )
    assert ei.value.kind == StorageErrorKind.PRECONDITION_FAILED.value


def test_if_match_etag_match_ok(adapter: StorageAdapter):
    meta = adapter.put("etag2.bin", b"aaa")
    meta2 = adapter.put("etag2.bin", b"bbb", if_match_etag=meta.etag)
    assert meta2.size == 3


# ---------------------------------------------------------------------------
# 流式写入 + PartialUpload 模拟
# ---------------------------------------------------------------------------


def test_stream_write_commit(adapter: StorageAdapter):
    with adapter.open_writable_stream("streamed.bin") as w:
        assert isinstance(w, WritableObjectStream)
        w.write(b"hello, ")
        w.write(b"world")
        meta = w.commit()
    assert meta.size == len(b"hello, world")
    assert _read_all(adapter, "streamed.bin") == b"hello, world"


def test_stream_abort_leaves_no_object(adapter: StorageAdapter):
    with adapter.open_writable_stream("aborted.bin") as w:
        w.write(b"partial")
        w.abort()
    with pytest.raises(StorageError) as ei:
        adapter.head("aborted.bin")
    assert ei.value.kind == StorageErrorKind.NOT_FOUND.value


def test_stream_exception_treated_as_partial_upload(adapter: StorageAdapter):
    class Boom(RuntimeError):
        pass

    with pytest.raises(Boom):
        with adapter.open_writable_stream("boom.bin") as w:
            w.write(b"partial")
            raise Boom("simulated network drop")
    # 对象不应可见
    with pytest.raises(StorageError) as ei:
        adapter.head("boom.bin")
    assert ei.value.kind == StorageErrorKind.NOT_FOUND.value


# ---------------------------------------------------------------------------
# InvalidKey 拒绝
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_key",
    [
        "../escape.bin",
        "a/../../escape.bin",
        "/absolute.bin",
        "C:/windows/evil.bin",
        "a\\b\\c.bin",  # 反斜杠
        "with\x00null.bin",
        "",
    ],
)
def test_invalid_key_rejected_on_put(adapter: StorageAdapter, bad_key: str):
    with pytest.raises(StorageError) as ei:
        adapter.put(bad_key, b"x")
    assert ei.value.kind == StorageErrorKind.INVALID_KEY.value


def test_invalid_key_rejected_on_get(adapter: StorageAdapter):
    with pytest.raises(StorageError) as ei:
        list(adapter.get_stream("../escape.bin"))
    assert ei.value.kind == StorageErrorKind.INVALID_KEY.value


def test_invalid_key_rejected_on_delete(adapter: StorageAdapter):
    with pytest.raises(StorageError) as ei:
        adapter.delete("../escape.bin")
    assert ei.value.kind == StorageErrorKind.INVALID_KEY.value


def test_invalid_prefix_rejected_on_list(adapter: StorageAdapter):
    with pytest.raises(StorageError) as ei:
        adapter.list_prefix("../oops")
    assert ei.value.kind == StorageErrorKind.INVALID_KEY.value


def test_symlink_escape_rejected(adapter: StorageAdapter, tmp_path: Path):
    # Windows 上 os.symlink 需要开发者模式；无权限时跳过。
    if not isinstance(adapter, LocalDirAdapter):
        pytest.skip("symlink escape only meaningful for LocalDirAdapter")
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside_file = outside_dir / "secret.txt"
    outside_file.write_bytes(b"secret")
    root = adapter._root
    link_path = root / "bad-link"
    try:
        os.symlink(outside_dir, link_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink 创建失败（无权限或平台不支持）")
    with pytest.raises(StorageError) as ei:
        list(adapter.get_stream("bad-link/secret.txt"))
    assert ei.value.kind == StorageErrorKind.INVALID_KEY.value


# ---------------------------------------------------------------------------
# list_prefix：分页与 cursor
# ---------------------------------------------------------------------------


def test_list_prefix_pagination_and_cursor(adapter: StorageAdapter):
    # 种 10 个对象，两个不同前缀
    for i in range(6):
        adapter.put(f"g1/f{i:02d}.bin", f"g1-{i}".encode())
    for i in range(4):
        adapter.put(f"g2/f{i:02d}.bin", f"g2-{i}".encode())

    # 前缀过滤：g1/
    items, cursor = adapter.list_prefix("g1/", limit=1000)
    items = list(items)
    keys = [m.key for m in items]
    assert keys == sorted(keys)
    assert all(k.startswith("g1/") for k in keys)
    assert len(keys) == 6
    assert cursor is None

    # 分页：limit=3
    items1, cursor1 = adapter.list_prefix("g1/", limit=3)
    items1 = list(items1)
    assert len(items1) == 3
    assert cursor1 == items1[-1].key

    items2, cursor2 = adapter.list_prefix("g1/", cursor=cursor1, limit=3)
    items2 = list(items2)
    assert len(items2) == 3
    assert cursor2 is None
    # 两段并集覆盖全部 6 个
    all_keys = [m.key for m in items1] + [m.key for m in items2]
    assert sorted(set(all_keys)) == sorted([f"g1/f{i:02d}.bin" for i in range(6)])

    # 空 prefix：列全部 10 个
    items_all, cursor_all = adapter.list_prefix("", limit=1000)
    items_all = list(items_all)
    assert len(items_all) == 10
    assert cursor_all is None


def test_list_prefix_empty_result(adapter: StorageAdapter):
    items, cursor = adapter.list_prefix("nothing-here/")
    assert list(items) == []
    assert cursor is None


# ---------------------------------------------------------------------------
# copy 幂等
# ---------------------------------------------------------------------------


def test_copy_creates_target(adapter: StorageAdapter):
    src_meta = adapter.put("src/original.bin", b"payload-1")
    dst_meta = adapter.copy("src/original.bin", "dst/copy.bin")
    assert dst_meta.size == src_meta.size
    assert dst_meta.etag == src_meta.etag
    assert _read_all(adapter, "dst/copy.bin") == b"payload-1"


def test_copy_same_key_idempotent(adapter: StorageAdapter):
    src_meta = adapter.put("idem/one.bin", b"same")
    dst_meta = adapter.copy("idem/one.bin", "idem/one.bin")
    assert dst_meta.etag == src_meta.etag
    assert _read_all(adapter, "idem/one.bin") == b"same"


def test_copy_overwrite_false_same_content_idempotent(adapter: StorageAdapter):
    adapter.put("idem/src.bin", b"same-content")
    adapter.put("idem/dst.bin", b"same-content")
    meta = adapter.copy("idem/src.bin", "idem/dst.bin", overwrite=False)
    assert meta.size == len(b"same-content")


def test_copy_overwrite_false_different_content_conflict(adapter: StorageAdapter):
    adapter.put("idem2/src.bin", b"payload-A")
    adapter.put("idem2/dst.bin", b"payload-B")
    with pytest.raises(StorageError) as ei:
        adapter.copy("idem2/src.bin", "idem2/dst.bin", overwrite=False)
    assert ei.value.kind == StorageErrorKind.ALREADY_EXISTS.value


def test_copy_missing_source_notfound(adapter: StorageAdapter):
    with pytest.raises(StorageError) as ei:
        adapter.copy("no-such/src.bin", "dst/copy.bin")
    assert ei.value.kind == StorageErrorKind.NOT_FOUND.value


# ---------------------------------------------------------------------------
# presigned URL 治理期占位
# ---------------------------------------------------------------------------


def test_presigned_get_url_placeholder_shape(adapter: StorageAdapter):
    adapter.put("foo/bar.png", b"png")
    url = adapter.presigned_get_url("foo/bar.png")
    # 治理期占位：以 url_prefix 或 `/` 开头
    assert url.startswith("/")
    assert "foo/bar.png" in url


def test_presigned_put_url_placeholder_shape(adapter: StorageAdapter):
    url = adapter.presigned_put_url("foo/new.bin", content_type="application/octet-stream")
    assert url.startswith("/")
    assert "foo/new.bin" in url


# ---------------------------------------------------------------------------
# StorageErrorKind 枚举冻结
# ---------------------------------------------------------------------------


def test_storage_error_kind_enum_frozen():
    expected = {
        "NotFound",
        "AlreadyExists",
        "PreconditionFailed",
        "RateLimited",
        "Timeout",
        "PartialUpload",
        "IntegrityError",
        "Backend",
        "Forbidden",
        "InvalidKey",
    }
    got = {e.value for e in StorageErrorKind}
    assert got == expected


def test_storage_error_unknown_kind_rejected():
    with pytest.raises(ValueError):
        StorageError(kind="MysteryKind")


# ---------------------------------------------------------------------------
# 契约层禁止越权：不得导入 main
# ---------------------------------------------------------------------------


def test_base_module_does_not_import_main():
    import app.adapters.storage.base as base_mod

    # 若 base 模块曾 `from main import ...`，import 后 sys.modules 会有痕迹；
    # 这里做一次轻量断言：base 模块的 __dict__ 里不出现 main 相关引用。
    for name, value in vars(base_mod).items():
        module = getattr(value, "__module__", None)
        assert module != "main", f"base.{name} 意外来自 main"


def test_local_dir_module_does_not_import_main():
    import app.adapters.storage.local_dir as local_mod

    for name, value in vars(local_mod).items():
        module = getattr(value, "__module__", None)
        assert module != "main", f"local_dir.{name} 意外来自 main"


def test_minio_adapter_module_does_not_import_main():
    """MinioAdapter 模块级契约层不许出现 main 引用。

    本断言强制在 import 后立即成立；导入 minio_adapter 本身应无副作用。
    """
    import app.adapters.storage.minio_adapter as minio_mod

    for name, value in vars(minio_mod).items():
        module = getattr(value, "__module__", None)
        assert module != "main", f"minio_adapter.{name} 意外来自 main"
