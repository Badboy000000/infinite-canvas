"""数据 PR-3 · Provider importer 密钥不入库断言。

Provider importer 走 `provider_config_store._safe_provider_records` 深层脱敏；
本测试验证：

1. DB `provider_configs.raw_json` 内不含 `api_key` / `authorization` / `secret`
   / `token` / `Bearer` 明文；
2. 白名单外字段（如 `api_key`）不进 raw_json 也不进 DB 独立列；
3. 嵌套 dict / list / URL query 中的密钥标记同样脱敏。

模式测试参考 `tests/stores/test_provider_snapshot_deep_sanitize`（若存在），
本测试独立于其存在与否。
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path


def _isolated_migrate(monkeypatch, tmp_path) -> Path:
    import main
    from app.db import engine as db_engine
    from app.db import session as db_session

    db = tmp_path / "pr3_creds.db"
    monkeypatch.setattr(main, "DATA_DB_PATH", str(db))
    db_engine.reset_engine()
    db_session._SessionLocal = None
    db_engine.run_migrations("head")
    return db


_SENSITIVE_TOKENS = ("api_key", "apiKey", "authorization", "Authorization",
                     "SECRET_VALUE_LEAK", "sk-EVIL", "Bearer LEAK")


def test_provider_credentials_never_touch_db(monkeypatch, tmp_path):
    providers_path = tmp_path / "api_providers.json"
    providers_path.write_text(json.dumps([
        {
            "id": "p1", "name": "OpenAI",
            "protocol": "openai", "base_url": "https://x.example/v1?apikey=SECRET_VALUE_LEAK",
            "enabled": True, "primary": True,
            "api_key": "sk-EVIL",
            "authorization": "Bearer LEAK",
            "raw": {"api_key": "sk-EVIL", "token": "SECRET_VALUE_LEAK"},
            "workflowJson": {
                "nodes": [{"api_key": "sk-EVIL", "authorization": "Bearer LEAK"}]
            },
            "endpoint_overrides": [
                {"name": "api_key", "value": "sk-EVIL"},
                {"name": "authorization", "value": "Bearer LEAK"},
                {"name": "base_url", "value": "https://x.example/v1"},
            ],
        },
    ], ensure_ascii=False), encoding="utf-8")

    import main
    monkeypatch.setattr(main, "API_PROVIDERS_FILE", str(providers_path))

    db = _isolated_migrate(monkeypatch, tmp_path)

    from app.data_import import import_domain

    outcome = import_domain("provider_config", source_path=str(providers_path))
    assert outcome.inserted == 1

    # 断言 DB 全量数据中不含密钥字面量
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute("SELECT id, raw_json FROM provider_configs").fetchall()
        assert len(rows) == 1
        for _id, raw in rows:
            for tok in _SENSITIVE_TOKENS:
                assert tok not in (raw or ""), (
                    f"密钥 {tok!r} 泄漏在 raw_json：{raw!r}"
                )
        # 全表 dump 验证
        dump = "\n".join(
            "\t".join(str(x) for x in row)
            for row in conn.execute("SELECT * FROM provider_configs").fetchall()
        )
        for tok in _SENSITIVE_TOKENS:
            assert tok not in dump, f"密钥 {tok!r} 在 provider_configs 表内出现"
    finally:
        conn.close()


def test_provider_importer_calls_safe_records(monkeypatch, tmp_path):
    """AST 断言：provider importer 复用 `_safe_provider_records`，禁自造字段过滤。"""
    import ast

    src = (
        Path(__file__).resolve().parents[2]
        / "app" / "data_import" / "importers" / "provider_config.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    seen = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "_safe_provider_records":
            seen = True
            break
        if isinstance(node, ast.Name) and node.id == "_safe_provider_records":
            seen = True
            break
    assert seen, (
        "provider_config importer 必须调用 provider_config_store."
        "_safe_provider_records，禁自造字段过滤"
    )
