"""ID 生成占位。

依 [[决策 - 主键类型]]：`generate_id / encode_id / parse_id` 三接口最终在
此冻结（UUIDv7 + `legacy_id TEXT UNIQUE` 承接）。PR-BE-01 仅建立模块路径。
"""
