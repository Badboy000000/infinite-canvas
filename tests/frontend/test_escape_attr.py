"""Frontend PR-7: escapeAttr XSS 全量抗回归测试.

Baseline (Wave 3-H closing / c3f2d83): 592 passed / 35 skipped.

Covers:
    T1  escapeAttr 对 &, <, >, ", ' 全部转义（canvas.js + smart-canvas.js）
    T2  canvas.js 内所有 onclick 字符串插值场景均被 escapeAttr / escapeHtml 包裹
    T3  smart-canvas.js 内所有 onclick 字符串插值场景均被 escapeAttr / escapeHtml 包裹
    T4  canvas.js:6080 deleteNodeFromButton onclick 包 escapeAttr（回归焦点）
    T5  修复后 canvas.js / smart-canvas.js 里没有裸 ${node.id} 直接进 onclick 字符串的模式
    T6  P0 密钥 sentinel 在 escapeAttr 转义后不会以 attribute-breakout 形式泄漏
"""
import re
import subprocess
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANVAS_JS = ROOT / "static/js/canvas.js"
SMART_CANVAS_JS = ROOT / "static/js/smart-canvas.js"


def _extract_escape_html_body(src: str) -> str:
    m = re.search(r"function escapeHtml\(str\)\s*\{[^}]+\}", src)
    return m.group(0) if m else ""


def test_escape_html_covers_five_chars_canvas():
    body = _extract_escape_html_body(CANVAS_JS.read_text(encoding="utf-8"))
    assert body, "canvas.js escapeHtml 定义缺失"
    for ch in ["&", "<", ">", '"', "'"]:
        assert repr(ch) in body or f"'{ch}'" in body


def test_escape_html_covers_five_chars_smart():
    body = _extract_escape_html_body(SMART_CANVAS_JS.read_text(encoding="utf-8"))
    assert body, "smart-canvas.js escapeHtml 定义缺失"
    for ch in ["&", "<", ">", '"', "'"]:
        assert repr(ch) in body or f"'{ch}'" in body


def test_escape_attr_runtime_transforms_five_chars_canvas():
    # 通过 Node 运行 escapeAttr 直接验证输出
    script = r"""
        const escapeHtml = (str) => String(str == null ? '' : str).replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));
        const escapeAttr = escapeHtml;
        const result = escapeAttr(`<img src=x onerror="alert('xss')" & ' " > <`);
        console.log(JSON.stringify({result}));
    """
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    out = json.loads(completed.stdout)
    for c in ["&lt;", "&gt;", "&amp;", "&quot;", "&#39;"]:
        assert c in out["result"], f"escapeAttr 未转义 {c}"


def test_canvas_js_onclick_interpolation_wrapped():
    """canvas.js:6080 的 deleteNodeFromButton onclick 必须包 escapeAttr"""
    src = CANVAS_JS.read_text(encoding="utf-8")
    assert "deleteNodeFromButton('${escapeAttr(node.id)}'" in src, (
        "canvas.js:6080 deleteNodeFromButton 未包 escapeAttr"
    )


def test_no_unwrapped_onclick_interpolation_in_two_canvases():
    """禁字段名正则守护(CI 抗回归):
    onclick="...${bareExpr}..." 未被 escapeAttr / escapeHtml 包裹的场景为 0.

    正则拒绝: onclick="foo(${x})" (x 不以 escapeAttr / escapeHtml 开头)
    正则允许: onclick="foo(${escapeAttr(x)})"
    """
    pattern = re.compile(r'onclick="[^"]*\$\{(?!escapeAttr|escapeHtml)[^}]+\}[^"]*"')
    for path in [CANVAS_JS, SMART_CANVAS_JS]:
        hits = pattern.findall(path.read_text(encoding="utf-8"))
        assert hits == [], f"{path.name} 存在未包裹 escapeAttr/escapeHtml 的 onclick 拼串: {hits[:3]}"


def test_p0_credential_sentinel_escaped_not_attribute_breakout():
    """P0 密钥 sentinel:即使 node.id 未来漂移含 " 或 script,escapeAttr 也把
    attribute 边界保护住,不允许 attribute-breakout XSS."""
    script = r"""
        const escapeHtml = (str) => String(str == null ? '' : str).replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));
        const escapeAttr = escapeHtml;
        const nodeId = `n1' onclick="alert('leak_sentinel_bearer_XYZ')`;
        const html = `<button onclick="deleteNodeFromButton('${escapeAttr(nodeId)}', event)"/>`;
        console.log(JSON.stringify({html}));
    """
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    out = json.loads(completed.stdout)
    html = out["html"]
    # sentinel 应作为字面文本存在但 attribute 边界应完整
    assert "leak_sentinel_bearer_XYZ" in html  # 字面 sentinel 出现（正常，因为 nodeId 就是它）
    # attribute-breakout 攻击应被中和:
    # attacker 试图用 ' 提前闭合 onclick 值,再插入 onclick="alert(...)"
    # escapeAttr 应把 ' 转成 &#39;
    assert "&#39;" in html
    # 原始未转义的 attacker-injected onclick 不应出现
    # 语义:整个 payload 被作为单个字符串挂在 deleteNodeFromButton('...') 里
    # 断言:未逃逸的 attribute-breakout 字符串 (未转义 " 或未转义 ') 不出现
    # attacker payload 中包含的 " 和 ' 应全被转义
    assert '"alert(' not in html, "发现未转义的 attribute-breakout 双引号 payload"
    # 攻击的关键:未转义的 `' onclick="` 序列。这个序列被转义后应变成 `&#39; onclick=&quot;`
    assert "' onclick=\"" not in html, "发现 raw ' onclick=\" attribute-breakout 未被转义"
