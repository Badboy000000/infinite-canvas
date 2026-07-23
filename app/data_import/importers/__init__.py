"""`app.data_import.importers` — 7 类 domain importer 注册表。"""
from __future__ import annotations

from . import (
    asset_library,
    canvas,
    identity,
    project,
    prompt_library,
    provider_config,
    workflow_definition,
)

IMPORTERS = {
    "project": project,
    "provider_config": provider_config,
    "prompt_library": prompt_library,
    "workflow_definition": workflow_definition,
    "asset_library": asset_library,
    "canvas": canvas,
    "identity": identity,
}


__all__ = [
    "IMPORTERS",
    "asset_library",
    "canvas",
    "identity",
    "project",
    "prompt_library",
    "provider_config",
    "workflow_definition",
]
