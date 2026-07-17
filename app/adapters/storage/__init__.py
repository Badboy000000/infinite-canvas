"""StorageAdapter 目录占位。

文件对象与 MinIO 治理 PR-1 会在此新增：
- `base.py`：`StorageAdapter` 抽象契约。
- `local_dir.py`：`LocalDirAdapter` 治理期实现。
- `legacy_url_resolver.py`：兼容期 URL 解析。

PR-BE-01 只建立 `__init__.py`，不落任何契约代码。
"""
