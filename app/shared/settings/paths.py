"""PathResolver — 只读路径解析器（PR-BE-03）。

包裹 `main.py` 中 `current_upload_dir()` / `current_generated_dir()` /
`current_local_dir()` 三个"读时求值"accessor，承接文件 PR-0（`main.py:302-388`
冻结区间）的多进程一致性语义：

- **每次调用现读**：不缓存启动时值。`main.storage_settings_snapshot()` 内部
  会现读 `data/storage_settings.json`，因此这三个方法每次调用都会反映最新
  磁盘状态。
- **只读**：不提供 setter。写入路径由 `main.save_storage_settings()`
  ↔ `PATCH /api/storage-settings` 独占，本 wrapper 不复用也不代理。

签名冻结：
- `PathResolver.current_upload_dir() -> str`
- `PathResolver.current_generated_dir() -> str`
- `PathResolver.current_local_dir() -> str`

以及只读属性代理，把 `Settings` 字段全部暴露为 `PathResolver.<field>`
形式的属性——方便调用侧不必区分"启动时锚点"与"运行时求值"两套 API：
- `PathResolver.base_dir`（等）返回 `get_settings().<field>`（启动时锚点，
  每次现读 `main` 属性）。
- `PathResolver.current_upload_dir()`（等）走 `main.current_*_dir()`，与
  三个存储目录设置的**读时求值**语义严格一致。

设计上"当前值"用方法名 `current_*()` 显式标记，"锚点"用属性形式暴露，
调用侧不易混淆。

详见 [[40 实施计划/后端模块化治理实施计划与PR清单]] PR-BE-03、
[[20 现状地图/数据存储现状地图]] §十一。
"""
from __future__ import annotations

from typing import Any

from .runtime import Settings, get_settings


class PathResolver:
    """只读路径解析器。

    内部不持有任何缓存字段——所有属性/方法都在每次访问时从 `main` 模块
    现读，保证与首批 PR-0 的读时求值语义一致，避免多 worker / 多进程下
    因 Python-level 缓存把 PATCH 后的 storage_settings 丢在别的 worker。
    """

    # ---- 存储目录设置：读时求值三件套（严格代理到 main.current_*_dir()） ----

    def current_upload_dir(self) -> str:
        """当前 `upload` 目录（读时求值）。

        代理到 `main.current_upload_dir()`，即 `storage_settings_snapshot().upload`。
        每次调用现读 `data/storage_settings.json` + env/BASE_DIR fallback；
        多 worker 场景下所有 worker 都会拿到磁盘最新值。
        """
        import main  # 懒 import

        return main.current_upload_dir()

    def current_generated_dir(self) -> str:
        """当前 `generated` 目录（读时求值）。

        代理到 `main.current_generated_dir()`。语义同 `current_upload_dir`。
        """
        import main  # 懒 import

        return main.current_generated_dir()

    def current_local_dir(self) -> str:
        """当前 `local` 目录（读时求值）。

        代理到 `main.current_local_dir()`。语义同 `current_upload_dir`。
        """
        import main  # 懒 import

        return main.current_local_dir()

    # ---- Settings 字段的只读代理（启动时锚点，非运行时求值） ------------

    def snapshot(self) -> Settings:
        """返回一份 `Settings` frozen dataclass 快照。等价于 `get_settings()`。"""
        return get_settings()

    def __getattr__(self, name: str) -> Any:
        """把 `PathResolver.<field>` 代理到 `get_settings().<field>`。

        仅在实例 `__dict__` 与类属性都查不到时才触发；三个 `current_*_dir`
        方法与 `snapshot` 已定义为类方法，不会走到这里，避免语义歧义。
        """
        if name.startswith("_"):
            raise AttributeError(name)
        settings = get_settings()
        try:
            return getattr(settings, name)
        except AttributeError as exc:
            raise AttributeError(
                f"PathResolver has no attribute {name!r}; "
                f"Settings 字段清单：{list(settings.__dataclass_fields__.keys())}"
            ) from exc


__all__ = ["PathResolver"]
