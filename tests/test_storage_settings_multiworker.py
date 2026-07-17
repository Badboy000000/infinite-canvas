"""文件对象与 MinIO 治理 PR-0 验收测试。

覆盖两个硬验收项：

1. 多进程一致性烟测：`apply_storage_settings` 不再依赖 module 级 global
   之后，两个独立解释器进程（模拟 `uvicorn --workers 2`）在 A 进程发起
   `PATCH /api/storage-settings` 之后，B 进程通过 `GET /api/storage-settings`
   与 `storage_settings_snapshot()` 都能读到最新路径。历史行为下 B 进程
   会沿用启动时值，本用例即为回归保护。

2. `/output` 双根 fallback 埋点：`output_file_from_url` 命中 legacy
   `/output/` 根时应发出结构化日志 `output_double_root_hit`，字段仅含
   `root_alias` 与 `rel_path`，不含 URL query / 绝对路径 / 用户身份。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 验收 1：多 worker 一致性
# ---------------------------------------------------------------------------


def _run_child(tmp_data_dir: Path, script: str) -> str:
    """在独立子进程中导入 `main` 并跑一段脚本，返回 stdout。

    通过 env `IC_TEST_DATA_DIR` 让子进程用临时 data 目录，避免污染仓库
    根下的 `data/storage_settings.json`。
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["IC_TEST_DATA_DIR"] = str(tmp_data_dir)
    # 让子进程在 REPO_ROOT 下 import main
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"child exited with {proc.returncode}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc.stdout


def test_multiworker_storage_settings_consistency(tmp_path: Path) -> None:
    """模拟 uvicorn --workers 2：A 进程 PATCH，B 进程读到新值。

    直接调 `save_storage_settings()` 与 `load_storage_settings()`（其为
    `/api/storage-settings` GET/PATCH 的实现底座），跨进程验证读时求值
    语义。历史 `apply_storage_settings` 改写 module global 的实现在
    B 进程会读回启动默认值，本用例会失败。
    """
    tmp_data = tmp_path / "data"
    tmp_data.mkdir(parents=True, exist_ok=True)

    # 子进程 A：把 `local` 指到 tmp_path/patched_local
    patched_local = str(tmp_path / "patched_local").replace("\\", "/")
    patched_upload = str(tmp_path / "patched_upload").replace("\\", "/")
    patched_generated = str(tmp_path / "patched_generated").replace("\\", "/")
    settings_file = tmp_data / "storage_settings.json"

    # A：直接落 storage_settings.json（等价于 PATCH /api/storage-settings 的持久化侧）
    settings_file.write_text(
        json.dumps(
            {
                "upload": patched_upload,
                "generated": patched_generated,
                "local": patched_local,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    child_script = (
        "import os, json, sys, importlib\n"
        # 把子进程的 STORAGE_SETTINGS_FILE 重定向到临时 data
        f"os.environ.setdefault('PYTHONPATH', r'{REPO_ROOT}')\n"
        "import main\n"
        # 覆盖 STORAGE_SETTINGS_FILE 指向临时目录（模拟 A 进程刚 PATCH 完的文件系统状态）
        f"main.STORAGE_SETTINGS_FILE = r'{settings_file}'\n"
        "snap = main.storage_settings_snapshot()\n"
        "print(json.dumps({'upload': snap.upload, 'generated': snap.generated, 'local': snap.local, "
        "'load': main.load_storage_settings()['dirs']}, ensure_ascii=False))\n"
    )

    stdout = _run_child(tmp_data, child_script)
    payload = json.loads(stdout.strip().splitlines()[-1])

    # 关键断言：子进程读到的是 tmp_path 下的路径，而不是 main.py 启动默认的 assets/*
    assert os.path.abspath(payload["upload"]) == os.path.abspath(patched_upload), payload
    assert os.path.abspath(payload["generated"]) == os.path.abspath(patched_generated), payload
    assert os.path.abspath(payload["local"]) == os.path.abspath(patched_local), payload
    # load_storage_settings() 契约 shape 冻结
    assert set(payload["load"].keys()) == {"upload", "generated", "local"}

    # 现在再模拟"B 进程随后读"：换一份新的 settings.json（等价于 PATCH 二次），
    # 子进程 B 从磁盘读到的应该是二次 PATCH 后的值——回归保护"module global 缓存"bug。
    second_local = str(tmp_path / "second_local").replace("\\", "/")
    settings_file.write_text(
        json.dumps(
            {
                "upload": patched_upload,
                "generated": patched_generated,
                "local": second_local,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    child_script_b = (
        "import os, json, sys, importlib\n"
        f"os.environ.setdefault('PYTHONPATH', r'{REPO_ROOT}')\n"
        "import main\n"
        f"main.STORAGE_SETTINGS_FILE = r'{settings_file}'\n"
        "print(main.current_local_dir())\n"
    )
    stdout_b = _run_child(tmp_data, child_script_b).strip().splitlines()[-1]
    assert os.path.abspath(stdout_b) == os.path.abspath(second_local), stdout_b


def test_apply_storage_settings_does_not_mutate_globals() -> None:
    """`apply_storage_settings` 不再改写 module 级 global（PR-0 硬约束）。

    调用前后 `OUTPUT_INPUT_DIR / OUTPUT_OUTPUT_DIR / LOCAL_UPLOAD_DIR`
    这三个 module 属性（若仍保留为默认锚点常量）必须**恒等**。
    """
    import main

    before = (
        getattr(main, "OUTPUT_INPUT_DIR", None),
        getattr(main, "OUTPUT_OUTPUT_DIR", None),
        getattr(main, "LOCAL_UPLOAD_DIR", None),
    )
    main.apply_storage_settings({"upload": "X", "generated": "Y", "local": "Z"})
    after = (
        getattr(main, "OUTPUT_INPUT_DIR", None),
        getattr(main, "OUTPUT_OUTPUT_DIR", None),
        getattr(main, "LOCAL_UPLOAD_DIR", None),
    )
    assert before == after, (
        "apply_storage_settings 触碰了 module 级 global，多 worker 语义又漂了；"
        f"before={before} after={after}"
    )


# ---------------------------------------------------------------------------
# 验收 2：`/output` 双根 fallback 埋点
# ---------------------------------------------------------------------------


def test_output_double_root_hit_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """命中 `/output/` legacy 根时应发出结构化日志 `output_double_root_hit`。

    构造：往 `OUTPUT_DIR`（`<repo>/output/`）下写一个真实文件，然后
    以 `/output/<name>` 形式调 `output_file_from_url`，断言日志里包含
    该事件且脱敏（不含 URL query、绝对路径、身份信息）。
    """
    import main

    caplog.set_level(logging.INFO, logger="infinite_canvas.storage")

    fname = "pr0_probe_double_root.bin"
    probe_path = Path(main.OUTPUT_DIR) / fname
    probe_path.parent.mkdir(parents=True, exist_ok=True)
    probe_path.write_bytes(b"pr0-probe")
    try:
        # 走 legacy `/output/*` 根路径且带 query，命中 fallback 分支
        hit = main.output_file_from_url(f"/output/{fname}?ts=12345")
        assert hit is not None, "fallback 未命中，无法验证埋点"

        records = [
            r for r in caplog.records
            if r.name == "infinite_canvas.storage"
            and r.getMessage() == "output_double_root_hit"
        ]
        assert records, f"未见 output_double_root_hit 日志；已抓到：{caplog.records}"

        rec = records[-1]
        # 脱敏断言：字段仅含 event / root_alias / rel_path
        assert getattr(rec, "event", None) == "output_double_root_hit"
        assert getattr(rec, "root_alias", None) == "legacy_output"
        rel_path = getattr(rec, "rel_path", None)
        assert rel_path == fname, rel_path
        # rel_path 不含 URL query（`?ts=12345`），不含绝对路径
        assert "?" not in rel_path
        assert not os.path.isabs(rel_path)
    finally:
        try:
            probe_path.unlink()
        except OSError:
            pass


def test_output_file_from_url_assets_root_does_not_log_double_hit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`/assets/*` 命中不应触发 double-root 埋点（否则一周观察数据被污染）。"""
    import main

    caplog.set_level(logging.INFO, logger="infinite_canvas.storage")

    # 命中或未命中都行，关键是不能发出 double_root_hit
    _ = main.output_file_from_url("/assets/output/some_nonexistent_probe.png")
    records = [
        r for r in caplog.records
        if r.getMessage() == "output_double_root_hit"
    ]
    assert not records, records
