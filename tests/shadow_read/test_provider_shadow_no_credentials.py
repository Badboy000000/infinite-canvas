"""数据 PR-4 · Provider shadow 双读密钥不入库 P0 硬约束。

Provider shadow diff 日志中**密钥字段永不出现**——走 store
`_safe_provider_records` 深层脱敏；本测试对 diff JSONL 全域 grep=0 断言，
覆盖 `api_key` / `Authorization` / `sk-` / `Bearer` 等常见 token 形式。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline


SECRET_TOKENS = (
    "sk-EVIL-LEAK-2026",
    "Bearer LEAK-2026",
    "AKIA_SECRET_ACCESS_KEY_EVIL",
    "priv_key_evil_leak_2026",
    "auth_password_evil",
)


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    with isolated_shadow_env(monkeypatch, tmp_path) as sandbox:
        yield sandbox


@pytest.fixture
def providers_file_with_secrets(tmp_path, monkeypatch, isolated_env):
    """Write an api_providers.json chock-full of credential-shaped fields."""
    import main

    api_file = tmp_path / "api_providers.json"
    # Provider list with keys sprinkled at every level & shape we can think of.
    api_file.write_text(
        json.dumps([
            {
                "id": "provider-1",
                "name": "provider-1-name",
                "base_url": "https://example.com/api?api_key=sk-EVIL-LEAK-2026&x=1",
                "protocol": "openai",
                "image_request_mode": "async",
                "enabled": True,
                "primary": True,
                # sensitive top-level: api_key must be stripped
                "api_key": "sk-EVIL-LEAK-2026",
                "authorization": "Bearer LEAK-2026",
                "password": "auth_password_evil",
                "private_key": "priv_key_evil_leak_2026",
                # nested inside rh_apps
                "rh_apps": [{
                    "id": "app1",
                    "name": "App One",
                    "credentials": {
                        "access_key": "AKIA_SECRET_ACCESS_KEY_EVIL",
                        "secret_key": "priv_key_evil_leak_2026",
                    },
                }],
                # a name/value marker: value should be scrubbed
                "endpoint_overrides": [
                    {"name": "api_key", "value": "sk-EVIL-LEAK-2026"},
                    {"name": "safe_field", "value": "should-remain"},
                ],
            },
            {
                "id": "provider-2",
                "name": "provider-2-name",
                "base_url": "https://example.com",
                "protocol": "openai",
                "enabled": False,
                "primary": False,
                "token": "Bearer LEAK-2026",
            },
        ], ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "API_PROVIDERS_FILE", str(api_file))
    yield api_file


def _load_providers_via_store():
    from app.stores import provider_config_store

    return provider_config_store.load_api_providers()


def test_provider_shadow_diff_never_contains_secrets(
    monkeypatch, providers_file_with_secrets, tmp_path, isolated_env
):
    """启用 shadow、DB 空 → 全部 legacy_id 进 missing_in_db；
    落盘 JSONL 里对所有已知敏感 token 断言 grep=0。"""
    migrate_baseline(tmp_path)

    monkeypatch.setenv("SHADOW_READ_PROVIDER_CONFIG", "true")

    _load_providers_via_store()

    diff_root = Path(tmp_path) / "shadow_diff" / "provider_config"
    files = list(diff_root.glob("*.jsonl"))
    assert files, "expected at least one shadow diff file"

    for path in files:
        text = path.read_text(encoding="utf-8")
        for token in SECRET_TOKENS:
            assert token not in text, (
                f"密钥 token {token!r} 泄漏到 shadow diff {path.name}"
            )
        for banned in (
            "api_key",
            "authorization",
            "private_key",
            "secret_key",
            "access_key",
            "password",
        ):
            # 允许 legacy_id 里出现名字，但字段名不应作为 key 存在
            # 简单 grep 断言：以字符串形式出现即视为不安全
            assert banned not in text.lower(), (
                f"敏感字段名 {banned!r} 出现在 shadow diff：{path.name}"
            )


def test_provider_shadow_records_only_whitelisted_scalar_fields(
    monkeypatch, providers_file_with_secrets, tmp_path, isolated_env
):
    """field_diffs 里出现的 `field` 必须落在 PROVIDER_STABLE_FIELDS 白名单内。"""
    from app.shadow_read.fields import PROVIDER_STABLE_FIELDS
    from app.data_import import import_domain

    migrate_baseline(tmp_path)
    # import first so common legacy_ids exist and we get field_diffs (not missing)
    import_domain(
        "provider_config",
        source_path=str(providers_file_with_secrets),
        dry_run=False,
    )
    # 篡改一处白名单字段
    api_file = providers_file_with_secrets
    payload = json.loads(api_file.read_text(encoding="utf-8"))
    payload[0]["name"] = "provider-1-renamed"
    api_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setenv("SHADOW_READ_PROVIDER_CONFIG", "true")
    _load_providers_via_store()

    diff_root = Path(tmp_path) / "shadow_diff" / "provider_config"
    files = list(diff_root.glob("*.jsonl"))
    assert files
    seen_fields: set[str] = set()
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            for d in rec["field_diffs"]:
                seen_fields.add(d["field"])
    assert seen_fields, "expected at least one field diff (name change)"
    assert seen_fields.issubset(PROVIDER_STABLE_FIELDS), (
        f"field_diffs contains non-whitelisted fields: "
        f"{seen_fields - PROVIDER_STABLE_FIELDS}"
    )


def test_provider_shadow_disabled_default_no_diff_file(
    monkeypatch, providers_file_with_secrets, tmp_path, isolated_env
):
    monkeypatch.delenv("SHADOW_READ_PROVIDER_CONFIG", raising=False)
    _load_providers_via_store()
    diff_root = Path(tmp_path) / "shadow_diff" / "provider_config"
    assert not diff_root.exists()
