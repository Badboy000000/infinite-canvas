"""Legacy JSON snapshot contract shared by Store facades.

Snapshots are an internal migration seam. They do not alter Store load/save
behavior and are deliberately independent from the database layer.
"""
from __future__ import annotations

import copy
import json
import os
from types import MappingProxyType
from typing import Any, Mapping, TypedDict


LEGACY_JSON_SCHEMA_VERSION = "v1_legacy_json"


class SchemaVersion:
    """Initial schema version assigned to each legacy JSON Store domain."""

    CANVAS = LEGACY_JSON_SCHEMA_VERSION
    PROJECT = LEGACY_JSON_SCHEMA_VERSION
    ASSET_LIBRARY = LEGACY_JSON_SCHEMA_VERSION
    PROMPT_LIBRARY = LEGACY_JSON_SCHEMA_VERSION
    PROVIDER_CONFIG = LEGACY_JSON_SCHEMA_VERSION
    HISTORY = LEGACY_JSON_SCHEMA_VERSION
    CONVERSATION = LEGACY_JSON_SCHEMA_VERSION
    WORKFLOW = LEGACY_JSON_SCHEMA_VERSION
    STORAGE_SETTINGS = LEGACY_JSON_SCHEMA_VERSION


SCHEMA_VERSIONS: Mapping[str, str] = MappingProxyType({
    "canvas": SchemaVersion.CANVAS,
    "project": SchemaVersion.PROJECT,
    "asset_library": SchemaVersion.ASSET_LIBRARY,
    "prompt_library": SchemaVersion.PROMPT_LIBRARY,
    "provider_config": SchemaVersion.PROVIDER_CONFIG,
    "history": SchemaVersion.HISTORY,
    "conversation": SchemaVersion.CONVERSATION,
    "workflow": SchemaVersion.WORKFLOW,
    "storage_settings": SchemaVersion.STORAGE_SETTINGS,
})


class LegacyFields(TypedDict):
    id: str | None
    path: str | None
    url: str | None
    owner_label: str | None


class LegacySnapshot(TypedDict):
    payload: Any
    legacy: LegacyFields
    raw_json: str
    schema_version: str


def serialize_json(value: Any) -> str:
    """Return deterministic UTF-8 JSON when no source bytes are available."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def parse_raw_json(raw_json: str, fallback: Any) -> Any:
    """Parse raw snapshot text while accepting the storage-settings BOM."""

    try:
        return json.loads(raw_json.lstrip("\ufeff"))
    except (TypeError, ValueError):
        return copy.deepcopy(fallback)


def read_json_source(
    path: str | os.PathLike[str] | None, fallback: Any
) -> tuple[Any, str]:
    """Build payload and raw text from one immutable source-file read.

    Opening a path once also gives replacement-safe semantics: an atomic rename
    may change what future opens see, but payload and ``raw_json`` are both
    derived from the bytes held by this open file descriptor. Missing,
    unreadable, or undecodable sources use one deterministic fallback value and
    do not retry through a Store load helper.
    """

    if path:
        try:
            with open(path, "rb") as source:
                raw_json = source.read().decode("utf-8")
            return parse_raw_json(raw_json, fallback), raw_json
        except (OSError, UnicodeError):
            pass
    payload = copy.deepcopy(fallback)
    return payload, serialize_json(payload)


def build_snapshot(
    payload: Any,
    *,
    raw_json: str,
    schema_version: str,
    legacy_id: str | None = None,
    legacy_path: str | None = None,
    legacy_url: str | None = None,
    legacy_owner_label: str | None = None,
) -> LegacySnapshot:
    """Build an isolated snapshot so callers cannot mutate Store state by alias."""

    return {
        "payload": copy.deepcopy(payload),
        "legacy": {
            "id": legacy_id,
            "path": legacy_path,
            "url": legacy_url,
            "owner_label": legacy_owner_label,
        },
        "raw_json": raw_json,
        "schema_version": schema_version,
    }
