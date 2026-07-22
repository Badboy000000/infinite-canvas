"""Wave 3-K 前置就绪度评估 · Canvas shadow_read 合成负载探针抗回归。

**声明**：本测试**不是**真实生产观察 · 是 `tools/synth_shadow_read_probe.py`
自身的工作性抗回归，编号 T80-T89（Lead 单点分配 Wave 3-K 前置就绪度评估
工作池）。

场景覆盖：

- T80 · probe 模块可 import 且导出稳定 API
- T81 · scale=10 单场景 A 命中率 == 1.0（100/100）
- T82 · scale=10 单场景 B 差异率 ≈ expected（bound ≤ 5pp）
- T83 · scale=10 单场景 C write latency P95 < 500ms
- T84 · scale=10 单场景 D shadow_write fail-safe（异常不上抛 + JSON 主写落盘）
- T85 · env fact-check 稳定键位存在
- T86 · full CLI end-to-end scale=10 输出 JSON schema 稳定
- T87 · asymmetric normalizer observation 触发（P2 · CB-P5-08）
- T88 · full CLI scale=50 · 标 `slow`（可选，5-10s）
- T89 · full CLI scale=500 · 标 `skip` 只作为文档存在（scale=500 单次 ~90s+，避开 CI）

零污染保证：所有场景走 pytest `tmp_path` fixture + 手工 setattr/restore
`main.DATA_DIR / CANVAS_DIR / DATA_DB_PATH`。不改动 `data/canvas/` /
`data/app.db` / `data/shadow_diff/`。
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# T80 · module import + public API stable
# ---------------------------------------------------------------------------


def test_T80_probe_module_public_api_stable():
    """T80 · probe 模块公共 API stable（防未来 refactor 破坏 CLI 与集成点）。"""

    from tools import synth_shadow_read_probe as probe

    assert hasattr(probe, "run_probe")
    assert hasattr(probe, "main_cli")
    assert hasattr(probe, "_environment_fact_check")
    assert probe.SCHEMA_VERSION == "synth-probe/v1"
    assert "synthetic" in probe.SYNTHETIC_DECLARATION.lower()
    assert probe.ALLOWED_SCALES == (10, 50, 200, 500)


# ---------------------------------------------------------------------------
# T81-T85 · run_probe internal helpers on small scale
# ---------------------------------------------------------------------------


@pytest.fixture
def small_probe_report(tmp_path):
    """跑一次 scale=10 的完整 probe，返回 report dict。所有其它 tmp 场景共享。"""

    from tools.synth_shadow_read_probe import run_probe

    workspace = tmp_path / "probe_ws"
    workspace.mkdir()
    return run_probe(
        scale=10,
        seed=1337,
        loads=100,
        saves=200,
        tx_fail_iters=3,
        tmp_path=workspace,
    )


def test_T81_scenario_A_hit_rate_all_present(small_probe_report):
    """T81 · scale=10 场景 A：N 双写 → 100 次 load missing_in_db 全空。"""

    scen = small_probe_report["scenarios"]["A_hit_rate"]
    assert scen["db_inserted"] == 10
    assert scen["loads_attempted"] == 100
    assert scen["hit_rate"] == 1.0
    assert scen["records_with_missing_in_db_nonempty"] == 0
    assert scen["verdict"] == "PASS"


def test_T82_scenario_B_diff_rate_within_bound(small_probe_report):
    """T82 · scale=10 场景 B：DB 缺 10% → observed diff rate 与 expected 差 ≤ 5pp。"""

    scen = small_probe_report["scenarios"]["B_diff_rate"]
    assert scen["db_inserted"] == 9
    assert scen["missing_ids_count"] == 1
    assert scen["observed_diff_rate"] is not None
    assert scen["expected_diff_rate"] is not None
    assert scen["delta_vs_expected"] <= 0.05
    assert scen["verdict"] == "PASS"


def test_T83_scenario_C_write_latency_under_bound(small_probe_report):
    """T83 · scale=10 场景 C：200 次 save P95 < 500ms（治理方案硬约束）。"""

    scen = small_probe_report["scenarios"]["C_write_latency"]
    assert scen["saves_attempted"] == 200
    assert scen["saves_bubbled_error"] == 0
    assert scen["latency_ms"]["p95_ms"] < 500.0
    assert scen["verdict"] == "PASS"


def test_T84_scenario_D_fail_safe_isolated(small_probe_report):
    """T84 · scale=10 场景 D：DB 锁 → shadow_write 失败不上抛 + JSON 主写落盘。"""

    scen = small_probe_report["scenarios"]["D_tx_fail_safe"]
    assert scen["iterations"] == 3
    assert scen["saves_bubbled_exception"] == 0
    assert scen["saves_completed_no_exception"] == 3
    # JSON 主写必须落盘（主路径与 DB 完全解耦）
    assert scen["json_primary_write_files_actually_updated"] == 3
    # shadow_write 内部至少捕获了一条 failure 记录
    assert scen["shadow_write_failure_records_logged"] >= 1
    assert scen["verdict"] == "PASS"


def test_T85_environment_fact_check_stable_keys():
    """T85 · env fact-check 提供稳定键位（下游报告 grep 依赖）。"""

    from tools.synth_shadow_read_probe import _environment_fact_check

    facts = _environment_fact_check()
    # 必须包含核心 3 项事实（不管值是啥）
    assert "data/canvas exists" in facts
    assert "data/app.db exists" in facts
    assert "data/shadow_diff/canvas exists" in facts


# ---------------------------------------------------------------------------
# T86 · full CLI end-to-end at scale=10
# ---------------------------------------------------------------------------


def test_T86_cli_end_to_end_scale_10(tmp_path):
    """T86 · CLI 全流程：scale=10 · 输出 JSON schema 稳定。"""

    output = tmp_path / "cli_probe.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.synth_shadow_read_probe",
            "--scale=10",
            f"--output={output}",
            "--seed=1337",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"CLI exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    # 稳定 schema 键位
    for key in (
        "schema",
        "synthetic_load_declaration",
        "generated_at_utc",
        "scale",
        "environment",
        "scenarios",
        "scenario_verdicts",
        "observations",
        "readiness_verdict",
    ):
        assert key in payload, f"missing schema key: {key}"
    assert payload["schema"] == "synth-probe/v1"
    assert payload["scale"] == 10
    assert set(payload["scenarios"].keys()) == {
        "A_hit_rate",
        "B_diff_rate",
        "C_write_latency",
        "D_tx_fail_safe",
    }
    # 显式 synthetic-load 声明
    assert "synthetic" in payload["synthetic_load_declaration"].lower()
    assert "NOT a real production observation" in payload["synthetic_load_declaration"]


# ---------------------------------------------------------------------------
# T87 · asymmetric normalizer observation
# ---------------------------------------------------------------------------


def test_T87_asymmetric_normalizer_observation_registered(small_probe_report):
    """T87 · shadow_read canvas normalizer 非对称观察项。

    历史（PR-10 之前）：canvas 域的 `_normalize_json_canvas` 只返回单 canvas，
    而 DB snapshot 是整表 → 每次 load_canvas 都会把 DB 里其它 canvas 记录到
    `missing_in_json`（O(N) 假 missing 噪声）· CB-P5-08b 观察项。

    数据 PR-15 内嵌承接（CB-P5-08b closed）：`app/shadow_read/runner.py` 在
    canvas 域下会先把 DB snapshot 收敛到 JSON snapshot 覆盖的 legacy_id 上
    （`app/shadow_read/canvas_normalizer.py::scope_db_snapshot_to_json`），
    因此探针不再观察到 `records_with_missing_in_json_nonempty > 0`。

    修复后契约：探针**不再登记**非对称观察项（本用例反过来护栏 · CB-P5-08b
    观察项闭合的抗回归）。
    """

    titles = [o["title"] for o in small_probe_report["observations"]]
    # CB-P5-08b 修复后：观察项不再触发。若未来出现回归（比如意外恢复整表
    # 扫描），本断言会失败并提示回归。
    assert not any("非对称" in t for t in titles), (
        "CB-P5-08b 已闭合（数据 PR-15）· 探针不应再登记非对称观察项，"
        f"实际观察项 titles={titles}"
    )
    # 其它现存观察项（如 created_at/updated_at 类型漂移）仍需保持 CB-P5-08 归口。
    for o in small_probe_report["observations"]:
        assert o.get("cb_candidate") == "CB-P5-08"


# ---------------------------------------------------------------------------
# T88 · full CLI at scale=50 (slow · pytest -m slow)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_T88_cli_scale_50_slow(tmp_path):
    """T88 · CLI scale=50（`-m slow` 才跑；~15-20s）。"""

    output = tmp_path / "cli_probe_50.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.synth_shadow_read_probe",
            "--scale=50",
            f"--output={output}",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["scale"] == 50
    assert payload["scenarios"]["A_hit_rate"]["db_inserted"] == 50


# ---------------------------------------------------------------------------
# T89 · scale=500（重 · skip 归档）
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "T89 · scale=500 是 Wave 3-K 就绪度评估的重负载采样，单次 90s+，"
        "avoid CI; 手动跑 `python -m tools.synth_shadow_read_probe --scale=500 "
        "--output=probe-500.json` 或去掉 skip 装饰器复跑。此处只做归档"
        "证明测试路径存在。"
    )
)
def test_T89_cli_scale_500_archived(tmp_path):  # pragma: no cover
    output = tmp_path / "cli_probe_500.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.synth_shadow_read_probe",
            "--scale=500",
            f"--output={output}",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert result.returncode == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["scale"] == 500
