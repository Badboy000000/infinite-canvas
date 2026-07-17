"""Identity 数据基座包（权限 PR-0 落地）。

对齐：
- [[40 实施计划/用户团队权限治理实施计划与PR清单]] PR-0
- [[50 决策记录/决策 - 认证栈选型]]
- [[50 决策记录/决策 - 主键类型]]（identity 全表 UUID + `legacy_owner_label` / `legacy_user_key`）
- [[50 决策记录/决策 - ORM 与迁移工具选型]]（本 PR 不落 ORM，只落 JSON；schema 与未来 SQLAlchemy 表结构对齐）
- [[60 讨论记录/2026-07-17 第二批开工/2026-07-17 第二批 PR 开工协调纲要]] 字段冻结契约

本包的职责边界（权限 PR-0）：

1. `schema.py` — 8 类 identity JSON 的 TypedDict / 校验函数（`_schema_version=1`）。
2. `store.py` — `IdentityStore` 门面（只读接口 9 个 + 单一写入接口
   `write_auth_migration_state` 供 bootstrap 使用）；`JsonIdentityStore` 具体实现；
   `SqliteIdentityStore` 为 `NotImplementedError` 占位。
3. `request_context.py` — `RequestContext` frozen dataclass **唯一定义位置**；
   字段清单由协调纲要冻结，PR-BE-02 / PR-BE-04 / PR-BE-12 消费。
4. `legacy_mapper.py` — 空壳，`x_user_id / owner / conversation dir` → UserAlias 映射
   逻辑由权限 PR-2 承接。

本包 **不做** 认证、不做权限判定、不接入 middleware、不改路由。
"""
