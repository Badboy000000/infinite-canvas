"""MinioAdapter（文件对象与 MinIO 治理 PR-3 · Wave 3-N.9 Batch 1 主线 A）。

稳定期 MinIO 后端实现，把 StorageAdapter 契约落在 S3-compatible 对象存储上。
本模块只在 `STORAGE_BACKEND=minio` 时被懒 import；默认路径下 `sys.modules` 无
本模块，保证零副作用。

约束：
- 本模块只依赖标准库 + `minio-py`（已作为项目依赖安装）。
- 不导入 `main`。
- P0 密钥零泄漏：access/secret 只从 `os.environ` 读；任何日志/错误/repr 不
  出现真实密钥。
- 复用 `base._validate_key` 做 key 校验（不重复实现）。
"""

from __future__ import annotations

import io
import os
from contextlib import contextmanager
from typing import ContextManager, Iterable, Iterator, Optional, Tuple

from minio import Minio
from minio.error import S3Error

from .base import (
    ObjectMeta,
    StorageAdapter,
    StorageError,
    StorageErrorKind,
    WritableObjectStream,
)
from .local_dir import _normalize_key

# ---------------------------------------------------------------------------
# MinIO S3 error → StorageErrorKind 映射
# ---------------------------------------------------------------------------

# 参考 minio-py S3Error.code 常见值；此处只映射我们已定义的 10 种 kind。
_S3_CODE_TO_KIND: dict[str, StorageErrorKind] = {
    "NoSuchKey": StorageErrorKind.NOT_FOUND,
    "NotFound": StorageErrorKind.NOT_FOUND,
    "BucketAlreadyExists": StorageErrorKind.ALREADY_EXISTS,
    "BucketAlreadyOwnedByYou": StorageErrorKind.ALREADY_EXISTS,
    "PreconditionFailed": StorageErrorKind.PRECONDITION_FAILED,
    "SlowDown": StorageErrorKind.RATE_LIMITED,
    "RequestTimeout": StorageErrorKind.TIMEOUT,
    "AccessDenied": StorageErrorKind.FORBIDDEN,
    "SignatureDoesNotMatch": StorageErrorKind.FORBIDDEN,
    "InvalidAccessKeyId": StorageErrorKind.FORBIDDEN,
}


def _map_s3_error(exc: S3Error, key: Optional[str] = None) -> StorageError:
    """把 minio S3Error 映射到 StorageError。

    P0 防线：message 只用 `S3Error.code`，不携带 access/secret 原文。
    """
    code = getattr(exc, "code", "") or ""
    kind = _S3_CODE_TO_KIND.get(code, StorageErrorKind.BACKEND)
    return StorageError(
        kind=kind,
        key=key,
        cause=exc,
        retryable=kind
        in (StorageErrorKind.RATE_LIMITED, StorageErrorKind.TIMEOUT, StorageErrorKind.BACKEND),
        http_status_hint=_http_status_for_kind(kind),
        request_id=getattr(exc, "request_id", None),
        message=f"[{kind.value}] MinIO code={code}" + (f" key={key!r}" if key else ""),
    )


_HTTP_STATUS_MAP: dict[StorageErrorKind, int] = {
    StorageErrorKind.NOT_FOUND: 404,
    StorageErrorKind.ALREADY_EXISTS: 409,
    StorageErrorKind.PRECONDITION_FAILED: 412,
    StorageErrorKind.RATE_LIMITED: 429,
    StorageErrorKind.TIMEOUT: 504,
    StorageErrorKind.FORBIDDEN: 403,
    StorageErrorKind.INVALID_KEY: 400,
}


def _http_status_for_kind(kind: StorageErrorKind) -> Optional[int]:
    return _HTTP_STATUS_MAP.get(kind)


# ---------------------------------------------------------------------------
# MinioWritableStream
# ---------------------------------------------------------------------------


class _MinioWritableStream(WritableObjectStream):
    """MinioAdapter 流式写入实现。

    使用内存 BytesIO 缓冲，close 时一次性 put_object。
    后续 PR 再改流式 multipart upload。
    """

    def __init__(
        self,
        adapter: "MinioAdapter",
        key: str,
        overwrite: bool,
        if_match_etag: Optional[str],
        mime_type: Optional[str],
    ) -> None:
        self._adapter = adapter
        self._key = key
        self._overwrite = overwrite
        self._if_match = if_match_etag
        self._mime = mime_type
        self._finalized = False
        self._aborted = False
        self._buffer = io.BytesIO()

    def write(self, chunk: bytes) -> int:
        if self._finalized:
            raise StorageError(
                kind=StorageErrorKind.BACKEND,
                key=self._key,
                message="[Backend] stream already finalized",
            )
        if not chunk:
            return 0
        self._buffer.write(chunk)
        return len(chunk)

    def abort(self) -> None:
        if self._finalized:
            return
        self._finalized = True
        self._aborted = True
        self._buffer.close()

    def commit(self) -> ObjectMeta:
        if self._finalized:
            if self._aborted:
                raise StorageError(
                    kind=StorageErrorKind.PARTIAL_UPLOAD,
                    key=self._key,
                    message="[PartialUpload] stream already aborted",
                )
            # 已 commit，幂等返回 head
            return self._adapter.head(self._key)
        self._finalized = True
        data = self._buffer.getvalue()
        self._buffer.close()
        return self._adapter.put(
            self._key,
            data,
            mime_type=self._mime,
            overwrite=self._overwrite,
            if_match_etag=self._if_match,
        )


# ---------------------------------------------------------------------------
# MinioAdapter
# ---------------------------------------------------------------------------


class MinioAdapter(StorageAdapter):
    """把 StorageAdapter 契约落在 MinIO / S3 兼容对象存储上。

    通过 `build_minio_adapter_from_env()` 从环境变量构建，需要：
    - `MINIO_ENDPOINT`：MinIO 服务端地址（含协议，如 `http://localhost:9000`）
    - `MINIO_ACCESS_KEY`：access key
    - `MINIO_SECRET_KEY`：secret key
    - `MINIO_BUCKET`：默认 bucket 名称
    - `MINIO_SECURE`（可选）：true/false（默认 false）
    - `MINIO_REGION`（可选）：区域（默认空）
    - `MINIO_PRESIGNED_EXPIRES`（可选）：签名 URL 有效期秒数（默认 3600）
    """

    backend_name = "minio"

    def __init__(
        self,
        client: Minio,
        bucket: str,
        *,
        presigned_expires: int = 3600,
    ) -> None:
        self._client = client
        self._bucket = bucket
        self._presigned_expires = int(presigned_expires)
        if self._presigned_expires <= 0:
            self._presigned_expires = 3600

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def put(
        self,
        key: str,
        data: bytes,
        *,
        mime_type: Optional[str] = None,
        overwrite: bool = True,
        if_match_etag: Optional[str] = None,
    ) -> ObjectMeta:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise StorageError(
                kind=StorageErrorKind.BACKEND,
                key=key,
                message="[Backend] put(data) 必须是 bytes-like",
            )
        norm = _normalize_key(key)
        if not overwrite or if_match_etag is not None:
            # 需要前置 head 检查 overwrite / etag 条件
            try:
                existing = self._client.stat_object(self._bucket, norm)
            except S3Error as exc:
                if getattr(exc, "code", "") == "NoSuchKey":
                    existing = None
                else:
                    raise _map_s3_error(exc, key=norm)
            if existing is not None:
                if not overwrite:
                    raise StorageError(
                        kind=StorageErrorKind.ALREADY_EXISTS,
                        key=norm,
                        http_status_hint=409,
                    )
                if if_match_etag is not None and existing.etag != if_match_etag:
                    raise StorageError(
                        kind=StorageErrorKind.PRECONDITION_FAILED,
                        key=norm,
                        http_status_hint=412,
                    )
        try:
            put_result = self._client.put_object(
                self._bucket,
                norm,
                io.BytesIO(data),
                length=len(data),
                content_type=mime_type or "application/octet-stream",
            )
        except S3Error as exc:
            raise _map_s3_error(exc, key=norm)
        # 再 stat 一次拿 etag / mtime / size
        try:
            stat = self._client.stat_object(self._bucket, norm)
        except S3Error as exc:
            raise _map_s3_error(exc, key=norm)
        return ObjectMeta(
            key=norm,
            size=stat.size,
            etag=stat.etag or "",
            mime_type=mime_type,
            last_modified_ms=_mtime_ms(stat.last_modified),
            backend=self.backend_name,
        )

    @contextmanager
    def open_writable_stream(
        self,
        key: str,
        *,
        mime_type: Optional[str] = None,
        overwrite: bool = True,
        if_match_etag: Optional[str] = None,
    ):
        norm = _normalize_key(key)
        writer = _MinioWritableStream(
            adapter=self,
            key=norm,
            overwrite=overwrite,
            if_match_etag=if_match_etag,
            mime_type=mime_type,
        )
        try:
            yield writer
        except BaseException:
            writer.abort()
            raise
        else:
            if not writer._finalized:
                writer.commit()

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------

    def get_stream(
        self,
        key: str,
        *,
        offset: int = 0,
        length: Optional[int] = None,
    ) -> Iterator[bytes]:
        norm = _normalize_key(key)
        try:
            response = self._client.get_object(
                self._bucket,
                norm,
                offset=offset,
                length=length,
            )
        except S3Error as exc:
            raise _map_s3_error(exc, key=norm)
        try:
            # 按 chunk 迭代
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            response.close()
            response.release_conn()

    def head(self, key: str) -> ObjectMeta:
        norm = _normalize_key(key)
        try:
            stat = self._client.stat_object(self._bucket, norm)
        except S3Error as exc:
            raise _map_s3_error(exc, key=norm)
        return ObjectMeta(
            key=norm,
            size=stat.size,
            etag=stat.etag or "",
            mime_type=stat.content_type,
            last_modified_ms=_mtime_ms(stat.last_modified),
            backend=self.backend_name,
            extra=stat.metadata or {},
        )

    # ------------------------------------------------------------------
    # 变更
    # ------------------------------------------------------------------

    def delete(self, key: str, *, missing_ok: bool = False) -> None:
        norm = _normalize_key(key)
        try:
            self._client.remove_object(self._bucket, norm)
        except S3Error as exc:
            code = getattr(exc, "code", "")
            if code == "NoSuchKey" and missing_ok:
                return
            raise _map_s3_error(exc, key=norm)

    def copy(
        self,
        src_key: str,
        dst_key: str,
        *,
        overwrite: bool = True,
    ) -> ObjectMeta:
        src_norm = _normalize_key(src_key)
        dst_norm = _normalize_key(dst_key)
        if src_norm == dst_norm:
            # 幂等
            return self.head(src_norm)
        if not overwrite:
            try:
                self._client.stat_object(self._bucket, dst_norm)
            except S3Error as exc:
                code = getattr(exc, "code", "")
                if code != "NoSuchKey":
                    raise _map_s3_error(exc, key=dst_norm)
            else:
                # 目标存在；检查是否同内容
                src_meta = self.head(src_norm)
                dst_meta = self.head(dst_norm)
                if src_meta.etag == dst_meta.etag and src_meta.size == dst_meta.size:
                    return dst_meta
                raise StorageError(
                    kind=StorageErrorKind.ALREADY_EXISTS,
                    key=dst_norm,
                    http_status_hint=409,
                )
        try:
            self._client.copy_object(
                self._bucket,
                dst_norm,
                f"{self._bucket}/{src_norm}",
            )
        except S3Error as exc:
            raise _map_s3_error(exc, key=dst_norm)
        return self.head(dst_norm)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list_prefix(
        self,
        prefix: str,
        *,
        cursor: Optional[str] = None,
        limit: int = 1000,
    ) -> Tuple[Iterable[ObjectMeta], Optional[str]]:
        if limit <= 0:
            limit = 1
        norm_prefix = ""
        if prefix:
            if "\\" in prefix or "\x00" in prefix:
                raise StorageError(
                    kind=StorageErrorKind.INVALID_KEY,
                    key=prefix,
                    message=f"[InvalidKey] prefix={prefix!r} 包含非法字符",
                )
            if prefix.startswith("/"):
                raise StorageError(
                    kind=StorageErrorKind.INVALID_KEY,
                    key=prefix,
                    message=f"[InvalidKey] prefix={prefix!r} 禁止绝对路径",
                )
            norm_prefix = prefix.rstrip("/")
        try:
            objects = self._client.list_objects(
                self._bucket,
                prefix=norm_prefix,
                start_after=cursor or "",
                recursive=True,
            )
        except S3Error as exc:
            raise _map_s3_error(exc, key=prefix)
        collected: list[ObjectMeta] = []
        next_cursor: Optional[str] = None
        for obj in objects:
            if obj.is_dir:
                continue
            if len(collected) >= limit:
                next_cursor = collected[-1].key
                return collected, next_cursor
            collected.append(
                ObjectMeta(
                    key=obj.object_name or "",
                    size=obj.size,
                    etag=obj.etag or "",
                    mime_type=obj.content_type,
                    last_modified_ms=_mtime_ms(obj.last_modified),
                    backend=self.backend_name,
                    extra=obj.metadata or {},
                )
            )
        return collected, None

    # ------------------------------------------------------------------
    # URL 签名
    # ------------------------------------------------------------------

    def presigned_get_url(
        self,
        key: str,
        *,
        expires_in: Optional[int] = None,
    ) -> str:
        norm = _normalize_key(key)
        expires = expires_in if expires_in is not None else self._presigned_expires
        try:
            return self._client.presigned_get_object(
                self._bucket,
                norm,
                expires=expires,
            )
        except S3Error as exc:
            raise _map_s3_error(exc, key=norm)

    def presigned_put_url(
        self,
        key: str,
        *,
        expires_in: Optional[int] = None,
        content_type: Optional[str] = None,
    ) -> str:
        norm = _normalize_key(key)
        expires = expires_in if expires_in is not None else self._presigned_expires
        try:
            return self._client.presigned_put_object(
                self._bucket,
                norm,
                expires=expires,
            )
        except S3Error as exc:
            raise _map_s3_error(exc, key=norm)


# ---------------------------------------------------------------------------
# 从环境构建
# ---------------------------------------------------------------------------


def build_minio_adapter_from_env() -> MinioAdapter:
    """从环境变量构建 MinioAdapter。

    读取变量：
    - `MINIO_ENDPOINT`（必需）：如 `http://localhost:9000`
    - `MINIO_ACCESS_KEY`（必需）
    - `MINIO_SECRET_KEY`（必需）
    - `MINIO_BUCKET`（必需）
    - `MINIO_SECURE`（可选，默认 false）
    - `MINIO_REGION`（可选，默认空）
    - `MINIO_PRESIGNED_EXPIRES`（可选，默认 3600）

    Raises:
        ValueError: 必需环境变量缺失。
    """
    endpoint = os.environ.get("MINIO_ENDPOINT")
    access_key = os.environ.get("MINIO_ACCESS_KEY")
    secret_key = os.environ.get("MINIO_SECRET_KEY")
    bucket = os.environ.get("MINIO_BUCKET")

    missing = []
    if not endpoint:
        missing.append("MINIO_ENDPOINT")
    if not access_key:
        missing.append("MINIO_ACCESS_KEY")
    if not secret_key:
        missing.append("MINIO_SECRET_KEY")
    if not bucket:
        missing.append("MINIO_BUCKET")
    if missing:
        raise ValueError(f"缺少必需的环境变量: {', '.join(missing)}")

    secure = os.environ.get("MINIO_SECURE", "false").strip().lower() in ("true", "1", "yes")
    region = os.environ.get("MINIO_REGION", None)
    expires_raw = os.environ.get("MINIO_PRESIGNED_EXPIRES", "3600")
    try:
        presigned_expires = int(expires_raw)
    except ValueError:
        presigned_expires = 3600

    # minio-py 要求 endpoint 只有 host[:port] 部分，不许带 scheme；
    # 是否 https 由 `secure` 决定。若 MINIO_ENDPOINT 带了 http:// / https:// 前缀
    # 就在这里剥掉；scheme 覆盖 MINIO_SECURE 的默认值（除非用户显式设置了）。
    stripped_endpoint = endpoint
    if endpoint.startswith("https://"):
        stripped_endpoint = endpoint[len("https://"):]
        if "MINIO_SECURE" not in os.environ:
            secure = True
    elif endpoint.startswith("http://"):
        stripped_endpoint = endpoint[len("http://"):]
        if "MINIO_SECURE" not in os.environ:
            secure = False
    # 去掉可能的尾部 `/`（minio-py 不接受 path）
    stripped_endpoint = stripped_endpoint.rstrip("/")

    client = Minio(
        endpoint=stripped_endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
        region=region,
    )
    return MinioAdapter(
        client=client,
        bucket=bucket,
        presigned_expires=presigned_expires,
    )


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _mtime_ms(last_modified) -> Optional[int]:
    """把 minio stat 返回的 last_modified (datetime) 转为毫秒时间戳。"""
    if last_modified is None:
        return None
    import datetime

    if isinstance(last_modified, datetime.datetime):
        return int(last_modified.timestamp() * 1000)
    return None


__all__ = ["MinioAdapter", "build_minio_adapter_from_env"]