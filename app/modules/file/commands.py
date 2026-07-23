"""File 模块命令对象（PR-BE-10 · Wave 3-N.7 Batch 2 主线 A）。

命令对象承接 `main.py` 中 storage-files / media-preview / view / download-output
共 6 端点的入参。每个命令对象都保留 `raw: dict` 兜底字段，防止 legacy 宽松
参数在 Service 边界上因显式建模丢失（参照 PR-BE-06/07/08/09 命令对象硬约束）。

设计约束（任务书零触碰事实清单）：
- **不改** `main.py` 中现有函数签名与 helper 行为。
- 命令对象刻意不引入校验；校验依然在 FastAPI 端点层及 legacy 函数体内完成。
- 6 端点均不涉及 P0 密钥字段（view / download-output / media-preview 是纯文件
  读取路径；storage-files 是文件列表与删除，不含 provider 凭据）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Storage Files · /api/storage-files*
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ListStorageFilesCommand:
    """`GET /api/storage-files` 命令对象。

    承接 query 参数 kind / offset / limit。
    """

    kind: str = "generated"
    offset: int = 0
    limit: int = 80
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GetStorageFileCommand:
    """`GET /api/storage-files/{kind}/{rel_path:path}` 命令对象。

    承接 path 参数 kind / rel_path。
    """

    kind: str
    rel_path: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeleteStorageFilesCommand:
    """`POST /api/storage-files/delete` 命令对象。

    承接 JSON body 中的 kind / items 数组。
    """

    kind: str = ""
    items: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Media Preview · /api/media-preview
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MediaPreviewCommand:
    """`GET /api/media-preview` 命令对象。

    承接 query 参数 url / w。
    """

    url: str = ""
    width: int = 512
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# View Image · /api/view
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ViewImageCommand:
    """`GET /api/view` 命令对象。

    承接 query 参数 filename / type / subfolder。
    """

    filename: str = ""
    type: str = "input"
    subfolder: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Download Output · /api/download-output
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DownloadOutputCommand:
    """`GET /api/download-output` 命令对象。

    承接 query 参数 url / name / inline。
    """

    url: str = ""
    name: str = ""
    inline: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ListStorageFilesCommand",
    "GetStorageFileCommand",
    "DeleteStorageFilesCommand",
    "MediaPreviewCommand",
    "ViewImageCommand",
    "DownloadOutputCommand",
]