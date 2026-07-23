"""Asset 领域模块（PR-BE-07 · Wave 3-N.7 Batch 1 主线 A · 候选 B 完整分组抽出）。

模块承接 `main.py` 三大 asset 路由分组的服务门面：

- Local Assets（本地素材 · `/api/local-assets*` · 11 路由 · 上传 / 分类 /
  反推 / 移动 / 删除）
- Asset Library（资产库 · `/api/asset-library*` · 18 路由 · 库/分类/项目
  CRUD + 批量 + 数字人认证 + workflows 上传）
- Prompt Libraries（提示词库 · `/api/prompt-libraries*` · 11 路由 · 库/分
  类/条目 CRUD + 批量删除）

设计原则（对齐 PR-BE-06 canvas + project / PR-BE-08 provider / PR-BE-09
task 模块 pattern · GM-14 圆桌自治第 9 次实证 · CB-P5-32 挂账）：

- `AssetModuleFacade` 承接稳定接口，**内部通过 callback 委派回 `main.py`
  中的 legacy 函数体**（保 P0 密钥零入库防线 + 请求 / 响应 shape 逐字节
  等价）。
- `AssetLibraryStore` / `PromptLibraryStore` 是**薄委派** —— 让 service /
  router 层拿到统一接口，内部转发 `app/stores/asset_library_store.py` /
  `app/stores/prompt_library_store.py`（PR-BE-04 已 landing）。
- 模块内部 **不 `import main`**（继承 PR-BE-05 / 06 / 08 / 09 硬约束）。

**P0 密钥零入库防线**（GM-16 v2 沿用 · CB-P5-32 承接）：
- upload / import-urls / caption / classify 等入参可能透传 provider api_key /
  secret / access_token 字段 · 本模块不落地 log · 不落地 dict 副本 · 委派
  时透传 DTO 实例;sentinel 反查断言仅在测试路径消费（T443）。
- `_sanitize_payload_dict` helper 对齐 `app.modules.task.service` pattern ·
  提供审计断言用的 sanitize view。

**冻结 · 不做**（任务书 §"明确不做什么"）：
- 不接入 MinIO / 不改 `assets/` 目录结构 / 不改 `asset_library.json` shape。
- 不动前端 URL / 响应字段 / `_local_upload_abs` / `storage_file_path` 路径校验。
- FileService 影子登记不新增（`app/services/files/` 独立存在）。
"""

from .commands import (
    AssetLibraryAddItemCommand,
    AssetLibraryBatchAddCommand,
    AssetLibraryBatchCropCommand,
    AssetLibraryBatchDeleteCommand,
    AssetLibraryBatchMoveCommand,
    AssetLibraryCategoryCommand,
    AssetLibraryClassifyCommand,
    AssetLibraryCreateCommand,
    AssetLibraryRenameCommand,
    LocalAssetCaptionCommand,
    LocalAssetCaptionSaveCommand,
    LocalAssetClassifyCommand,
    LocalAssetDeleteCommand,
    LocalAssetFolderCommand,
    LocalAssetImportUrlsCommand,
    LocalAssetMoveCommand,
    LocalAssetRenameCommand,
    LocalAssetUploadCommand,
    PromptLibraryBatchDeleteCommand,
    PromptLibraryCategoryCommand,
    PromptLibraryCreateCommand,
    PromptLibraryItemCommand,
    PromptLibraryRenameCommand,
)
from .service import AssetModuleFacade
from .store import AssetLibraryModuleStore, PromptLibraryModuleStore


__all__ = [
    "AssetModuleFacade",
    "AssetLibraryModuleStore",
    "PromptLibraryModuleStore",
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
