"""Legacy URL 解析器（PR-BE-10 · Wave 3-N.7 Batch 2 主线 A）。

把 `/api/view` 等 legacy URL 映射到实际文件路径。治理期配合 LocalDirAdapter
使用，稳定期 MinIO 接入后视情况废弃或保留为兼容层。

**约束**：
- 本模块只依赖标准库 + `app.adapters.storage.base` 契约；禁止 `from main import ...`。
- 不修改 legacy URL 语义（[[前端兼容合同冻结清单]] §7.8、§13）。
- 与 `static/js/shared/media/legacyUrlResolver.js` 前端版本协同，但各自独立
  维护（后端解析从文件系统路径角度，前端解析从 URL 分类角度）。

当前治理期只提供占位接口 —— 实际解析逻辑仍保留在 `main.py` 的 legacy 函数
体中（`output_file_from_url` / `view_image` / `download_output`），本模块在
未来 PR 迁入解析逻辑时填写实现。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def resolve_legacy_url(
    url: str,
    *,
    assets_dir: str = "",
    output_dir: str = "",
    generated_dir: str = "",
    upload_dir: str = "",
) -> Optional[str]:
    """把 legacy URL 映射到本地文件系统路径。

    当前治理期仅做占位转发 —— 实际解析由 `main.py` 中 `output_file_from_url`
    等函数承担。本函数在后续 PR 迁入解析逻辑时填写实现。

    Args:
        url: 原始 URL 字符串（如 `/api/view?filename=xxx&type=input`、
            `/output/xxx.png`、`/assets/xxx.png`）。
        assets_dir: ASSETS_DIR 绝对路径。
        output_dir: OUTPUT_DIR 绝对路径。
        generated_dir: 当前 generated 目录绝对路径。
        upload_dir: 当前 upload 目录绝对路径。

    Returns:
        本地文件系统绝对路径，无法解析时返回 None。
    """

    if not url:
        return None
    # 当前治理期：返回 None 表示"请由 legacy 函数体处理"。
    # 未来 PR 在此填写解析逻辑。
    _ = assets_dir, output_dir, generated_dir, upload_dir  # 抑制 lint 告警
    return None


__all__ = ["resolve_legacy_url"]