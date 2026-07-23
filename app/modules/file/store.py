"""File 模块持久化 facade（PR-BE-10 · Wave 3-N.7 Batch 2 主线 A）。

当前阶段 6 端点直接操作文件系统，不经过持久化 store。本文件保留为占位，
当未来 PR 引入 FileObject 表 + MinIO 接入时，在此追加正式 store facade。

严格约束（任务书零触碰事实清单）：
- **不改** `app/services/files/file_service.py`（PR-2 已 landing）。
- **不改** `app/adapters/storage/` 下现有接口与实现。
"""

from __future__ import annotations


__all__: list[str] = []