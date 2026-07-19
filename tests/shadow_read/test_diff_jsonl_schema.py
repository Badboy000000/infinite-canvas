"""数据 PR-4 · Diff JSONL schema 稳定键位断言。

`data/shadow_diff/<domain>/<yyyymmdd>.jsonl` 每行一条 JSON，键位必须与
`DIFF_RECORD_KEYS` 一致——下游 grep / 对账工具依赖此契约。
"""

from __future__ import annotations

import datetime as dt
import json

from app.shadow_read.diff_writer import DIFF_RECORD_KEYS, build_diff_record


def test_diff_record_keys_stable():
    assert DIFF_RECORD_KEYS == (
        "ts",
        "domain",
        "request_id",
        "missing_in_db",
        "missing_in_json",
        "field_diffs",
    )


def test_build_diff_record_shape_and_types():
    rec = build_diff_record(
        domain="project",
        missing_in_db=["p1", "p2"],
        missing_in_json=["p3"],
        field_diffs=[
            {"legacy_id": "p1", "field": "name", "json_value": "a", "db_value": "b"}
        ],
        request_id="req-42",
    )
    # keys present
    for key in DIFF_RECORD_KEYS:
        assert key in rec, f"missing key: {key}"
    assert set(rec.keys()) == set(DIFF_RECORD_KEYS)

    # types
    assert isinstance(rec["ts"], str)
    # ts is ISO 8601 with tz info
    parsed = dt.datetime.fromisoformat(rec["ts"])
    assert parsed.tzinfo is not None

    assert rec["domain"] == "project"
    assert rec["request_id"] == "req-42"
    assert rec["missing_in_db"] == ["p1", "p2"]
    assert rec["missing_in_json"] == ["p3"]
    assert isinstance(rec["field_diffs"], list)

    # serializable
    line = json.dumps(rec)
    assert isinstance(line, str)


def test_build_diff_record_supports_none_request_id():
    rec = build_diff_record(
        domain="prompt_library",
        missing_in_db=[],
        missing_in_json=[],
        field_diffs=[],
    )
    assert rec["request_id"] is None
    assert rec["missing_in_db"] == []
    assert rec["missing_in_json"] == []
    assert rec["field_diffs"] == []


def test_build_diff_record_sorts_missing_ids():
    rec = build_diff_record(
        domain="project",
        missing_in_db=["zeta", "alpha", "mu"],
        missing_in_json=["c", "b", "a"],
        field_diffs=[],
    )
    assert rec["missing_in_db"] == ["alpha", "mu", "zeta"]
    assert rec["missing_in_json"] == ["a", "b", "c"]
