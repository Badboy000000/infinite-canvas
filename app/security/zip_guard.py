"""`app.security.zip_guard` — zip bomb / 路径穿越防护(部署 PR-04 骨架层)。

**定位**:纯函数 + frozen dataclass 决策对象 · env flag 默认关闭 · 与旧行为等价。

**骨架契约**:
- ``ZipGuardPolicy``:总大小 / 条目数 / 单条 / 压缩比阈值 · frozen
- ``ZipDecision``:结果 frozen dataclass(``accepted`` / ``reason`` / ``details``)
- ``ZipReason``:拒绝原因 Literal 枚举
- ``inspect_zip_entries(entries, policy)``:纯函数入口 · 接收 metadata 列表
- ``normalize_zip_entry_path(name, dest_root)``:路径规范化 + dest_root 越界检测
- ``is_zip_guard_enforce_enabled()``:env flag ``ZIP_GUARD_ENFORCE`` 判据

**默认策略**(治理方案 M1 明示):
- 总大小 200 MB
- 条目数 5000
- 单条 100 MB
- 压缩比 200(1MB 压缩不得解压到 200MB 以上)
- 拒绝符号链接

**不做**:
- 不替换 ``main.py`` 中现有 ``zipfile.ZipFile`` 调用点(生产切换归后续 PR)
- 不实现 ``safe_extract`` 真正解压(骨架只提供 metadata inspection)
- 不引入 ``py7zr`` / ``rarfile``
- 骨架 flag off 时上层依旧走原 ``zipfile`` 语义

见 [[40 实施计划/部署与安全治理实施计划与PR清单]] PR-04。
"""
from __future__ import annotations

import os
import posixpath
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
from typing import List, Literal, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# env flag
# ---------------------------------------------------------------------------

_TRUTHY = frozenset({"1", "true", "yes", "on", "TRUE"})

ZIP_GUARD_ENFORCE_ENV = "ZIP_GUARD_ENFORCE"


def is_zip_guard_enforce_enabled() -> bool:
    """``ZIP_GUARD_ENFORCE`` 是否已开启(默认 false)。"""
    return os.environ.get(ZIP_GUARD_ENFORCE_ENV, "").strip() in _TRUTHY


# ---------------------------------------------------------------------------
# Reason 枚举 & 决策对象
# ---------------------------------------------------------------------------

ZipReason = Literal[
    "accepted",
    "oversize_total_uncompressed",
    "too_many_entries",
    "oversize_single_entry",
    "path_escape",
    "symlink",
    "bomb_ratio",
    "absolute_path",
]


@dataclass(frozen=True)
class ZipEntryMeta:
    """zip 单条元数据 · 用于 inspect_zip_entries 输入。

    Attributes:
        filename: 条目名(zip 内部使用 posix 分隔符);外部读取时统一 ``.replace("\\\\", "/")``。
        compressed_size: 压缩后字节数。
        uncompressed_size: 解压后字节数。
        is_symlink: zip external_attr 是否为符号链接(zipfile.ZipInfo.external_attr 判据)。
    """

    filename: str
    compressed_size: int
    uncompressed_size: int
    is_symlink: bool = False


@dataclass(frozen=True)
class ZipDecision:
    """zip 护栏决策 · frozen。"""

    accepted: bool
    reason: ZipReason
    offending_entry: Optional[str] = None
    total_uncompressed: Optional[int] = None
    entry_count: Optional[int] = None
    detected_ratio: Optional[float] = None


# ---------------------------------------------------------------------------
# 策略 dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ZipGuardPolicy:
    """zip 护栏策略 · frozen。

    默认策略对齐治理方案 M1 明示阈值。生产 PR 通过 Settings 覆盖。
    """

    max_total_uncompressed_bytes: int = 200 * 1024 * 1024
    max_entries: int = 5000
    max_single_entry_bytes: int = 100 * 1024 * 1024
    max_compression_ratio: float = 200.0
    allow_symlinks: bool = False


DEFAULT_ZIP_POLICY = ZipGuardPolicy()


# ---------------------------------------------------------------------------
# 路径规范化
# ---------------------------------------------------------------------------


def normalize_zip_entry_path(name: str, dest_root: str) -> Tuple[bool, str]:
    """规范化 zip 条目名 · 检测是否越出 ``dest_root``。

    路径穿越判据(至少一项命中即视为越界):
        - 条目名为绝对路径(``/foo`` 或 ``C:/foo``)
        - 规范化后的路径以 ``..`` 段开头
        - 规范化后 join 到 ``dest_root`` 后 · resolved 目标不再位于 ``dest_root`` 之内

    Args:
        name: zip 内条目名(可能含 ``..`` / ``/`` / 反斜杠)。
        dest_root: 期望解压根(posix 或 windows 绝对路径均可)。

    Returns:
        ``(is_safe, canonical_relative)`` 元组。``is_safe=False`` 表示路径穿越。
    """
    if not name:
        return (True, "")

    # 统一分隔符
    unified = name.replace("\\", "/")

    # 绝对路径判据
    if unified.startswith("/") or (
        len(unified) >= 3 and unified[1:3] == ":/"
    ):
        return (False, unified)

    # 规范化 · posix
    normalized = posixpath.normpath(unified)
    if normalized.startswith("../") or normalized == "..":
        return (False, normalized)

    # join dest_root 后再校验
    # 使用 os.path 判断是否仍在 dest_root 内
    dest_norm = os.path.normpath(dest_root)
    joined = os.path.normpath(os.path.join(dest_norm, normalized))
    # 保证末尾 sep 一致
    dest_sep = dest_norm + os.sep
    joined_sep = joined + os.sep
    if not (
        joined == dest_norm
        or joined.startswith(dest_sep)
        or joined_sep.startswith(dest_sep)
    ):
        return (False, normalized)

    return (True, normalized)


# ---------------------------------------------------------------------------
# 主入口:纯函数 · 不打开 zip 文件
# ---------------------------------------------------------------------------


def inspect_zip_entries(
    entries: Sequence[ZipEntryMeta],
    *,
    dest_root: str = "/tmp/zip-unpack",
    policy: ZipGuardPolicy = DEFAULT_ZIP_POLICY,
) -> ZipDecision:
    """zip 护栏主检查 · 纯函数 · 无 IO。

    检查顺序:
        1. 条目数超限 → ``too_many_entries``
        2. 单条超限 → ``oversize_single_entry``
        3. 压缩比超限 → ``bomb_ratio``
        4. 路径穿越 / 绝对路径 → ``path_escape`` / ``absolute_path``
        5. 符号链接且不允许 → ``symlink``
        6. 累加超总量 → ``oversize_total_uncompressed``
        7. 均通过 → ``accepted``

    Args:
        entries: zip 条目元数据列表。
        dest_root: 期望解压根(用于路径穿越判据 · 骨架层可传占位值)。
        policy: 策略;缺省 ``DEFAULT_ZIP_POLICY``。

    Returns:
        ``ZipDecision``。
    """
    entry_count = len(entries)
    if entry_count > policy.max_entries:
        return ZipDecision(
            accepted=False,
            reason="too_many_entries",
            entry_count=entry_count,
        )

    total_uncompressed = 0
    for entry in entries:
        # 单条上限
        if entry.uncompressed_size > policy.max_single_entry_bytes:
            return ZipDecision(
                accepted=False,
                reason="oversize_single_entry",
                offending_entry=entry.filename,
            )

        # 压缩比 · compressed=0 时视为无穷大(空条目豁免)
        if entry.compressed_size > 0:
            ratio = entry.uncompressed_size / entry.compressed_size
            if ratio > policy.max_compression_ratio:
                return ZipDecision(
                    accepted=False,
                    reason="bomb_ratio",
                    offending_entry=entry.filename,
                    detected_ratio=ratio,
                )
        elif entry.uncompressed_size > 0:
            # 压缩后 0 字节但解压 > 0 · 视为 zip bomb
            return ZipDecision(
                accepted=False,
                reason="bomb_ratio",
                offending_entry=entry.filename,
                detected_ratio=float("inf"),
            )

        # 路径穿越
        # 绝对路径优先判据
        unified = entry.filename.replace("\\", "/")
        if unified.startswith("/") or (
            len(unified) >= 3 and unified[1:3] == ":/"
        ):
            return ZipDecision(
                accepted=False,
                reason="absolute_path",
                offending_entry=entry.filename,
            )
        is_safe, _norm = normalize_zip_entry_path(entry.filename, dest_root)
        if not is_safe:
            return ZipDecision(
                accepted=False,
                reason="path_escape",
                offending_entry=entry.filename,
            )

        # 符号链接
        if entry.is_symlink and not policy.allow_symlinks:
            return ZipDecision(
                accepted=False,
                reason="symlink",
                offending_entry=entry.filename,
            )

        total_uncompressed += entry.uncompressed_size

    if total_uncompressed > policy.max_total_uncompressed_bytes:
        return ZipDecision(
            accepted=False,
            reason="oversize_total_uncompressed",
            total_uncompressed=total_uncompressed,
            entry_count=entry_count,
        )

    return ZipDecision(
        accepted=True,
        reason="accepted",
        total_uncompressed=total_uncompressed,
        entry_count=entry_count,
    )


__all__ = [
    "ZIP_GUARD_ENFORCE_ENV",
    "ZipGuardPolicy",
    "ZipDecision",
    "ZipReason",
    "ZipEntryMeta",
    "DEFAULT_ZIP_POLICY",
    "inspect_zip_entries",
    "normalize_zip_entry_path",
    "is_zip_guard_enforce_enabled",
]
