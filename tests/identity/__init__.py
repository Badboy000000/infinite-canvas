"""tests/identity — 权限 PR-0 契约测试包。

覆盖：
- `test_schema.py`：8 类 JSON schema 校验函数的正例 / 反例。
- `test_store.py`：`JsonIdentityStore` 在空数据 / bootstrap 后的行为；
  `SqliteIdentityStore.__init__` 抛 NotImplementedError。
- `test_bootstrap_idempotent.py`：`tools/migrate_identity_bootstrap.py` 连续
  运行 3 次的字节等价性。
- `test_request_context.py`：`RequestContext` frozen 语义 / 字段类型 /
  `dataclasses.replace` 行为。

所有测试使用 `tmp_path` fixture 隔离；**不写** 项目 `data/identity/`。
"""
