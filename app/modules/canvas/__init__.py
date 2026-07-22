"""Canvas 领域模块（PR-BE-06 起）。

- `commands.py` 命令对象（CanvasSaveCommand / CanvasCreateCommand / …）
- `store.py`    持久化 facade（委派给 `app.stores.canvas_store` 与
                `app.stores.project_store`；不重新实现 IO）
- `service.py`  业务 service（`CanvasService`）— 组合 store + main.py
                helper（通过 callback 显式注入 · 不 `import main`）

设计原则：`app/api/routers/canvas.py` 等新路由文件通过 `create_router(...)` 工
厂函数拿到 `CanvasService`，不 `import main`。service 内部**允许**在 `main.py`
里对领域函数保留原实现（PR-BE-06 兼容层要求）；只是 service 明确暴露一层稳定
接口，为下一批 PR 把领域函数体正式迁入本模块打底。
"""
