"""Legacy semantics mapper — 空壳（权限 PR-2 承接）。

本文件由权限 PR-0 建立**空壳**，占位路径 `app/identity/legacy_mapper.py`，
防止权限 PR-2 建立时找不到目录。

PR-2 承接责任（见 [[40 实施计划/用户团队权限治理实施计划与PR清单]] PR-2）：

- 扫描 `data/canvases/*.json` / `data/projects.json` / `data/conversations/` /
  `data/asset_library.json` / `data/api_providers.json` / `data/history.json`，
  把旧 `owner` / `x_user_id` / conversation 目录名派生的身份线索**影子写入**
  `data/identity/user_aliases.json`（`UserAliasRecord`）。
- 在运行时（PR-1 middleware 落地后）暴露解析函数：
  `resolve_legacy(request) -> Optional[UserAliasRecord]`
  给 `get_request_context` 使用；本 PR **不落**这个函数。

本文件保留空壳，不导出任何符号；调用点若在此期间导入本模块，只能拿到本 docstring。
"""
