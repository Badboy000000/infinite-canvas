"""治理期 LocalDirAdapter：把 StorageAdapter 契约落在本地目录上。

治理期与稳定期分工：
- Local：底层是文件系统；`presigned_get_url` 返回 `/{url_prefix}/{key}`
  或 `/assets/{key}` / `/output/{key}` 前缀占位，由 FastAPI 静态挂载消费。
- MinIO（PR-8 承接）：底层是 S3；签名 URL 走 MinIO 服务端。

**约束**：
- 本模块只用标准库，不导入 `main`。
- 内部路径处理拒绝路径穿越（`..`、绝对路径、盘符、反斜杠、空字节、
  经解析后跳出 root 的符号链接目标），命中即 raise `InvalidKey`。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator, Optional, Tuple
from urllib.parse import quote

from .base import (
    ObjectMeta,
    StorageAdapter,
    StorageError,
    StorageErrorKind,
    WritableObjectStream,
)


_DEFAULT_CHUNK_SIZE = 64 * 1024
_INVALID_KEY_CHARS = ("\x00", "\\")


def _reject(key: str, reason: str) -> "StorageError":
    return StorageError(
        kind=StorageErrorKind.INVALID_KEY,
        key=key,
        message=f"[InvalidKey] key={key!r}: {reason}",
    )


def _normalize_key(key: str) -> str:
    """把 key 归一化到 POSIX 相对路径；违反契约立即 raise InvalidKey。"""

    if not isinstance(key, str):
        raise _reject(str(key), "key 必须是字符串")
    if not key:
        raise _reject(key, "key 不能为空")
    for ch in _INVALID_KEY_CHARS:
        if ch in key:
            raise _reject(key, f"包含非法字符 {ch!r}")
    if key.startswith("/"):
        raise _reject(key, "禁止绝对路径")
    if len(key) >= 2 and key[1] == ":":
        raise _reject(key, "禁止盘符前缀")
    # 用 PurePosixPath 归一化，检查是否有 `..` 段
    pure = PurePosixPath(key)
    parts = pure.parts
    if any(p == ".." for p in parts):
        raise _reject(key, "包含 `..` 段")
    if any(p == "" for p in parts):
        raise _reject(key, "包含空段")
    if parts and parts[0].startswith("/"):
        raise _reject(key, "禁止绝对路径")
    return str(pure)


class _LocalWritableStream(WritableObjectStream):
    """LocalDirAdapter 的流式写入实现。

    先写入 `${target}.__tmp_${suffix}` 临时文件，`commit` 时原子 rename。
    `abort` 或异常离开时删除临时文件——保证不留 partial 对象。
    """

    def __init__(
        self,
        adapter: "LocalDirAdapter",
        key: str,
        abs_target: Path,
        overwrite: bool,
        if_match_etag: Optional[str],
        mime_type: Optional[str],
    ) -> None:
        self._adapter = adapter
        self._key = key
        self._target = abs_target
        self._overwrite = overwrite
        self._if_match = if_match_etag
        self._mime = mime_type
        self._finalized = False
        self._aborted = False
        self._bytes_written = 0
        self._digest = hashlib.sha256()
        self._tmp_path: Optional[Path] = None
        self._tmp_fh = None
        self._prepare()

    def _prepare(self) -> None:
        adapter = self._adapter
        target = self._target
        # 前置校验 overwrite / if_match_etag
        if target.exists():
            if not self._overwrite:
                raise StorageError(
                    kind=StorageErrorKind.ALREADY_EXISTS,
                    key=self._key,
                    http_status_hint=409,
                )
            if self._if_match is not None:
                current_meta = adapter._head_from_path(self._key, target)
                if current_meta.etag != self._if_match:
                    raise StorageError(
                        kind=StorageErrorKind.PRECONDITION_FAILED,
                        key=self._key,
                        http_status_hint=412,
                    )
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=target.name + ".",
            suffix=".__tmp",
            dir=str(target.parent),
        )
        self._tmp_path = Path(tmp_name)
        self._tmp_fh = os.fdopen(fd, "wb")

    def write(self, chunk: bytes) -> int:
        if self._finalized:
            raise StorageError(
                kind=StorageErrorKind.BACKEND,
                key=self._key,
                message="[Backend] stream already finalized",
            )
        if not chunk:
            return 0
        try:
            self._tmp_fh.write(chunk)
        except OSError as exc:
            self.abort()
            raise StorageError(
                kind=StorageErrorKind.PARTIAL_UPLOAD,
                key=self._key,
                cause=exc,
                retryable=True,
            ) from exc
        self._bytes_written += len(chunk)
        self._digest.update(chunk)
        return len(chunk)

    def abort(self) -> None:
        if self._finalized:
            return
        self._finalized = True
        self._aborted = True
        try:
            if self._tmp_fh is not None:
                try:
                    self._tmp_fh.close()
                except OSError:
                    pass
        finally:
            if self._tmp_path is not None and self._tmp_path.exists():
                try:
                    self._tmp_path.unlink()
                except OSError:
                    pass

    def commit(self) -> ObjectMeta:
        if self._finalized:
            if self._aborted:
                raise StorageError(
                    kind=StorageErrorKind.PARTIAL_UPLOAD,
                    key=self._key,
                    message="[PartialUpload] stream already aborted",
                )
            # 已 commit 幂等
            return self._adapter._head_from_path(self._key, self._target)
        self._finalized = True
        try:
            self._tmp_fh.flush()
            os.fsync(self._tmp_fh.fileno())
            self._tmp_fh.close()
        except OSError as exc:
            # commit 阶段失败：清理临时文件，报 PartialUpload。
            if self._tmp_path is not None and self._tmp_path.exists():
                try:
                    self._tmp_path.unlink()
                except OSError:
                    pass
            raise StorageError(
                kind=StorageErrorKind.PARTIAL_UPLOAD,
                key=self._key,
                cause=exc,
                retryable=True,
            ) from exc
        try:
            os.replace(self._tmp_path, self._target)
        except OSError as exc:
            if self._tmp_path is not None and self._tmp_path.exists():
                try:
                    self._tmp_path.unlink()
                except OSError:
                    pass
            raise StorageError(
                kind=StorageErrorKind.BACKEND,
                key=self._key,
                cause=exc,
                retryable=True,
            ) from exc
        etag = self._digest.hexdigest()[:32]
        try:
            stat = self._target.stat()
        except OSError as exc:
            raise StorageError(
                kind=StorageErrorKind.BACKEND,
                key=self._key,
                cause=exc,
            ) from exc
        return ObjectMeta(
            key=self._key,
            size=self._bytes_written,
            etag=etag,
            mime_type=self._mime,
            last_modified_ms=int(stat.st_mtime * 1000),
            backend=self._adapter.backend_name,
        )


class LocalDirAdapter(StorageAdapter):
    """把 StorageAdapter 契约落在本地目录上（治理期主力实现）。"""

    backend_name = "local"

    def __init__(
        self,
        root: str | os.PathLike,
        *,
        url_prefix: str = "/assets",
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
    ) -> None:
        root_path = Path(os.fspath(root)).expanduser().resolve()
        if not root_path.exists():
            root_path.mkdir(parents=True, exist_ok=True)
        if not root_path.is_dir():
            raise StorageError(
                kind=StorageErrorKind.BACKEND,
                key=None,
                message=f"[Backend] root 不是目录: {root_path}",
            )
        self._root = root_path
        # url_prefix 归一化：必须以 `/` 开头，不以 `/` 结尾。
        if not url_prefix:
            url_prefix = "/"
        if not url_prefix.startswith("/"):
            url_prefix = "/" + url_prefix
        self._url_prefix = url_prefix.rstrip("/") or ""
        if chunk_size <= 0:
            chunk_size = _DEFAULT_CHUNK_SIZE
        self._chunk_size = int(chunk_size)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _resolve(self, key: str) -> Path:
        """把 key 解析为 root 内部的绝对路径；越界 raise InvalidKey。"""

        norm = _normalize_key(key)
        candidate = (self._root / norm).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError:
            raise _reject(key, "path 解析后跳出 root（可能是符号链接指向外部）")
        return candidate

    def _head_from_path(self, key: str, path: Path) -> ObjectMeta:
        try:
            stat = path.stat()
        except FileNotFoundError as exc:
            raise StorageError(
                kind=StorageErrorKind.NOT_FOUND,
                key=key,
                cause=exc,
                http_status_hint=404,
            ) from exc
        except OSError as exc:
            raise StorageError(
                kind=StorageErrorKind.BACKEND,
                key=key,
                cause=exc,
            ) from exc
        digest = hashlib.sha256()
        try:
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(self._chunk_size), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise StorageError(
                kind=StorageErrorKind.BACKEND,
                key=key,
                cause=exc,
            ) from exc
        return ObjectMeta(
            key=key,
            size=stat.st_size,
            etag=digest.hexdigest()[:32],
            mime_type=None,
            last_modified_ms=int(stat.st_mtime * 1000),
            backend=self.backend_name,
        )

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
        target = self._resolve(key)
        with self.open_writable_stream(
            key,
            mime_type=mime_type,
            overwrite=overwrite,
            if_match_etag=if_match_etag,
        ) as writer:
            if data:
                writer.write(bytes(data))
            meta = writer.commit()
        _ = target  # already resolved above; the writer targets same path
        return meta

    @contextmanager
    def open_writable_stream(
        self,
        key: str,
        *,
        mime_type: Optional[str] = None,
        overwrite: bool = True,
        if_match_etag: Optional[str] = None,
    ):
        target = self._resolve(key)
        writer = _LocalWritableStream(
            adapter=self,
            key=_normalize_key(key),
            abs_target=target,
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
        target = self._resolve(key)
        if not target.exists() or not target.is_file():
            raise StorageError(
                kind=StorageErrorKind.NOT_FOUND,
                key=key,
                http_status_hint=404,
            )
        return self._iter_file(target, offset=offset, length=length)

    def _iter_file(
        self,
        path: Path,
        *,
        offset: int,
        length: Optional[int],
    ) -> Iterator[bytes]:
        if offset < 0:
            raise StorageError(
                kind=StorageErrorKind.BACKEND,
                key=str(path),
                message="[Backend] offset 不能为负",
            )
        remaining = length if length is not None else -1
        try:
            with path.open("rb") as fh:
                if offset:
                    fh.seek(offset)
                while True:
                    if remaining == 0:
                        break
                    read_size = self._chunk_size
                    if remaining > 0:
                        read_size = min(read_size, remaining)
                    chunk = fh.read(read_size)
                    if not chunk:
                        break
                    if remaining > 0:
                        remaining -= len(chunk)
                    yield chunk
        except OSError as exc:
            raise StorageError(
                kind=StorageErrorKind.BACKEND,
                key=str(path),
                cause=exc,
                retryable=True,
            ) from exc

    def head(self, key: str) -> ObjectMeta:
        target = self._resolve(key)
        if not target.exists() or not target.is_file():
            raise StorageError(
                kind=StorageErrorKind.NOT_FOUND,
                key=key,
                http_status_hint=404,
            )
        return self._head_from_path(_normalize_key(key), target)

    # ------------------------------------------------------------------
    # 变更
    # ------------------------------------------------------------------

    def delete(self, key: str, *, missing_ok: bool = False) -> None:
        target = self._resolve(key)
        if not target.exists():
            if missing_ok:
                return
            raise StorageError(
                kind=StorageErrorKind.NOT_FOUND,
                key=key,
                http_status_hint=404,
            )
        try:
            if target.is_file():
                target.unlink()
            else:
                raise StorageError(
                    kind=StorageErrorKind.BACKEND,
                    key=key,
                    message="[Backend] 目标不是文件，拒绝删除",
                )
        except OSError as exc:
            raise StorageError(
                kind=StorageErrorKind.BACKEND,
                key=key,
                cause=exc,
                retryable=True,
            ) from exc

    def copy(
        self,
        src_key: str,
        dst_key: str,
        *,
        overwrite: bool = True,
    ) -> ObjectMeta:
        src_norm = _normalize_key(src_key)
        dst_norm = _normalize_key(dst_key)
        src = self._resolve(src_key)
        dst = self._resolve(dst_key)
        if not src.exists() or not src.is_file():
            raise StorageError(
                kind=StorageErrorKind.NOT_FOUND,
                key=src_key,
                http_status_hint=404,
            )
        if src == dst:
            # 幂等：src == dst 视为成功。
            return self._head_from_path(src_norm, src)
        if dst.exists():
            if not overwrite:
                # 幂等判定：若内容完全一致（sha256 相同），视为成功；否则报冲突。
                src_meta = self._head_from_path(src_norm, src)
                dst_meta = self._head_from_path(dst_norm, dst)
                if src_meta.etag == dst_meta.etag and src_meta.size == dst_meta.size:
                    return dst_meta
                raise StorageError(
                    kind=StorageErrorKind.ALREADY_EXISTS,
                    key=dst_key,
                    http_status_hint=409,
                )
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            # 通过临时文件 + rename 保证原子性
            fd, tmp_name = tempfile.mkstemp(
                prefix=dst.name + ".",
                suffix=".__tmp",
                dir=str(dst.parent),
            )
            os.close(fd)
            shutil.copyfile(src, tmp_name)
            os.replace(tmp_name, dst)
        except OSError as exc:
            raise StorageError(
                kind=StorageErrorKind.BACKEND,
                key=dst_key,
                cause=exc,
                retryable=True,
            ) from exc
        return self._head_from_path(dst_norm, dst)

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
        # prefix 允许空串（列全部）；也允许尾部斜杠。
        norm_prefix = ""
        if prefix:
            # 空段允许保留（用户可能只想按目录列）
            for ch in _INVALID_KEY_CHARS:
                if ch in prefix:
                    raise _reject(prefix, f"prefix 包含非法字符 {ch!r}")
            if prefix.startswith("/"):
                raise _reject(prefix, "prefix 禁止绝对路径")
            pure = PurePosixPath(prefix.rstrip("/"))
            if any(p == ".." for p in pure.parts):
                raise _reject(prefix, "prefix 包含 `..`")
            norm_prefix = str(pure) if str(pure) != "." else ""
        collected: list[ObjectMeta] = []
        root = self._root
        # 生成候选路径：只走 root 内部；发现越界符号链接就跳过。
        # 因为不同后端目录不深，这里做全量扫描 + 前缀过滤，成本可接受。
        candidates: list[Tuple[str, Path]] = []
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            for name in filenames:
                p = Path(dirpath) / name
                try:
                    rel = p.resolve().relative_to(root)
                except (ValueError, OSError):
                    continue
                rel_key = str(PurePosixPath(*rel.parts))
                if norm_prefix and not (
                    rel_key == norm_prefix or rel_key.startswith(norm_prefix + "/")
                ):
                    continue
                candidates.append((rel_key, p))
        candidates.sort(key=lambda item: item[0])
        started = cursor is None
        next_cursor: Optional[str] = None
        for rel_key, p in candidates:
            if not started:
                if rel_key > cursor:
                    started = True
                else:
                    continue
            if len(collected) >= limit:
                next_cursor = collected[-1].key
                return collected, next_cursor
            try:
                collected.append(self._head_from_path(rel_key, p))
            except StorageError:
                continue
        return collected, None

    # ------------------------------------------------------------------
    # URL 签名（治理期占位）
    # ------------------------------------------------------------------

    def presigned_get_url(
        self,
        key: str,
        *,
        expires_in: Optional[int] = None,
    ) -> str:
        norm = _normalize_key(key)
        # 治理期占位：/{url_prefix}/{key}
        encoded = "/".join(quote(part, safe="") for part in norm.split("/"))
        prefix = self._url_prefix
        if not prefix:
            return "/" + encoded
        return f"{prefix}/{encoded}"

    def presigned_put_url(
        self,
        key: str,
        *,
        expires_in: Optional[int] = None,
        content_type: Optional[str] = None,
    ) -> str:
        # 治理期本地后端没有独立 PUT 端点；返回内部代理 URL 占位，
        # 具体路由挂载归 FileService（PR-2）。上层调用方需知晓这只是
        # 契约层的占位实现。
        norm = _normalize_key(key)
        encoded = "/".join(quote(part, safe="") for part in norm.split("/"))
        return f"/api/_local-storage-put/{encoded}"


__all__ = ["LocalDirAdapter"]
