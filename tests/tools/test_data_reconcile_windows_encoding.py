"""CB-P5-04 · tools/data_reconcile 在 Windows GBK 环境下的 UTF-8 输出稳定性(数据 PR-16 · Wave 3-L 主线 C)。

覆盖点(T116-T117 共 2 项):

- T116 CB-P5-04:模块加载时 Windows 分支 sys.stdout.reconfigure 已定义
- T117 CB-P5-04:CLI subprocess 独立执行 · 打印含 CJK 的 canvas 名字不抛
  `UnicodeEncodeError`(regression pin)

**注意**:本测试跑在任何平台上,但只有 Windows 平台真实触发 reconfigure 路径;
其它平台走 platform 分支保护 · reconfigure 不执行。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# T116 · CB-P5-04 · Windows 分支 reconfigure 已声明
# ---------------------------------------------------------------------------


def test_t116_cbp504_windows_stdout_reconfigure_declared() -> None:
    """`tools/data_reconcile.py` 顶部 Windows 分支 reconfigure 逻辑存在。

    检查代码文本 · 不真实调用 reconfigure(测试环境已有自己的 stdout 配置)。
    """
    source = (REPO_ROOT / "tools" / "data_reconcile.py").read_text(encoding="utf-8")
    assert 'sys.platform == "win32"' in source, "Windows 平台判定缺失"
    assert 'sys.stdout.reconfigure(encoding="utf-8"' in source, "stdout UTF-8 重配缺失"
    assert 'sys.stderr.reconfigure(encoding="utf-8"' in source, "stderr UTF-8 重配缺失"
    assert "CB-P5-04" in source, "CB 追溯注释缺失"


# ---------------------------------------------------------------------------
# T117 · CB-P5-04 · CLI subprocess UTF-8 稳定输出
# ---------------------------------------------------------------------------


def test_t117_cbp504_cli_utf8_output_stable(tmp_path: Path) -> None:
    """subprocess 独立执行 `python -m tools.data_reconcile canvas` 不抛
    UnicodeEncodeError · 输出 JSON 可解析为 UTF-8。"""

    # 构造一个含 CJK 字符的 canvas JSON 让对账扫描
    src_dir = tmp_path / "canvas_src"
    src_dir.mkdir()
    (src_dir / "测试画布.json").write_text(
        '{"id": "test-cjk-name", "title": "测试画布 · 中文标题"}',
        encoding="utf-8",
    )

    # 独立跑 CLI · 强制 encoding=utf-8 · 观察 exit + 输出
    result = subprocess.run(
        [sys.executable, "-m", "tools.data_reconcile", "canvas", "--source-dir", str(src_dir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
        timeout=30,
    )
    assert result.returncode == 0, f"CLI 非 0 退出 · stderr={result.stderr!r}"
    # 输出应为可解析 JSON(exit=0 契约)
    import json
    payload = json.loads(result.stdout)
    assert payload["domain"] == "canvas"
    # stderr 不含 UnicodeEncodeError trace
    assert "UnicodeEncodeError" not in result.stderr
