"""Store facade 包 — 数据模型治理 PR-0 落地。

按九个数据边界暴露 facade 模块；每个 facade 内部委派到 `main.py` 现有实现。
路由层通过 `from app.stores import canvas_store` 后调用 `canvas_store.save_canvas(...)`
的形式接入，不再直接引用 `main.py` 里的 helper 名字。

后续（数据 PR-1 起）会替换各 store 的内部实现为 SQLAlchemy Session，
路由层调用点无需再改。
"""
from . import (
    asset_library_store,
    canvas_store,
    conversation_store,
    history_store,
    project_store,
    prompt_library_store,
    provider_config_store,
    storage_settings_store,
    workflow_store,
)
from .legacy_snapshot import LegacySnapshot, SCHEMA_VERSIONS, SchemaVersion

__all__ = [
    "asset_library_store",
    "canvas_store",
    "conversation_store",
    "history_store",
    "project_store",
    "prompt_library_store",
    "provider_config_store",
    "storage_settings_store",
    "workflow_store",
    "LegacySnapshot",
    "SCHEMA_VERSIONS",
    "SchemaVersion",
]
