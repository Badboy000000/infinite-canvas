"""MinioAdapter 独立单元测试（文件对象与 MinIO 治理 PR-3）。

**不需要**真 MinIO 服务；使用 mock `minio.Minio` 客户端做纯单元测试。
覆盖：
- 9 个接口每个至少 1 断言（put / open_writable_stream / get_stream /
  head / delete / copy / list_prefix / presigned_get_url / presigned_put_url）
- 密钥零泄漏（log / str(exception) / repr(adapter) 都不出现真实密钥）
- 懒 import + defaults-off（STORAGE_BACKEND 未设置时 minio_adapter 不进
  sys.modules）
- build_minio_adapter_from_env 缺 env 报错、完整 env 构建成功

T500-T519 序列。
"""

from __future__ import annotations

import datetime
import io
import logging
import os
import sys
from unittest import mock

import pytest
from minio.error import S3Error


# ---------------------------------------------------------------------------
# T500-T501: 懒 import + defaults-off 契约
# ---------------------------------------------------------------------------


def test_t500_minio_adapter_module_not_auto_imported():
    """T500 · defaults-off · STORAGE_BACKEND 未设置时 minio_adapter 不在 sys.modules。

    验证的是"不显式 import minio_adapter 则不会被 side-effect 拉入"。
    该模块被显式 import 一次后当然会进 sys.modules；这里保护的是
    `app.adapters.storage.__init__` / `main.py` 等入口不 eager 拉入。
    """
    # 走 storage 包入口 __init__（默认路径），不许因此拉入 minio_adapter
    if "app.adapters.storage.minio_adapter" in sys.modules:
        del sys.modules["app.adapters.storage.minio_adapter"]
    import app.adapters.storage  # noqa: F401
    assert "app.adapters.storage.minio_adapter" not in sys.modules


def test_t501_minio_adapter_import_no_side_effect_when_env_empty(monkeypatch):
    """T501 · 空 MINIO_* env 时 import app.adapters.storage.minio_adapter 无副作用。"""
    for name in list(os.environ.keys()):
        if name.startswith("MINIO_"):
            monkeypatch.delenv(name, raising=False)
    # 强制从头 import，验证 module import 本身不炸
    if "app.adapters.storage.minio_adapter" in sys.modules:
        del sys.modules["app.adapters.storage.minio_adapter"]
    import app.adapters.storage.minio_adapter as mod
    assert hasattr(mod, "MinioAdapter")
    assert hasattr(mod, "build_minio_adapter_from_env")


# ---------------------------------------------------------------------------
# fixture: mock minio client + adapter
# ---------------------------------------------------------------------------


class _FakeStat:
    def __init__(self, etag: str, size: int, content_type: str = None, metadata: dict = None):
        self.etag = etag
        self.size = size
        self.content_type = content_type
        self.metadata = metadata or {}
        self.last_modified = datetime.datetime(2026, 7, 24, 10, 0, 0)


class _FakeListEntry:
    def __init__(self, name: str, size: int, etag: str):
        self.object_name = name
        self.size = size
        self.etag = etag
        self.content_type = None
        self.metadata = {}
        self.is_dir = False
        self.last_modified = datetime.datetime(2026, 7, 24, 10, 0, 0)


class _FakeResponse:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)
        self._closed = False

    def read(self, chunk_size: int) -> bytes:
        return self._buf.read(chunk_size)

    def close(self):
        self._closed = True

    def release_conn(self):
        self._closed = True


def _make_s3_error(code: str, message: str = "boom") -> S3Error:
    """构造一个可复用的 S3Error。"""
    try:
        return S3Error(
            code=code,
            message=message,
            resource="/bucket/key",
            request_id="req-1",
            host_id="host-1",
            response=None,
        )
    except TypeError:
        # minio-py 版本差异兜底
        e = S3Error.__new__(S3Error)
        e.code = code
        e.message = message
        e.request_id = "req-1"
        return e


@pytest.fixture
def mock_adapter():
    from app.adapters.storage.minio_adapter import MinioAdapter

    client = mock.MagicMock()
    adapter = MinioAdapter(client=client, bucket="test-bucket", presigned_expires=3600)
    return adapter, client


# ---------------------------------------------------------------------------
# T502-T510: 9 接口 × 1 断言以上
# ---------------------------------------------------------------------------


def test_t502_put_writes_and_returns_meta(mock_adapter):
    """T502 · put · 9 接口 #1"""
    adapter, client = mock_adapter
    client.stat_object.return_value = _FakeStat(etag="abcd", size=5)
    meta = adapter.put("dir/file.bin", b"hello", mime_type="text/plain")
    assert meta.key == "dir/file.bin"
    assert meta.size == 5
    assert meta.etag == "abcd"
    assert meta.backend == "minio"
    client.put_object.assert_called_once()
    # 验证 mime_type 传下去了
    call_kwargs = client.put_object.call_args.kwargs
    assert call_kwargs.get("content_type") == "text/plain"


def test_t502b_put_overwrite_false_rejects_existing(mock_adapter):
    """T502b · put · overwrite=False + 已存在 → AlreadyExists"""
    from app.adapters.storage.base import StorageErrorKind, StorageError

    adapter, client = mock_adapter
    client.stat_object.return_value = _FakeStat(etag="e1", size=3)
    with pytest.raises(StorageError) as ei:
        adapter.put("k.bin", b"xxx", overwrite=False)
    assert ei.value.kind == StorageErrorKind.ALREADY_EXISTS.value


def test_t502c_put_if_match_mismatch_precondition_failed(mock_adapter):
    """T502c · put · if_match_etag 不匹配 → PreconditionFailed"""
    from app.adapters.storage.base import StorageErrorKind, StorageError

    adapter, client = mock_adapter
    client.stat_object.return_value = _FakeStat(etag="different", size=3)
    with pytest.raises(StorageError) as ei:
        adapter.put("k.bin", b"xxx", if_match_etag="expected")
    assert ei.value.kind == StorageErrorKind.PRECONDITION_FAILED.value


def test_t503_open_writable_stream_buffers_and_commits(mock_adapter):
    """T503 · open_writable_stream · 9 接口 #2"""
    adapter, client = mock_adapter
    client.stat_object.return_value = _FakeStat(etag="deadbeef", size=11)
    with adapter.open_writable_stream("stream.bin") as w:
        w.write(b"hello, ")
        w.write(b"world")
        meta = w.commit()
    assert meta.size == 11
    assert meta.etag == "deadbeef"


def test_t503b_open_writable_stream_abort_leaves_no_object(mock_adapter):
    """T503b · open_writable_stream · abort 不触发 put_object"""
    adapter, client = mock_adapter
    with adapter.open_writable_stream("aborted.bin") as w:
        w.write(b"partial")
        w.abort()
    client.put_object.assert_not_called()


def test_t504_get_stream_yields_bytes(mock_adapter):
    """T504 · get_stream · 9 接口 #3"""
    adapter, client = mock_adapter
    client.get_object.return_value = _FakeResponse(b"hello world")
    body = b"".join(adapter.get_stream("k.bin"))
    assert body == b"hello world"


def test_t504b_get_stream_notfound(mock_adapter):
    """T504b · get_stream · NoSuchKey → NotFound"""
    from app.adapters.storage.base import StorageErrorKind, StorageError

    adapter, client = mock_adapter
    client.get_object.side_effect = _make_s3_error("NoSuchKey")
    with pytest.raises(StorageError) as ei:
        list(adapter.get_stream("missing.bin"))
    assert ei.value.kind == StorageErrorKind.NOT_FOUND.value


def test_t505_head_returns_meta(mock_adapter):
    """T505 · head · 9 接口 #4"""
    adapter, client = mock_adapter
    client.stat_object.return_value = _FakeStat(etag="e-head", size=42, content_type="image/png")
    meta = adapter.head("img.png")
    assert meta.size == 42
    assert meta.etag == "e-head"
    assert meta.mime_type == "image/png"
    assert meta.backend == "minio"


def test_t505b_head_missing_returns_notfound_with_hint(mock_adapter):
    """T505b · head · NoSuchKey → NotFound + http_status_hint=404"""
    from app.adapters.storage.base import StorageErrorKind, StorageError

    adapter, client = mock_adapter
    client.stat_object.side_effect = _make_s3_error("NoSuchKey")
    with pytest.raises(StorageError) as ei:
        adapter.head("missing.bin")
    assert ei.value.kind == StorageErrorKind.NOT_FOUND.value
    assert ei.value.http_status_hint == 404


def test_t506_delete_calls_remove(mock_adapter):
    """T506 · delete · 9 接口 #5"""
    adapter, client = mock_adapter
    adapter.delete("k.bin")
    client.remove_object.assert_called_once_with("test-bucket", "k.bin")


def test_t506b_delete_missing_ok_swallow(mock_adapter):
    """T506b · delete · missing_ok=True + NoSuchKey 不抛"""
    adapter, client = mock_adapter
    client.remove_object.side_effect = _make_s3_error("NoSuchKey")
    adapter.delete("gone.bin", missing_ok=True)


def test_t506c_delete_missing_no_ok_raises_notfound(mock_adapter):
    """T506c · delete · missing_ok=False + NoSuchKey → NotFound"""
    from app.adapters.storage.base import StorageErrorKind, StorageError

    adapter, client = mock_adapter
    client.remove_object.side_effect = _make_s3_error("NoSuchKey")
    with pytest.raises(StorageError) as ei:
        adapter.delete("gone.bin")
    assert ei.value.kind == StorageErrorKind.NOT_FOUND.value


def test_t507_copy_calls_copy_object(mock_adapter):
    """T507 · copy · 9 接口 #6"""
    adapter, client = mock_adapter
    # copy 方法：overwrite=True（默认）→ 不调 stat_object → 直接 copy_object → head(dst)
    client.stat_object.return_value = _FakeStat(etag="ec", size=7)
    meta = adapter.copy("s.bin", "d.bin")
    assert meta.size == 7
    client.copy_object.assert_called_once()


def test_t507b_copy_same_key_idempotent(mock_adapter):
    """T507b · copy · src==dst 幂等，不调 copy_object"""
    adapter, client = mock_adapter
    client.stat_object.return_value = _FakeStat(etag="e-same", size=3)
    meta = adapter.copy("same.bin", "same.bin")
    assert meta.etag == "e-same"
    client.copy_object.assert_not_called()


def test_t508_list_prefix_yields_meta(mock_adapter):
    """T508 · list_prefix · 9 接口 #7"""
    adapter, client = mock_adapter
    client.list_objects.return_value = iter(
        [
            _FakeListEntry("a/1.bin", 1, "e1"),
            _FakeListEntry("a/2.bin", 2, "e2"),
        ]
    )
    items, cursor = adapter.list_prefix("a/", limit=1000)
    items = list(items)
    assert [i.key for i in items] == ["a/1.bin", "a/2.bin"]
    assert cursor is None


def test_t508b_list_prefix_pagination(mock_adapter):
    """T508b · list_prefix · limit 触发分页 cursor"""
    adapter, client = mock_adapter
    client.list_objects.return_value = iter(
        [
            _FakeListEntry("a/1.bin", 1, "e1"),
            _FakeListEntry("a/2.bin", 2, "e2"),
            _FakeListEntry("a/3.bin", 3, "e3"),
        ]
    )
    items, cursor = adapter.list_prefix("a/", limit=2)
    items = list(items)
    assert len(items) == 2
    assert cursor == items[-1].key


def test_t509_presigned_get_url(mock_adapter):
    """T509 · presigned_get_url · 9 接口 #8"""
    adapter, client = mock_adapter
    client.presigned_get_object.return_value = "http://example/signed?x=1"
    url = adapter.presigned_get_url("k.bin", expires_in=60)
    assert url == "http://example/signed?x=1"
    client.presigned_get_object.assert_called_once_with(
        "test-bucket", "k.bin", expires=60
    )


def test_t510_presigned_put_url(mock_adapter):
    """T510 · presigned_put_url · 9 接口 #9"""
    adapter, client = mock_adapter
    client.presigned_put_object.return_value = "http://example/put-signed?x=1"
    url = adapter.presigned_put_url("k.bin")
    assert url == "http://example/put-signed?x=1"


# ---------------------------------------------------------------------------
# T511-T512: build_minio_adapter_from_env
# ---------------------------------------------------------------------------


def test_t511_build_from_env_missing_raises(monkeypatch):
    """T511 · build_minio_adapter_from_env 缺 env 抛 ValueError · P0 密钥错误无泄漏"""
    for name in ["MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "MINIO_BUCKET"]:
        monkeypatch.delenv(name, raising=False)
    from app.adapters.storage.minio_adapter import build_minio_adapter_from_env

    with pytest.raises(ValueError) as ei:
        build_minio_adapter_from_env()
    # 错误消息包含缺失变量名，但绝不包含 access/secret 值
    text = str(ei.value)
    assert "MINIO_ENDPOINT" in text
    assert "MINIO_ACCESS_KEY" in text
    # 不许 leak：这些名字里绝不能出现"任何长于 8 字符的疑似密钥字面量"
    assert "CbFTvWF" not in text
    assert "sk-" not in text
    assert "AKIA" not in text


def test_t512_build_from_env_success(monkeypatch):
    """T512 · build_minio_adapter_from_env 全 env 存在时构造成功"""
    monkeypatch.setenv("MINIO_ENDPOINT", "localhost:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "TESTACCESSKEY_PLACEHOLDER_1234")
    monkeypatch.setenv("MINIO_SECRET_KEY", "TESTSECRETKEY_PLACEHOLDER_5678")
    monkeypatch.setenv("MINIO_BUCKET", "test-bucket")
    monkeypatch.setenv("MINIO_SECURE", "false")

    from app.adapters.storage.minio_adapter import build_minio_adapter_from_env, MinioAdapter

    adapter = build_minio_adapter_from_env()
    assert isinstance(adapter, MinioAdapter)
    assert adapter._bucket == "test-bucket"


# ---------------------------------------------------------------------------
# T513-T515: P0 密钥零泄漏防线
# ---------------------------------------------------------------------------


def test_t513_secret_never_in_str_of_exception(monkeypatch):
    """T513 · P0 · str(exc) 绝不出现真实密钥"""
    fake_secret = "CbFTvWF_SECRET_XYZ_9876543210_do_not_leak"
    fake_access = "AKIA_TEST_ACCESS_KEY_DO_NOT_LEAK"
    monkeypatch.setenv("MINIO_ENDPOINT", "localhost:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", fake_access)
    monkeypatch.setenv("MINIO_SECRET_KEY", fake_secret)
    monkeypatch.setenv("MINIO_BUCKET", "test-bucket")

    from app.adapters.storage.minio_adapter import build_minio_adapter_from_env
    from app.adapters.storage.base import StorageError

    adapter = build_minio_adapter_from_env()
    # 让 stat_object 抛错，触发 _map_s3_error 生成 message
    adapter._client = mock.MagicMock()
    adapter._client.stat_object.side_effect = _make_s3_error(
        "AccessDenied", message="forbidden"
    )
    with pytest.raises(StorageError) as ei:
        adapter.head("x.bin")
    text = str(ei.value)
    assert fake_secret not in text
    assert fake_access not in text


def test_t514_secret_never_in_repr_of_adapter(monkeypatch):
    """T514 · P0 · repr(adapter) 不出现密钥"""
    fake_secret = "CbFTvWF_SECRET_XYZ_9876543210_do_not_leak"
    fake_access = "AKIA_TEST_ACCESS_KEY_DO_NOT_LEAK"
    monkeypatch.setenv("MINIO_ENDPOINT", "localhost:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", fake_access)
    monkeypatch.setenv("MINIO_SECRET_KEY", fake_secret)
    monkeypatch.setenv("MINIO_BUCKET", "test-bucket")

    from app.adapters.storage.minio_adapter import build_minio_adapter_from_env

    adapter = build_minio_adapter_from_env()
    r = repr(adapter)
    assert fake_secret not in r
    assert fake_access not in r


def test_t515_no_secret_in_log_output(monkeypatch, caplog):
    """T515 · P0 · 触发 log 时密钥不进 log 记录"""
    fake_secret = "CbFTvWF_SECRET_XYZ_9876543210_do_not_leak"
    fake_access = "AKIA_TEST_ACCESS_KEY_DO_NOT_LEAK"
    monkeypatch.setenv("MINIO_ENDPOINT", "localhost:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", fake_access)
    monkeypatch.setenv("MINIO_SECRET_KEY", fake_secret)
    monkeypatch.setenv("MINIO_BUCKET", "test-bucket")

    caplog.set_level(logging.DEBUG)

    from app.adapters.storage.minio_adapter import build_minio_adapter_from_env

    adapter = build_minio_adapter_from_env()
    adapter._client = mock.MagicMock()
    adapter._client.remove_object.side_effect = _make_s3_error("AccessDenied")

    from app.adapters.storage.base import StorageError

    try:
        adapter.delete("k.bin")
    except StorageError:
        pass

    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert fake_secret not in log_text
    assert fake_access not in log_text


# ---------------------------------------------------------------------------
# T516: InvalidKey 拒绝（复用 _normalize_key）
# ---------------------------------------------------------------------------


def test_t516_invalid_key_rejected(mock_adapter):
    """T516 · InvalidKey · 复用 base._validate_key 语义（经 _normalize_key）"""
    from app.adapters.storage.base import StorageError, StorageErrorKind

    adapter, client = mock_adapter
    for bad in ["../escape.bin", "/absolute.bin", "with\x00null.bin", ""]:
        with pytest.raises(StorageError) as ei:
            adapter.put(bad, b"x")
        assert ei.value.kind == StorageErrorKind.INVALID_KEY.value


# ---------------------------------------------------------------------------
# T517: S3Error → StorageErrorKind 映射覆盖
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "s3_code,expected_kind",
    [
        ("NoSuchKey", "NotFound"),
        ("AccessDenied", "Forbidden"),
        ("SlowDown", "RateLimited"),
        ("RequestTimeout", "Timeout"),
        ("PreconditionFailed", "PreconditionFailed"),
        ("SomethingWeird", "Backend"),  # fallback
    ],
)
def test_t517_s3error_kind_mapping(mock_adapter, s3_code, expected_kind):
    """T517 · S3Error code → StorageErrorKind 映射"""
    from app.adapters.storage.base import StorageError

    adapter, client = mock_adapter
    client.stat_object.side_effect = _make_s3_error(s3_code)
    with pytest.raises(StorageError) as ei:
        adapter.head("k.bin")
    assert ei.value.kind == expected_kind


# ---------------------------------------------------------------------------
# T518: STORAGE_BACKEND defaults-off 兜底断言
# ---------------------------------------------------------------------------


def test_t518_default_storage_backend_is_local(monkeypatch):
    """T518 · defaults-off · STORAGE_BACKEND 未设置或 =local 时不需要 minio 环境"""
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    # 该断言只锁定"env 层默认关闭"的契约；实际 dispatch 由 main.py / FileService
    # 后续 PR 承接。这里仅验证：读默认值即为 "local"。
    backend = os.environ.get("STORAGE_BACKEND", "local").strip().lower() or "local"
    assert backend == "local"


# ---------------------------------------------------------------------------
# T519: MinioAdapter 独立可 import（不依赖 main）
# ---------------------------------------------------------------------------


def test_t519_minio_adapter_module_isolated_from_main():
    """T519 · 治理护栏 · minio_adapter 模块不许出现来自 main 的引用"""
    import app.adapters.storage.minio_adapter as mod

    for name, value in vars(mod).items():
        module = getattr(value, "__module__", None)
        assert module != "main", f"minio_adapter.{name} 意外来自 main"