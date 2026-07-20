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


def _extract_function_source(src: str, name: str) -> str:
    """从 JS 源码中提取 `function <name>(...) {...}` 的完整定义。

    简单大括号平衡计数(逃逸串/注释未考虑,canvas.js 实现足够简单)。
    """
    m = re.search(rf"function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{", src)
    if not m:
        return ""
    start = m.start()
    depth = 0
    i = m.end() - 1  # 指向左花括号
    while i < len(src):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start:i+1]
        i += 1
    return ""


def _extract_escape_html_body(src: str) -> str:
    """兼容 T1/T2 的旧 signature,委托到通用提取器。"""
    return _extract_function_source(src, "escapeHtml")


def _run_node_with_source(src_snippet: str, epilogue: str) -> dict:
    """把一段 JS(通常是从 canvas.js 提取的函数定义)+ 一段调用/断言尾巴
    一起用 node -e 跑,回读 JSON 输出。"""
    script = src_snippet + "\n" + epilogue
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return json.loads(completed.stdout)


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
    """Wave 3-I 承接补丁 P0-1(前端 TRA):从内联复制升级为**真正执行 canvas.js
    的 escapeHtml / escapeAttr 定义体**。

    P0 反审背景:原测试内联写一份 `const escapeHtml = ...`,断言其行为
    符合契约 —— canvas.js 里的 escapeAttr 即使被改坏(比如漏 `'` 映射)
    测试仍然会 PASS(因为它跑的是内联副本,不是真实实现)。
    """
    src = CANVAS_JS.read_text(encoding="utf-8")
    escape_html_fn = _extract_function_source(src, "escapeHtml")
    escape_attr_fn = _extract_function_source(src, "escapeAttr")
    assert escape_html_fn, "canvas.js escapeHtml 定义体未提取到"
    assert escape_attr_fn, "canvas.js escapeAttr 定义体未提取到"

    # 直接把两个函数体 evaluate 到 node global scope,再调 escapeAttr
    out = _run_node_with_source(
        escape_html_fn + "\n" + escape_attr_fn,
        r"""
        const result = escapeAttr(`<img src=x onerror="alert('xss')" & ' " > <`);
        console.log(JSON.stringify({result}));
        """,
    )
    for c in ["&lt;", "&gt;", "&amp;", "&quot;", "&#39;"]:
        assert c in out["result"], f"canvas.js escapeAttr 未转义 {c}"


def test_escape_attr_runtime_transforms_five_chars_smart():
    """T3b(承接补丁新增):smart-canvas.js 只有 escapeHtml(没有独立 escapeAttr)。
    验证 escapeHtml 5 字符全转义运行时。"""
    src = SMART_CANVAS_JS.read_text(encoding="utf-8")
    escape_html_fn = _extract_function_source(src, "escapeHtml")
    assert escape_html_fn, "smart-canvas.js escapeHtml 定义体未提取到"
    out = _run_node_with_source(
        escape_html_fn,
        r"""
        const result = escapeHtml(`<img src=x onerror="alert('xss')" & ' " > <`);
        console.log(JSON.stringify({result}));
        """,
    )
    for c in ["&lt;", "&gt;", "&amp;", "&quot;", "&#39;"]:
        assert c in out["result"], f"smart-canvas.js escapeHtml 未转义 {c}"


def test_canvas_js_onclick_interpolation_wrapped():
    """canvas.js:6080 的 deleteNodeFromButton onclick 必须包 escapeAttr"""
    src = CANVAS_JS.read_text(encoding="utf-8")
    assert "deleteNodeFromButton('${escapeAttr(node.id)}'" in src, (
        "canvas.js:6080 deleteNodeFromButton 未包 escapeAttr"
    )


def test_no_unwrapped_high_risk_attribute_interpolation_in_two_canvases():
    """Wave 3-I 承接补丁 P1-1(前端 TRA):正则从只覆盖 `onclick=` 扩到全部
    **高风险 sink** attribute:
      - `on\\w+` 所有事件属性(onclick / onload / onerror / onmouseover / …)
      - `href` / `src` / `action` — URL / navigation sink
      - `formaction` — 表单提交 URL sink

    豁免 attribute(仅显示,非 sink):`title` / `value` / `placeholder` /
    `alt` / `data-i18n-title` / `aria-*` —— 这些即使含 `${tr('key')}` 也不构成
    XSS,不视为回归。承接补丁把范围收敛到"确实是 handler / URL sink"的属性,
    避免误报 i18n / 显示串。

    允许的包裹函数:`escapeAttr` / `escapeHtml` / `CSS.escape`(CSS/URL 场景)
    + 允许变量名 `safe`/`escaped`(通过命名约定标注上游已转义;若不放心可
    独立小 PR 收敛)。

    此测试是回归锚点:未来任何 PR 新增高风险 attribute 拼串场景必须显式加
    escape 包裹或加入允许清单;不允许自由漂移。
    """
    # 关键 sink attributes(可以执行 JS 或改变导航目标)
    sink_attrs = r'(on\w+|href|src|action|formaction)'
    # 允许清单:以下 identifier 开头视为已转义 / 已白名单
    allowlist = r'(?:escapeAttr|escapeHtml|CSS\.escape|safe\b|escaped\b|urlSafe\b)'
    pattern = re.compile(
        rf'\b{sink_attrs}="[^"]*\$\{{(?!{allowlist})[^}}]+\}}[^"]*"'
    )
    for path in [CANVAS_JS, SMART_CANVAS_JS]:
        real_hits = [m.group(0) for m in pattern.finditer(path.read_text(encoding="utf-8"))]
        assert real_hits == [], (
            f"{path.name} 存在未包裹 escapeAttr/escapeHtml/CSS.escape 的**高风险 sink** "
            f"attribute 拼串(共 {len(real_hits)} 处,前 3 处):\n  " +
            "\n  ".join(real_hits[:3]) +
            "\n\n允许清单:escapeAttr / escapeHtml / CSS.escape / 变量名 safe / escaped / urlSafe"
        )


def test_no_unwrapped_onclick_interpolation_in_two_canvases():
    """兼容旧断言(承接前的 grep 抗回归)。保留以确保 onclick 特化不被回归。"""
    pattern = re.compile(r'onclick="[^"]*\$\{(?!escapeAttr|escapeHtml)[^}]+\}[^"]*"')
    for path in [CANVAS_JS, SMART_CANVAS_JS]:
        hits = pattern.findall(path.read_text(encoding="utf-8"))
        assert hits == [], f"{path.name} 存在未包裹 escapeAttr/escapeHtml 的 onclick 拼串: {hits[:3]}"


def test_p0_credential_sentinel_escaped_not_attribute_breakout():
    """Wave 3-I 承接补丁 P0-2(前端 TRA):**参数化 6 sentinel + 真正跑 canvas.js
    的 escapeAttr** + attribute-breakout 抗回归。

    P0 反审背景:原测试内联复制 escapeHtml 定义,断言其行为 —— 与 canvas.js
    实际实现解耦。承接补丁改造为:
      (a) 提取 canvas.js 中的 escapeHtml/escapeAttr 定义体 evaluate 到 node,
      (b) 参数化 6 种 P0 密钥 sentinel(api_key/access_token/secret/Bearer/sk-/AKI),
      (c) 每个 sentinel 尝试 attribute-breakout(用 ' 提前闭合 attribute)
      (d) 断言 sentinel 字面存在(证明进入了 render 路径)+ attribute-breakout 序列被中和
    """
    src = CANVAS_JS.read_text(encoding="utf-8")
    escape_html_fn = _extract_function_source(src, "escapeHtml")
    escape_attr_fn = _extract_function_source(src, "escapeAttr")
    assert escape_html_fn and escape_attr_fn

    sentinels = [
        ("api_key", "api_key=SECRET_ABC"),
        ("access_token", "access_token_XYZ"),
        ("secret", "secret_material_QQQ"),
        ("Bearer", "Bearer eyJhbGciOiJIUzI1NiJ9"),
        ("sk-", "sk-abcdef0123456789"),
        ("AKIA", "AKIAIOSFODNN7EXAMPLE"),
    ]
    for tag, payload in sentinels:
        # 构造 attribute-breakout attack payload:攻击者在 node.id 里塞 `' onclick="alert(...)`
        node_id_attack = f"n1' onclick=\"alert('leak_{payload}')"
        escaped_epilogue = (
            "const nodeId = " + json.dumps(node_id_attack) + ";"
            "const html = `<button onclick=\"deleteNodeFromButton('${escapeAttr(nodeId)}', event)\"/>`;"
            "console.log(JSON.stringify({html}));"
        )
        out = _run_node_with_source(escape_html_fn + "\n" + escape_attr_fn, escaped_epilogue)
        html = out["html"]
        # (a) sentinel 字面存在,证明确实进入了 render 路径
        assert payload in html, f"[sentinel {tag}] {payload} 未出现在渲染结果,render 路径断裂"
        # (b) attribute-breakout 序列 `' onclick="` 应被完全中和(`'` 转成 `&#39;` + `"` 转成 `&quot;`)
        assert "' onclick=\"" not in html, (
            "[sentinel " + tag + "] 发现 raw `' onclick=\"` 未转义,"
            "attribute-breakout 攻击面存在"
        )
        # (c) `"` 边界被保护
        # HTML 是 <button onclick="deleteNodeFromButton('...', event)"/> —— 期望的 `"` 只出现在 attribute 定界(2 个)
        # 攻击者插入的额外 `"` 应被转义为 &quot;
        dq_count = html.count('"')
        assert dq_count == 2, (
            "[sentinel " + tag + "] `\"` 计数异常"
            + "(期望 2 个 attribute 定界):" + str(dq_count)
        )
        # (d) 关键:`&#39;` 应存在(证明攻击 payload 里的 `'` 被转义了)
        assert "&#39;" in html, "[sentinel " + tag + "] 未在输出中找到 `&#39;`,`'` 转义未生效"

