"""Asset 命令对象（PR-BE-07 · Wave 3-N.7 Batch 1 主线 A）。

命令对象承接 `main.py` 中 local-assets / asset-library / prompt-libraries
三大分组共 40 端点的入参。每个命令对象都保留 `raw: dict` 兜底字段，
防止 legacy 宽松 JSON 字段在 Service 边界上因显式建模丢失（参照 PR-BE-06
canvas commands / PR-BE-08 provider commands / PR-BE-09 task commands 硬约束）。

设计约束（任务书零触碰事实清单）：
- **不改** `LocalAssetUrlImportRequest` / `LocalAssetFolderRequest` /
  `AssetLibraryRequest` / `PromptLibraryRequest` 等 Pydantic DTO 字段与默
  认值。命令对象只是从 DTO 组装出来的、供 Service 内部使用的轻量类型。
- 命令对象刻意不引入校验；校验依然在 FastAPI DTO 层完成。
- **P0 密钥字段**（如 payload 里可能透传的 api_key / secret 字段）走
  `raw: dict` 兜底，Service 层在委派 `main.upload_local_assets` /
  `main.classify_local_assets` 等函数之前会执行 sanitize（参照
  `_safe_provider_records` / `app.modules.task.service._sanitize_payload_dict`
  pattern）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Local Assets · /api/local-assets*
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LocalAssetUploadCommand:
    """`POST /api/local-assets/upload` 命令对象（multipart · FILES + folder Form）。

    payload 不建模 —— multipart 由 FastAPI 端点直接消费；本命令对象仅承
    载 `folder` 与文件计数，供 Service 层做审计。
    """

    folder: str = ""
    file_count: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalAssetImportUrlsCommand:
    """`POST /api/local-assets/import-urls` 命令对象。

    承接 `LocalAssetUrlImportRequest` DTO（folder + items[] + classify +
    provider / model / ms_model / prompt）。
    """

    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalAssetFolderCommand:
    """`POST/PATCH /api/local-assets/folders` 命令对象。

    承接 `LocalAssetFolderRequest`（parent / path / name）。
    """

    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalAssetRenameCommand:
    """`PATCH /api/local-assets/items` 命令对象。

    承接 `LocalAssetRenameRequest`（path + name）。
    """

    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalAssetDeleteCommand:
    """`POST /api/local-assets/delete` 命令对象（宽松 dict 入参）。"""

    names: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalAssetMoveCommand:
    """`POST /api/local-assets/move` 命令对象（宽松 dict 入参）。"""

    names: tuple[str, ...] = ()
    folder: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalAssetCaptionCommand:
    """`POST /api/local-assets/caption` 命令对象。

    承接 `LocalAssetCaptionRequest`（names + prompt + provider / model / ms_model）。
    """

    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalAssetCaptionSaveCommand:
    """`PATCH /api/local-assets/caption` 命令对象。

    承接 `LocalAssetCaptionSaveRequest`（name + caption）。
    """

    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalAssetClassifyCommand:
    """`POST /api/local-assets/classify` 命令对象。

    承接 `LocalAssetClassifyRequest`（names + provider / model / ms_model / prompt）。
    """

    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Asset Library · /api/asset-library*
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssetLibraryCreateCommand:
    """`POST /api/asset-library/libraries` 命令对象。承接 `AssetLibraryRequest`。"""

    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetLibraryRenameCommand:
    """`PATCH /api/asset-library/libraries/{library_id}` /
    `PATCH /api/asset-library/categories/{category_id}` /
    `PATCH /api/asset-library/items/{item_id}` 命令对象。

    共享 `AssetLibraryRenameRequest`（library_id + name）。
    """

    resource_id: str
    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetLibraryCategoryCommand:
    """`POST /api/asset-library/categories` 命令对象。承接
    `AssetLibraryCategoryRequest`（library_id + name + type）。
    """

    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetLibraryAddItemCommand:
    """`POST /api/asset-library/items` 命令对象。承接
    `AssetLibraryAddRequest`（category_id + library_id + url + name）。
    """

    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetLibraryBatchAddCommand:
    """`POST /api/asset-library/items/batch` 命令对象。承接
    `AssetLibraryBatchAddRequest`（category_id + library_id + items[]）。
    """

    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetLibraryBatchDeleteCommand:
    """`POST /api/asset-library/items/delete` 命令对象。承接
    `AssetLibraryBatchDeleteRequest`（library_id + ids[]）。
    """

    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetLibraryBatchMoveCommand:
    """`POST /api/asset-library/items/move` 命令对象。承接
    `AssetLibraryBatchMoveRequest`。
    """

    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetLibraryBatchCropCommand:
    """`POST /api/asset-library/items/crop` 命令对象。承接
    `AssetLibraryBatchCropRequest`。
    """

    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetLibraryClassifyCommand:
    """`POST /api/asset-library/items/classify` 命令对象。承接
    `AssetLibraryClassifyRequest`（library_id + ids[] + provider / model /
    ms_model / prompt）。
    """

    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Prompt Libraries · /api/prompt-libraries*
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromptLibraryCreateCommand:
    """`POST /api/prompt-libraries` 命令对象。承接 `PromptLibraryRequest`（name）。"""

    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PromptLibraryRenameCommand:
    """`PATCH /api/prompt-libraries/{library_id}` 命令对象。承接
    `PromptLibraryRequest`。
    """

    library_id: str
    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PromptLibraryCategoryCommand:
    """`POST /api/prompt-libraries/categories` /
    `PATCH /api/prompt-libraries/categories/{category_id}` 命令对象。

    承接 `PromptLibraryCategoryRequest`（library_id + name）。
    """

    payload: Any
    category_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PromptLibraryItemCommand:
    """`POST /api/prompt-libraries/items` /
    `PATCH /api/prompt-libraries/items/{item_id}` 命令对象。

    承接 `PromptLibraryItemRequest`（library_id + name + category + positive /
    negative / scene）。
    """

    payload: Any
    item_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PromptLibraryBatchDeleteCommand:
    """`POST /api/prompt-libraries/items/delete` 命令对象。承接
    `PromptLibraryBatchDeleteRequest`（ids[]）。
    """

    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "LocalAssetUploadCommand",
    "LocalAssetImportUrlsCommand",
    "LocalAssetFolderCommand",
    "LocalAssetRenameCommand",
    "LocalAssetDeleteCommand",
    "LocalAssetMoveCommand",
    "LocalAssetCaptionCommand",
    "LocalAssetCaptionSaveCommand",
    "LocalAssetClassifyCommand",
    "AssetLibraryCreateCommand",
    "AssetLibraryRenameCommand",
    "AssetLibraryCategoryCommand",
    "AssetLibraryAddItemCommand",
    "AssetLibraryBatchAddCommand",
    "AssetLibraryBatchDeleteCommand",
    "AssetLibraryBatchMoveCommand",
    "AssetLibraryBatchCropCommand",
    "AssetLibraryClassifyCommand",
    "PromptLibraryCreateCommand",
    "PromptLibraryRenameCommand",
    "PromptLibraryCategoryCommand",
    "PromptLibraryItemCommand",
    "PromptLibraryBatchDeleteCommand",
]
