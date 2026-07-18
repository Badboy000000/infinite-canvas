"""数据 PR-3 · CLI smoke。

`python main.py data-import <domain> [--dry-run]` / `data-reconcile <domain>`
subprocess 冒烟。验证输出为稳定 JSON（可 `json.loads`）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_cli(args, db_path):
    env = dict(os.environ)
    env["DATA_DB_PATH"] = str(db_path)
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )


def _last_json_line(text: str) -> dict:
    lines = [line for line in text.splitlines() if line.strip()]
    assert lines, "CLI 无 stdout 输出"
    return json.loads(lines[-1])


def test_data_import_dry_run_canvas(tmp_path):
    db = tmp_path / "cli_smoke.db"
    r = _run_cli(["migrate", "head"], db)
    assert r.returncode == 0, r.stderr

    r = _run_cli(["data-import", "canvas", "--dry-run"], db)
    assert r.returncode == 0, r.stderr
    doc = _last_json_line(r.stdout)
    assert doc["domain"] == "canvas"
    assert doc["dry_run"] is True
    assert "inserted" in doc
    assert "skipped" in doc


def test_data_reconcile_canvas(tmp_path):
    db = tmp_path / "cli_reconcile.db"
    r = _run_cli(["migrate", "head"], db)
    assert r.returncode == 0, r.stderr

    r = _run_cli(["data-reconcile", "canvas"], db)
    assert r.returncode == 0, r.stderr
    doc = _last_json_line(r.stdout)
    assert doc["domain"] == "canvas"
    assert "counts" in doc
    assert "json" in doc["counts"] and "db" in doc["counts"]
    assert "missing" in doc
    assert "field_diffs" in doc


def test_data_import_missing_domain_error(tmp_path):
    db = tmp_path / "cli_err.db"
    r = _run_cli(["migrate", "head"], db)
    assert r.returncode == 0

    r = _run_cli(["data-import"], db)
    assert r.returncode == 2
    doc = _last_json_line(r.stdout)
    assert doc.get("error") == "missing_domain"
