"""File 领域模块（PR-BE-10 · Wave 3-N.7 Batch 2 主线 A）。

模块承接 `main.py` 中 6 文件路由的服务门面：

- Storage Files（存储文件 · `/api/storage-files*` · 3 路由）
- Media Preview（媒体预览 · `/api/media-preview` · 1 路由）
- View Image（ComfyUI 视图代理 · `/api/view` · 1 路由）
- Download Output（文件下载 · `/api/download-output` · 1 路由）

设计原则（对齐 PR-BE-07 asset / PR-BE-08 provider / PR-BE-09 task 模块 pattern）：

- `FileModuleFacade` 承接稳定接口，**内部通过 callback 委派回 `main.py`
  中的 legacy 函数体**（保请求 / 响应 shape 逐字节等价）。
- 模块内部 **不 `import main`**（继承 PR-BE-05/06/07/08/09 硬约束）。
"""

from .commands import (
    DeleteStorageFilesCommand,
    DownloadOutputCommand,
    GetStorageFileCommand,
    ListStorageFilesCommand,
    MediaPreviewCommand,
    ViewImageCommand,
)
from .service import FileModuleFacade


__all__ = [
    "FileModuleFacade",
    "ListStorageFilesCommand",
    "GetStorageFileCommand",
    "DeleteStorageFilesCommand",
    "MediaPreviewCommand",
    "ViewImageCommand",
    "DownloadOutputCommand",
]