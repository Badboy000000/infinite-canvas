"""StorageAdapter 端口契约（文件对象与 MinIO 治理 PR-1）。

治理期 LocalDirAdapter、稳定期 MinioAdapter 都必须实现同一份 9 接口
契约；本文件冻结接口签名、`ObjectMeta` shape 与 `StorageError.kind`
枚举。任何后续 PR 若需扩接口，走"新技术引入规则"评审，禁止悄悄加
方法或改变异常语义。

约束：
- 本模块只依赖标准库；禁止 `from main import ...`；禁止引入除
  `httpx` 外的 IO 依赖（`httpx` 仅在 Adapter 具体实现里按需引入）。
- `hash_stream` 明确不在 Adapter 层——内容语义归 FileService（PR-2）。
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import BinaryIO, ContextManager, Iterable, Iterator, Optional, Tuple


# ---------------------------------------------------------------------------
# 错误契约
# ---------------------------------------------------------------------------


class StorageErrorKind(str, Enum):
    """StorageError 的种类枚举——契约冻结，后续 PR 不得增删。

    值同时用作稳定错误码（`code`），FileService/HTTP 层可直接引用。
    """

    NOT_FOUND = "NotFound"
    ALREADY_EXISTS = "AlreadyExists"
    PRECONDITION_FAILED = "PreconditionFailed"
    RATE_LIMITED = "RateLimited"
    TIMEOUT = "Timeout"
    PARTIAL_UPLOAD = "PartialUpload"
    INTEGRITY_ERROR = "IntegrityError"
    BACKEND = "Backend"
    FORBIDDEN = "Forbidden"
    INVALID_KEY = "InvalidKey"


# 允许 `StorageError(kind="NotFound", ...)` 的字符串写法，也允许枚举。
_VALID_KIND_VALUES = {k.value for k in StorageErrorKind}


class StorageError(Exception):
    """Adapter 层统一异常。

    - `kind`：`StorageErrorKind` 或其字符串值。
    - `key`：涉及的对象 key（可选）。
    - `cause`：底层原始异常（用于日志，不用于 API 返回）。
    - `retryable`：是否值得上层调度重试。
    - `http_status_hint`：路由层可参考的 HTTP 状态码（可选）。
    - `request_id`：底层后端返回的 request id（如 MinIO），用于追踪。
    """

    def __init__(
        self,
        kind: StorageErrorKind | str,
        key: Optional[str] = None,
        cause: Optional[BaseException] = None,
        retryable: bool = False,
        http_status_hint: Optional[int] = None,
        request_id: Optional[str] = None,
        message: Optional[str] = None,
    ) -> None:
        if isinstance(kind, StorageErrorKind):
            kind_value = kind.value
        else:
            kind_value = str(kind)
            if kind_value not in _VALID_KIND_VALUES:
                raise ValueError(
                    f"StorageError.kind={kind_value!r} 不在冻结枚举内: "
                    f"{sorted(_VALID_KIND_VALUES)}"
                )
        self.kind: str = kind_value
        self.key = key
        self.cause = cause
        self.retryable = bool(retryable)
        self.http_status_hint = http_status_hint
        self.request_id = request_id
        text = message or f"[{kind_value}] key={key!r}"
        super().__init__(text)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"StorageError(kind={self.kind!r}, key={self.key!r}, "
            f"retryable={self.retryable}, http_status_hint={self.http_status_hint}, "
            f"request_id={self.request_id!r})"
        )


# ---------------------------------------------------------------------------
# ObjectMeta
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ObjectMeta:
    """对象元信息。

    治理期 Local 后端字段可能有缺失（etag 用 sha256 头 16 位十六进制字符串
    充当，`sha256` 由 FileService 计算并回填，Adapter 不算校验和）。
    """

    key: str
    size: int
    etag: str
    mime_type: Optional[str] = None
    last_modified_ms: Optional[int] = None
    backend: str = "local"
    # 允许后端自身携带的原生元数据（如 MinIO user_meta）。
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# WritableStream 协议——供 open_writable_stream 使用
# ---------------------------------------------------------------------------


class WritableObjectStream(abc.ABC):
    """流式写入的上下文对象。

    契约：
    - 作为 context manager 使用（`with adapter.open_writable_stream(key) as w`）。
    - `write(chunk)` 允许多次调用。
    - `abort()` 主动放弃写入；触发 `PartialUpload` 语义（可见对象不生成）。
    - 正常离开 `with` 块（无异常且未 `abort`）视为 `commit`：对象对
      后续 `head/get_stream/list_prefix` 可见。
    - 异常离开 `with` 块视同 `abort`；实现必须清理临时资源，
      **不得**留下部分写入的对象。
    """

    @abc.abstractmethod
    def write(self, chunk: bytes) -> int:
        raise NotImplementedError

    @abc.abstractmethod
    def abort(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def commit(self) -> ObjectMeta:
        raise NotImplementedError

    # context manager sugar
    def __enter__(self) -> "WritableObjectStream":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self.abort()
            return None
        # 若调用方未显式 commit/abort，默认 commit。
        if not getattr(self, "_finalized", False):
            self.commit()
        return None


# ---------------------------------------------------------------------------
# StorageAdapter 契约
# ---------------------------------------------------------------------------


class StorageAdapter(abc.ABC):
    """9 接口契约。后续 MinioAdapter 参数化跑同一份契约测试。

    key 语义：
    - 使用 POSIX 风格正斜杠 `/`。
    - 禁止 `..` 段、绝对路径（`/foo`）、盘符（`C:`）、反斜杠、空字节。
    - 违反即 raise `StorageError(kind=INVALID_KEY)`。
    """

    backend_name: str = "abstract"

    # ---- 写入 -----------------------------------------------------------

    @abc.abstractmethod
    def put(
        self,
        key: str,
        data: bytes,
        *,
        mime_type: Optional[str] = None,
        overwrite: bool = True,
        if_match_etag: Optional[str] = None,
    ) -> ObjectMeta:
        """一次性写入 bytes。

        - `overwrite=False` 时目标已存在则 raise `AlreadyExists`。
        - `if_match_etag` 指定时若当前 etag 不匹配则 raise
          `PreconditionFailed`。
        """
        raise NotImplementedError

    @abc.abstractmethod
    def open_writable_stream(
        self,
        key: str,
        *,
        mime_type: Optional[str] = None,
        overwrite: bool = True,
        if_match_etag: Optional[str] = None,
    ) -> ContextManager[WritableObjectStream]:
        """打开流式写入通道。Context manager 语义见 `WritableObjectStream`。"""
        raise NotImplementedError

    # ---- 读取 -----------------------------------------------------------

    @abc.abstractmethod
    def get_stream(
        self,
        key: str,
        *,
        offset: int = 0,
        length: Optional[int] = None,
    ) -> Iterator[bytes]:
        """按 chunk 迭代对象内容。`length=None` 表示读到末尾。"""
        raise NotImplementedError

    @abc.abstractmethod
    def head(self, key: str) -> ObjectMeta:
        """返回对象元数据；对象不存在 raise `NotFound`。"""
        raise NotImplementedError

    # ---- 变更 -----------------------------------------------------------

    @abc.abstractmethod
    def delete(self, key: str, *, missing_ok: bool = False) -> None:
        """删除对象。`missing_ok=False` 且对象不存在时 raise `NotFound`。"""
        raise NotImplementedError

    @abc.abstractmethod
    def copy(
        self,
        src_key: str,
        dst_key: str,
        *,
        overwrite: bool = True,
    ) -> ObjectMeta:
        """服务端 copy。幂等：`src == dst` 或目标已存在同内容视为幂等成功。"""
        raise NotImplementedError

    # ---- 查询 -----------------------------------------------------------

    @abc.abstractmethod
    def list_prefix(
        self,
        prefix: str,
        *,
        cursor: Optional[str] = None,
        limit: int = 1000,
    ) -> Tuple[Iterable[ObjectMeta], Optional[str]]:
        """列举前缀下的对象。

        返回 `(items, next_cursor)`，`next_cursor is None` 表示已到末尾。
        `cursor` 语义：调用方传入上次返回的 `next_cursor`，实现按 key 排序
        并从大于 cursor 的第一个开始返回。
        """
        raise NotImplementedError

    # ---- URL 签名 -------------------------------------------------------

    @abc.abstractmethod
    def presigned_get_url(
        self,
        key: str,
        *,
        expires_in: Optional[int] = None,
    ) -> str:
        """返回可供 GET 的 URL。

        治理期 Local 后端返回 `/{url_prefix}/{key}` 占位，路由层由
        FastAPI 静态挂载消费；稳定期 Minio 后端返回真正的签名 URL。
        """
        raise NotImplementedError

    @abc.abstractmethod
    def presigned_put_url(
        self,
        key: str,
        *,
        expires_in: Optional[int] = None,
        content_type: Optional[str] = None,
    ) -> str:
        """返回可供 PUT 的 URL。

        治理期 Local 后端返回内部代理 URL 占位；稳定期 Minio 后端返回
        真正的签名 PUT URL。
        """
        raise NotImplementedError


__all__ = [
    "StorageAdapter",
    "StorageError",
    "StorageErrorKind",
    "ObjectMeta",
    "WritableObjectStream",
]
