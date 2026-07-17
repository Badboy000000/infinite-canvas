from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

from app.stores import SCHEMA_VERSIONS, SchemaVersion
from app.stores import (
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


@pytest.fixture()
def legacy_sources(tmp_path, monkeypatch):
    import main

    data_dir = tmp_path / "data"
    canvas_dir = data_dir / "canvases"
    conversation_dir = data_dir / "conversations"
    data_dir.mkdir()
    canvas_dir.mkdir()
    conversation_dir.mkdir()

    paths = {
        "canvas": canvas_dir / "canvas-1.json",
        "project": data_dir / "projects.json",
        "asset_library": data_dir / "asset_library.json",
        "prompt_library": data_dir / "prompt_library.json",
        "provider_config": data_dir / "api_providers.json",
        "history": data_dir / "history.json",
        "conversation": conversation_dir / "owner-1" / "conversation-1.json",
        "workflow": data_dir / "runninghub_workflow_store.json",
        "storage_settings": data_dir / "storage_settings.json",
    }

    monkeypatch.setattr(main, "DATA_DIR", str(data_dir), raising=True)
    monkeypatch.setattr(main, "CANVAS_DIR", str(canvas_dir), raising=True)
    monkeypatch.setattr(main, "CONVERSATION_DIR", str(conversation_dir), raising=True)
    monkeypatch.setattr(main, "PROJECTS_PATH", str(paths["project"]), raising=True)
    monkeypatch.setattr(main, "ASSET_LIBRARY_PATH", str(paths["asset_library"]), raising=True)
    monkeypatch.setattr(main, "PROMPT_LIBRARY_PATH", str(paths["prompt_library"]), raising=True)
    monkeypatch.setattr(main, "API_PROVIDERS_FILE", str(paths["provider_config"]), raising=True)
    monkeypatch.setattr(main, "HISTORY_FILE", str(paths["history"]), raising=True)
    monkeypatch.setattr(main, "RUNNINGHUB_WORKFLOW_STORE_FILE", str(paths["workflow"]), raising=True)
    monkeypatch.setattr(main, "STORAGE_SETTINGS_FILE", str(paths["storage_settings"]), raising=True)
    monkeypatch.setattr(main, "GLOBAL_LOOP", None, raising=True)

    canvas_store.save_canvas({
        "id": "canvas-1",
        "title": "Golden canvas",
        "owner": "legacy-owner",
        "url": "/canvas/canvas-1",
        "nodes": [{"id": "node-1", "future_field": {"kept": True}}],
        "connections": [],
    })
    project_store.save_projects([{"id": "project-1", "name": "Golden project"}])
    asset_library_store.save_asset_library({
        "active_library_id": "library-1",
        "libraries": [{"id": "library-1", "name": "Golden assets", "categories": []}],
        "categories": [],
    })
    prompt_library_store.save_prompt_libraries({
        "active_library_id": "custom",
        "libraries": [{
            "id": "custom", "name": "Golden prompts", "categories": [], "items": [],
        }],
    })
    provider_config_store.save_api_providers([{
        "id": "provider-1",
        "name": "Golden provider",
        "base_url": "https://provider.invalid/v1",
        "protocol": "openai",
        "enabled": True,
        "primary": False,
    }])
    history_store.save_to_history({"id": "history-1", "timestamp": 1, "url": "/output/one.png"})
    conversation_store.save_conversation("owner-1", {
        "id": "conversation-1", "title": "Golden conversation", "messages": [],
    })
    workflow_store.save_runninghub_workflow_store({
        "workflow-1": {"name": "Golden workflow", "future_field": "kept"},
    })
    storage_raw = b'\xef\xbb\xbf{\n  "upload": "uploads",\n  "generated": "output",\n  "local": "local"\n}'
    paths["storage_settings"].write_bytes(storage_raw)

    return paths


def _assert_golden(
    snapshot, *, path: Path, legacy_id=None, legacy_url=None, owner_label=None
):
    assert set(snapshot) == {"payload", "legacy", "raw_json", "schema_version"}
    assert snapshot["schema_version"] == "v1_legacy_json"
    assert snapshot["legacy"] == {
        "id": legacy_id,
        "path": str(path),
        "url": legacy_url,
        "owner_label": owner_label,
    }
    assert isinstance(snapshot["raw_json"], str)


def test_schema_version_table_is_complete_and_immutable():
    assert SCHEMA_VERSIONS == {
        "canvas": "v1_legacy_json",
        "project": "v1_legacy_json",
        "asset_library": "v1_legacy_json",
        "prompt_library": "v1_legacy_json",
        "provider_config": "v1_legacy_json",
        "history": "v1_legacy_json",
        "conversation": "v1_legacy_json",
        "workflow": "v1_legacy_json",
        "storage_settings": "v1_legacy_json",
    }
    assert SchemaVersion.CANVAS == "v1_legacy_json"
    with pytest.raises(TypeError):
        SCHEMA_VERSIONS["canvas"] = "v2"  # type: ignore[index]


def test_each_store_exposes_the_frozen_snapshot_shape(legacy_sources):
    snapshots = {
        "canvas": canvas_store.snapshot("canvas-1"),
        "project": project_store.snapshot(),
        "asset_library": asset_library_store.snapshot(),
        "prompt_library": prompt_library_store.snapshot(),
        "provider_config": provider_config_store.snapshot(),
        "history": history_store.snapshot(),
        "conversation": conversation_store.snapshot("owner-1", "conversation-1"),
        "workflow": workflow_store.snapshot(),
        "storage_settings": storage_settings_store.snapshot(),
    }

    for domain, value in snapshots.items():
        _assert_golden(
            value,
            path=legacy_sources[domain],
            legacy_id={"canvas": "canvas-1", "conversation": "conversation-1"}.get(domain),
            legacy_url={"canvas": "/canvas/canvas-1"}.get(domain),
            owner_label={"canvas": "legacy-owner", "conversation": "owner-1"}.get(domain),
        )
        json.dumps(value, ensure_ascii=False)

    assert snapshots["canvas"]["legacy"]["url"] == "/canvas/canvas-1"
    assert snapshots["canvas"]["payload"]["nodes"][0]["future_field"] == {"kept": True}
    assert snapshots["workflow"]["payload"]["workflow-1"]["future_field"] == "kept"


@pytest.mark.parametrize(
    ("domain", "snapshot_factory"),
    [
        ("canvas", lambda: canvas_store.snapshot("canvas-1")),
        ("project", project_store.snapshot),
        ("asset_library", asset_library_store.snapshot),
        ("prompt_library", prompt_library_store.snapshot),
        ("history", history_store.snapshot),
        ("conversation", lambda: conversation_store.snapshot("owner-1", "conversation-1")),
        ("workflow", workflow_store.snapshot),
        ("storage_settings", storage_settings_store.snapshot),
    ],
)
def test_raw_json_is_byte_equivalent_to_the_legacy_source(
    legacy_sources, domain, snapshot_factory
):
    snapshot = snapshot_factory()
    assert snapshot["raw_json"].encode("utf-8") == legacy_sources[domain].read_bytes()


def test_provider_raw_json_is_the_sanitized_payload_not_source_bytes(legacy_sources):
    snapshot = provider_config_store.snapshot()

    assert json.loads(snapshot["raw_json"]) == snapshot["payload"]


def test_every_snapshot_payload_matches_its_single_raw_source(legacy_sources):
    snapshots = [
        canvas_store.snapshot("canvas-1"),
        project_store.snapshot(),
        asset_library_store.snapshot(),
        prompt_library_store.snapshot(),
        provider_config_store.snapshot(),
        history_store.snapshot(),
        conversation_store.snapshot("owner-1", "conversation-1"),
        workflow_store.snapshot(),
        storage_settings_store.snapshot(),
    ]

    for snapshot in snapshots:
        assert json.loads(snapshot["raw_json"].lstrip("\ufeff")) == snapshot["payload"]


def test_snapshot_payload_is_detached_from_later_mutation(legacy_sources):
    first = canvas_store.snapshot("canvas-1")
    first["payload"]["nodes"].clear()

    second = canvas_store.snapshot("canvas-1")
    assert second["payload"]["nodes"] == [
        {"id": "node-1", "future_field": {"kept": True}}
    ]


def test_snapshot_uses_one_open_source_when_path_is_replaced(
    legacy_sources, monkeypatch
):
    path = legacy_sources["project"]
    original_payload = [{"id": "before-replace", "name": "Before"}]
    replacement_payload = [{"id": "after-replace", "name": "After"}]
    path.write_text(json.dumps(original_payload), encoding="utf-8")

    real_open = builtins.open
    source_open_count = 0

    class ReplaceAfterRead:
        def __init__(self, source):
            self._source = source

        def __enter__(self):
            self._source.__enter__()
            return self

        def read(self, *args, **kwargs):
            return self._source.read(*args, **kwargs)

        def __exit__(self, exc_type, exc, traceback):
            result = self._source.__exit__(exc_type, exc, traceback)
            path.with_suffix(".replacement").write_text(
                json.dumps(replacement_payload), encoding="utf-8"
            )
            path.with_suffix(".replacement").replace(path)
            return result

        def __getattr__(self, name):
            return getattr(self._source, name)

    def replacing_open(file, *args, **kwargs):
        nonlocal source_open_count
        source = real_open(file, *args, **kwargs)
        if Path(file) == path and "r" in str(args[0] if args else kwargs.get("mode", "r")):
            source_open_count += 1
            if source_open_count == 1:
                return ReplaceAfterRead(source)
        return source

    monkeypatch.setattr(builtins, "open", replacing_open)

    snapshot = project_store.snapshot()

    assert source_open_count == 1
    assert snapshot["payload"] == original_payload
    assert json.loads(snapshot["raw_json"]) == original_payload
    assert json.loads(path.read_text(encoding="utf-8")) == replacement_payload


def test_provider_snapshot_uses_a_safe_field_whitelist(legacy_sources):
    secret = "plain-provider-secret-must-not-survive"
    source = [{
        "id": "provider-secret-test",
        "name": "Provider secret test",
        "base_url": "https://provider.invalid/v1",
        "protocol": "openai",
        "enabled": True,
        "api_key": secret,
        "access_token": secret,
        "unknown_extension": {"secret": secret},
        "rh_apps": [{"id": "app-1", "name": "App", "wallet_key": secret}],
    }]
    legacy_sources["provider_config"].write_text(
        json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    snapshot = provider_config_store.snapshot()
    serialized = json.dumps(snapshot, ensure_ascii=False)
    raw_payload = json.loads(snapshot["raw_json"])

    assert secret not in serialized
    assert raw_payload
    assert all(
        set(provider) <= provider_config_store.PROVIDER_SNAPSHOT_FIELDS
        for provider in raw_payload
    )
    assert all(
        set(provider) <= provider_config_store.PROVIDER_SNAPSHOT_FIELDS
        for provider in snapshot["payload"]
    )
    assert "api_key" not in raw_payload[0]
    assert "access_token" not in raw_payload[0]
    assert "unknown_extension" not in raw_payload[0]


def test_provider_snapshot_deeply_removes_secret_sentinels(legacy_sources):
    sentinels = {
        "name_value": "sentinel-name-value",
        "query": "sentinel-url-query",
        "raw": "sentinel-raw",
        "workflow": "sentinel-workflow-json",
        "unknown": "sentinel-unknown-nested",
    }
    source = [{
        "id": "provider-deep-secret-test",
        "name": "Provider deep secret test",
        "base_url": (
            "https://provider.invalid/v1?api_key=" + sentinels["query"] + "&region=cn"
        ),
        "protocol": "runninghub",
        "enabled": True,
        "rh_apps": [{
            "id": "app-1",
            "fields": [{"name": "api_key", "value": sentinels["name_value"]}],
        }],
        "rh_workflows": [{
            "id": "workflow-1",
            "raw": {
                "headers": {"Authorization": "Bearer " + sentinels["raw"]},
            },
            "workflowJson": json.dumps({
                "node": {"inputs": {"access_token": sentinels["workflow"]}},
            }),
            "future_extension": {
                "unknown": [{"client_secret": sentinels["unknown"]}],
            },
        }],
    }]
    legacy_sources["provider_config"].write_text(
        json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    snapshot = provider_config_store.snapshot()

    for surface in (snapshot["payload"], snapshot["raw_json"], snapshot["legacy"]):
        serialized = json.dumps(surface, ensure_ascii=False)
        for sentinel in sentinels.values():
            assert sentinel not in serialized
