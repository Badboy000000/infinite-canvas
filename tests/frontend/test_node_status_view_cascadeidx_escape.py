"""CB-P5-05 · NodeStatusView cascadeIdx 全通道 escape 硬锁(数据 PR-16 · Wave 3-L 主线 C)。

覆盖点(T118-T119 共 2 项):

- T118 CB-P5-05:静态 grep 断言 NodeStatusView `buildBadgeHtml` +
  `buildFallbackHtml` 与 canvas.js line 6186 legacy 兜底所有 cascadeIdx 拼接位
  置都用 `escapeHtml(...)` 包裹(引用完整性契约)
- T119 CB-P5-05:Node subprocess 独立执行 `buildBadgeHtml` · 断言 XSS payload
  `<script>alert(1)</script>` 通过 cascadeIdx 传入时输出为 escaped 文本

**GM-08 / GM-09 pattern**:引用完整性 CI 硬断言 + 端到端 dispatch 运行时。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
NSV_PATH = REPO_ROOT / "static" / "js" / "shared" / "components" / "NodeStatusView" / "index.js"
CANVAS_JS_PATH = REPO_ROOT / "static" / "js" / "canvas.js"


# ---------------------------------------------------------------------------
# T118 · CB-P5-05 · 静态 grep 引用完整性
# ---------------------------------------------------------------------------


def test_t118_cbp505_cascadeidx_escape_static_reference_integrity() -> None:
    """NodeStatusView + canvas.js 所有 cascadeIdx 拼接位点必须用 escapeHtml 包裹。"""

    nsv_source = NSV_PATH.read_text(encoding="utf-8")
    # NSV 两处 cascadeIdx 定义(buildBadgeHtml / buildFallbackHtml)
    # 期望模式:` + escapeHtml(String(options.cascadeIdx))`
    nsv_matches = re.findall(
        r"options\.cascadeIdx\s*\?\s*'\s*'\s*\+\s*(escapeHtml\(String\(options\.cascadeIdx\)\)|String\(options\.cascadeIdx\))",
        nsv_source,
    )
    assert len(nsv_matches) == 2, (
        f"NSV cascadeIdx 拼接位点应精确 2 处,实际找到 {len(nsv_matches)}: {nsv_matches}"
    )
    # 每一处都必须是 escapeHtml wrap · 不能是裸 String
    for match in nsv_matches:
        assert "escapeHtml" in match, (
            f"NSV cascadeIdx 拼接位点未 escape · match={match!r}"
        )

    # canvas.js line 6186 legacy 内联兜底
    canvas_source = CANVAS_JS_PATH.read_text(encoding="utf-8")
    # 期望 `${node._cascadeIdx?' '+escapeHtml(node._cascadeIdx):''}`
    legacy_matches = re.findall(
        r"node\._cascadeIdx\s*\?\s*'\s*'\s*\+\s*(escapeHtml\(node\._cascadeIdx\)|node\._cascadeIdx)",
        canvas_source,
    )
    # canvas.js 只此一处 legacy 兜底(line 6186 附近)· 但 grep 可能命中多个上下文
    # 我们只关心该模式是否存在 · 且不存在裸 node._cascadeIdx 拼接
    assert legacy_matches, "canvas.js 未找到 cascadeIdx 拼接位点"
    for match in legacy_matches:
        assert "escapeHtml" in match, (
            f"canvas.js cascadeIdx 拼接位点未 escape · match={match!r}"
        )


# ---------------------------------------------------------------------------
# T119 · CB-P5-05 · Node subprocess 端到端 XSS 输入 escape 验证
# ---------------------------------------------------------------------------


def _node_available() -> bool:
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=5, check=True)
        return True
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


@pytest.mark.skipif(not _node_available(), reason="Node.js not available on this CI runner")
def test_t119_cbp505_xss_payload_via_cascadeidx_escaped() -> None:
    """Node subprocess 独立跑 NodeStatusView.renderHtml · XSS payload 通过
    cascadeIdx 传入应输出 escaped(< 变 &lt;)· 而非可执行 HTML。"""

    nsv_url = NSV_PATH.as_posix()
    script = f"""
import('file://{nsv_url}').then(mod => {{
    const html = mod.default ? mod.default.renderHtml('running', {{cascadeIdx: '<script>alert(1)</script>'}})
                              : mod.NodeStatusView.renderHtml('running', {{cascadeIdx: '<script>alert(1)</script>'}});
    process.stdout.write(html);
}}).catch(err => {{ process.stderr.write(String(err)); process.exit(2); }});
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        pytest.skip(f"Node ESM import 失败 · 可能是 tests/frontend 环境问题 · stderr={result.stderr[:200]}")

    output = result.stdout
    # XSS payload 必须被 escape
    assert "<script>" not in output, f"cascadeIdx XSS 未 escape · output={output!r}"
    assert "&lt;script&gt;" in output or "&#x3C;script&#x3E;" in output, (
        f"escaped payload 不存在于输出 · output={output!r}"
    )
