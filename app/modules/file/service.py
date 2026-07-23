"""File 模块 Service facade（PR-BE-10 · Wave 3-N.7 Batch 2 主线 A）。

`FileModuleFacade` 承接文件域公共状态。**6 端点的路由层通过 callback factory
委派**，本 facade 提供跨端点的通用工具与稳定接口签名。

**方案对齐**：
- 与 `app.modules.asset.service.AssetModuleFacade` 完全同源（PR-BE-07 pattern）：
  路由层调 callback → callback 委派 legacy `main.list_storage_files` /
  `main.media_preview` / `main.view_image` / `main.download_output` 函数体。
- 本 facade **不 `import main`**（继承 PR-BE-05/06/07/08/09 硬约束）。

**P0 密钥零入库防线**：storage-files / media-preview / view / download-output
端点不涉及 provider 凭据入参（纯文件读取路径），因此本 facade 不引入
`_sanitize_payload_dict` helper。若后续 PR 在 upload 场景引入本模块，参照
`app.modules.asset.service._sanitize_payload_dict` pattern 追加。
"""

from __future__ import annotations

from typing import Any


class FileModuleFacade:
    """文件域 service facade（薄状态载体）。

    当前阶段不维护 store 引用（6 端点直接操作文件系统，不经过持久化 store）。
    保留本 facade 作为未来扩展接入点。
    """

    def __init__(self) -> None:
        pass


__all__ = [
    "FileModuleFacade",
]