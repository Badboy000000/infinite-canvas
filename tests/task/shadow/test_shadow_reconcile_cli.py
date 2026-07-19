"""任务 PR-3 · `scripts/task_shadow_reconcile.py` CLI 稳定 JSON 契约测试。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_reconcile_cli_outputs_stable_json(tmp_path):
    """CLI 在空 DB 上 exit=0 并输出预期键。"""

    env = dict(os.environ)
    env["DATA_DB_PATH"] = str(tmp_path / "reconcile_cli.db")
    env["TASK_SHADOW_ENABLE"] = "false"  # CLI 只对账，与开关无关
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "task_shadow_reconcile.py")],
        env=env,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert set(payload.keys()) == {
        "canvas_tasks_count",
        "shadow_tasks_count",
        "missing_shadow",
        "extra_shadow",
        "kind_stats",
    }
    assert payload["canvas_tasks_count"] == 0
    assert payload["shadow_tasks_count"] == 0
    assert payload["missing_shadow"] == []
    assert payload["extra_shadow"] == []
    assert payload["kind_stats"] == {}


def test_reconcile_reports_missing_shadow(monkeypatch, tmp_path):
    """CANVAS_TASKS 有 entry、shadow 无副本 → missing_shadow 报告该 canvas_task_id。"""

    from tests.task.shadow._helpers import isolated_shadow_db
    import main

    with isolated_shadow_db(monkeypatch, tmp_path):
        with main.CANVAS_TASK_LOCK:
            main.CANVAS_TASKS["canvas_img_mismatch"] = {
                "id": "canvas_img_mismatch",
                "type": "online-image",
                "status": "queued",
                "created_at": 0.0,
                "updated_at": 0.0,
            }
        try:
            from scripts.task_shadow_reconcile import reconcile

            report = reconcile()
            assert report["canvas_tasks_count"] >= 1
            assert "canvas_img_mismatch" in report["missing_shadow"]
        finally:
            with main.CANVAS_TASK_LOCK:
                main.CANVAS_TASKS.pop("canvas_img_mismatch", None)
