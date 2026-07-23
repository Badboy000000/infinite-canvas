"""Provider 领域模块（PR-BE-08 · Wave 3-N.6 Batch 2 主线 A）。

- `commands.py` 命令对象（SaveProvidersCommand / TestConnectionCommand / …）
- `store.py`    持久化 facade（委派给 `app.stores.provider_config_store`；
                密钥深度脱敏由 `_safe_provider_records` 承担）
- `service.py`  业务 service（`ProviderConfigService`）— 组合 store + main.py
                helper（通过 callback 显式注入 · 不 `import main`）
- `registry.py` `ProviderRegistry` facade — 双参 `resolve(provider_id, model)`
                委派给 `app.adapters.provider.registry::resolve_adapter`
                以保留 `model_protocols` 表映射能力（GM-14 圆桌自治第 7 次
                实证 · 裁决 3）。

设计原则：`app/api/routers/providers.py` 等新路由文件通过 `create_router(...)`
工厂函数拿到 `ProviderConfigService`，不 `import main`。service 内部**允许**
在 `main.py` 里对领域函数保留原实现（PR-BE-06 兼容层要求）；service 明确暴
露一层稳定接口，为下一批 PR 把领域函数体正式迁入本模块打底。
"""
