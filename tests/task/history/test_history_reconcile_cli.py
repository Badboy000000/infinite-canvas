"""任务 PR-4 · `scripts/task_history_reconcile.py` CLI 稳定 JSON 契约测试。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_reconcile_cli_outputs_stable_json(tmp_path):
    """CLI 在空 DB + 空 history.json 上 exit=0 并输出预期键。"""

    env = dict(os.environ)
    env["DATA_DB_PATH"] = str(tmp_path / "reconcile_cli.db")
    env["TASK_HISTORY_ENABLE"] = "false"
    # 隔离 HISTORY_FILE：主进程 history.json 可能不为空，CLI 需通过环境变量
    # 或额外机制解耦；此处直接用一个空 history file 覆盖 main.HISTORY_FILE
    # 通过 subprocess PYTHONPATH 无法直接注入，因此这里断言键位与 exit code
    # ——非空 history 情形由 `reconcile()` 直接调用测试覆盖。
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "task_history_reconcile.py")],
        env=env,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert set(payload.keys()) == {
        "history_json_count",
        "derived_count",
        "missing_derived",
        "extra_derived",
        "kind_stats",
    }
    # derived side 是新建的空 DB —— 保证为 0
    assert payload["derived_count"] == 0
    assert isinstance(payload["missing_derived"], list)
    assert isinstance(payload["extra_derived"], list)
    assert isinstance(payload["kind_stats"], dict)


def test_reconcile_reports_missing_derived(monkeypatch, tmp_path):
    """history.json 有 record、事实层无副本 → missing_derived 报告 idempotency key。"""

    from tests.task.history._helpers import isolated_history_db
    import json as json_mod
    import main

    with isolated_history_db(monkeypatch, tmp_path):
        history_path = tmp_path / "history.json"
        record = {
            "prompt": "reconcile-missing",
            "images": ["/output/miss.png"],
            "type": "online",
            "task_id": "recon-miss-upstream",
            "timestamp": 555.0,
        }
        history_path.write_text(json_mod.dumps([record]), encoding="utf-8")
        monkeypatch.setattr(main, "HISTORY_FILE", str(history_path))

        from scripts.task_history_reconcile import reconcile

        report = reconcile()
        assert report["history_json_count"] == 1
        assert len(report["missing_derived"]) == 1
        assert report["missing_derived"][0].startswith("history:")
        assert report["derived_count"] == 0
