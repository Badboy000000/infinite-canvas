"""Frontend PR-11: PromptTemplateDrawer seam tests (Wave 3-N.5 Batch 3 主线 B).

`static/js/shared/prompt/PromptTemplateDrawer/` 抽出 canvas.js 中的抽屉入口。
Pattern reuse: PR-4 MediaEditor（`test_media_editor_seam.py`）。

seam 三文件以 classic `<script src>` 方式加载（非 ES module；`window.*` IIFE），
测试通过 node vm 模拟浏览器 `window` + 顺序 evaluate 三文件，然后跑断言脚本。
"""
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

SEAM_DIR = ROOT / "static/js/shared/prompt/PromptTemplateDrawer"
REGISTRY = SEAM_DIR / "templateRegistry.js"
EDITOR = SEAM_DIR / "promptEditor.js"
INDEX = SEAM_DIR / "index.js"
CANVAS_JS = ROOT / "static/js/canvas.js"
CANVAS_HTML = ROOT / "static/canvas.html"
COMPAT = ROOT / "docs/frontend-freeze/compat-contract.md"


def run_node_with_seam(assertion_script: str) -> dict:
    """Load 3 seam scripts under a fake `window`, then run assertion script.

    Returns parsed JSON printed to stdout by the assertion script.
    """
    node_script = f"""
    const fs = require('fs');
    const vm = require('vm');
    const path = require('path');
    const paths = {json.dumps([str(REGISTRY), str(EDITOR), str(INDEX)])};
    const window = {{}};
    const sandbox = {{ window, globalThis: window, console, Promise, Array, Object, Boolean, Math, Date, JSON, Error }};
    vm.createContext(sandbox);
    for (const p of paths) {{
      const code = fs.readFileSync(p, 'utf-8');
      vm.runInContext(code, sandbox, {{ filename: p }});
    }}
    const assertion = {json.dumps(assertion_script)};
    // assertion script has access to `window`
    (async () => {{
      const result = await (new Function('window', 'return (async () => {{' + assertion + '}})()'))(window);
      process.stdout.write(JSON.stringify(result));
    }})().catch(err => {{
      process.stderr.write(String(err && err.stack || err));
      process.exit(1);
    }});
    """
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return json.loads(completed.stdout)


# ---------------------------------------------------------------------------
# T290: seam 三文件存在且可加载
# ---------------------------------------------------------------------------
def test_t290_three_seam_files_exist_and_load():
    for p in (REGISTRY, EDITOR, INDEX):
        assert p.exists(), f"PR-11 seam file missing: {p}"
        assert p.stat().st_size > 0, f"PR-11 seam file empty: {p}"
    result = run_node_with_seam(
        """
        return {
          hasDrawer: typeof window.PromptTemplateDrawer === 'object',
          hasReady: typeof window.PromptTemplateDrawerReady?.then === 'function',
          hasRegistry: typeof window.__PromptTemplateDrawerRegistry === 'object',
          hasEditor: typeof window.__PromptTemplateDrawerEditor === 'object',
        };
        """
    )
    assert result == {
        "hasDrawer": True,
        "hasReady": True,
        "hasRegistry": True,
        "hasEditor": True,
    }


# ---------------------------------------------------------------------------
# T291: register / open / close / render 4 个 API 可调用
# ---------------------------------------------------------------------------
def test_t291_four_apis_callable():
    result = run_node_with_seam(
        """
        const calls = [];
        window.PromptTemplateDrawer.register('classic', {
          open: (nodeId, opts) => { calls.push({fn:'open', nodeId, opts}); },
          close: () => { calls.push({fn:'close'}); },
          renderCallback: () => { calls.push({fn:'render'}); },
          loadTemplates: () => { calls.push({fn:'load'}); return []; },
          saveTemplate: (payload) => { calls.push({fn:'save', payload}); },
        });
        const openResult = await window.PromptTemplateDrawer.open({ canvasKind:'classic', nodeId:'n1' });
        window.PromptTemplateDrawer.render('classic');
        window.PromptTemplateDrawer.close('classic');
        return {
          types: {
            register: typeof window.PromptTemplateDrawer.register,
            open: typeof window.PromptTemplateDrawer.open,
            close: typeof window.PromptTemplateDrawer.close,
            render: typeof window.PromptTemplateDrawer.render,
          },
          openResult,
          activeFinal: window.PromptTemplateDrawer.isOpen(),
          calls,
        };
        """
    )
    assert result["types"] == {"register": "function", "open": "function", "close": "function", "render": "function"}
    assert result["openResult"]["ok"] is True
    assert result["openResult"]["canvasKind"] == "classic"
    assert result["openResult"]["nodeId"] == "n1"
    assert result["activeFinal"] is False
    fn_names = [c["fn"] for c in result["calls"]]
    assert fn_names == ["open", "render", "close"]


# ---------------------------------------------------------------------------
# T292: openPromptTemplateModal(nodeId) 冻结签名保持
# ---------------------------------------------------------------------------
def test_t292_open_prompt_template_modal_frozen_signature():
    text = CANVAS_JS.read_text(encoding="utf-8")
    # 定义仍然存在（byte-equivalent 保留 async function）
    assert re.search(r"^async\s+function\s+openPromptTemplateModal\s*\(\s*nodeId\s*\)\s*\{", text, re.MULTILINE), (
        "canvas.js 内 openPromptTemplateModal(nodeId) 定义（byte-equivalent）缺失"
    )
    # window 全局 wrapper 存在
    assert "window.openPromptTemplateModal" in text, "canvas.js 未挂 window.openPromptTemplateModal wrapper"


# ---------------------------------------------------------------------------
# T293: renderPromptTemplateModal() 冻结签名保持
# ---------------------------------------------------------------------------
def test_t293_render_prompt_template_modal_frozen_signature():
    text = CANVAS_JS.read_text(encoding="utf-8")
    assert re.search(r"^function\s+renderPromptTemplateModal\s*\(\s*\)\s*\{", text, re.MULTILINE), (
        "canvas.js 内 renderPromptTemplateModal() 定义（byte-equivalent）缺失"
    )
    assert "window.renderPromptTemplateModal" in text, "canvas.js 未挂 window.renderPromptTemplateModal wrapper"


# ---------------------------------------------------------------------------
# T294: closePromptTemplateModal() 冻结签名保持
# ---------------------------------------------------------------------------
def test_t294_close_prompt_template_modal_frozen_signature():
    text = CANVAS_JS.read_text(encoding="utf-8")
    assert re.search(r"^function\s+closePromptTemplateModal\s*\(\s*\)\s*\{", text, re.MULTILINE), (
        "canvas.js 内 closePromptTemplateModal() 定义（byte-equivalent）缺失"
    )
    assert "window.closePromptTemplateModal" in text, "canvas.js 未挂 window.closePromptTemplateModal wrapper"


# ---------------------------------------------------------------------------
# T295: canvas.js 已挂 PromptTemplateDrawer register + wrapper（seam consumer）
# ---------------------------------------------------------------------------
def test_t295_canvas_js_wires_seam_registration_and_wrappers():
    text = CANVAS_JS.read_text(encoding="utf-8")
    # register 挂载存在
    assert "PromptTemplateDrawerReady" in text, "canvas.js 未使用 window.PromptTemplateDrawerReady 挂载 adapter"
    assert "PromptTemplateDrawer.register('classic'" in text, "canvas.js 未 register('classic', ...) 到 seam"
    # 三个 wrapper 都指到本模块内同名函数
    for name in ("openPromptTemplateModal", "renderPromptTemplateModal", "closePromptTemplateModal"):
        assert f"window.{name}" in text, f"canvas.js 未挂 window.{name} wrapper"
    # HTML 加载顺序：seam 三脚本必须在 canvas.js 之前
    html = CANVAS_HTML.read_text(encoding="utf-8")
    idx_registry = html.find("PromptTemplateDrawer/templateRegistry.js")
    idx_editor = html.find("PromptTemplateDrawer/promptEditor.js")
    idx_index = html.find("PromptTemplateDrawer/index.js")
    idx_canvas = html.find("/static/js/canvas.js")
    assert idx_registry > 0 and idx_editor > idx_registry and idx_index > idx_editor and idx_canvas > idx_index, (
        "canvas.html 中 seam 三脚本必须在 canvas.js 之前顺序加载"
    )


# ---------------------------------------------------------------------------
# T296: byte-equivalent 迁移断言 —— 抽屉核心函数体逐字对齐 baseline 97ba98a
# ---------------------------------------------------------------------------
def test_t296_byte_equivalent_migration_vs_baseline():
    """抽屉核心函数（openPromptTemplateModal / closePromptTemplateModal /
    renderPromptTemplateModal / loadCanvasPromptTemplates）在 canvas.js 内的
    函数体行数与 baseline 97ba98a 的差异 ≤ 5%（允许 wrapper/adapter 微小抖动）。"""
    baseline = subprocess.run(
        ["git", "show", "97ba98a:static/js/canvas.js"],
        cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout
    current = CANVAS_JS.read_text(encoding="utf-8")

    def extract_body(source: str, fn_pattern: str) -> str:
        m = re.search(fn_pattern, source, re.MULTILINE)
        assert m, f"pattern not found: {fn_pattern}"
        start = m.end() - 1  # position on the `{`
        depth = 0
        for i in range(start, len(source)):
            ch = source[i]
            if ch == "{": depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return source[start:i + 1]
        raise AssertionError("unbalanced braces")

    patterns = {
        "openPromptTemplateModal": r"^async\s+function\s+openPromptTemplateModal\s*\(\s*nodeId\s*\)\s*\{",
        "closePromptTemplateModal": r"^function\s+closePromptTemplateModal\s*\(\s*\)\s*\{",
        "renderPromptTemplateModal": r"^function\s+renderPromptTemplateModal\s*\(\s*\)\s*\{",
        "loadCanvasPromptTemplates": r"^async\s+function\s+loadCanvasPromptTemplates\s*\(\s*\)\s*\{",
    }
    for name, pat in patterns.items():
        base_body = extract_body(baseline, pat)
        cur_body = extract_body(current, pat)
        # 字节等价：直接字符串相等
        assert base_body == cur_body, (
            f"{name} 函数体与 baseline 97ba98a 不逐字对齐（PR-11 byte-equivalent 契约）"
        )


# ---------------------------------------------------------------------------
# T297: canvas.js 中三条 `let` 模块级变量已迁到 seam registry
# ---------------------------------------------------------------------------
def test_t297_module_level_state_migrated_to_registry():
    text = CANVAS_JS.read_text(encoding="utf-8")
    # 直接的 `let canvasPromptTemplates = ...` / `let canvasPromptTemplatesLoaded = ...` /
    # `let canvasPromptTemplateOverrides = ...` 声明不再存在
    for pattern in (
        r"^let\s+canvasPromptTemplates\s*=",
        r"^let\s+canvasPromptTemplatesLoaded\s*=",
        r"^let\s+canvasPromptTemplateOverrides\s*=",
    ):
        assert not re.search(pattern, text, re.MULTILINE), (
            f"canvas.js 仍存在模块级 `let` 声明匹配 {pattern}（应迁到 templateRegistry.js）"
        )
    # 提示注释存在
    assert "templateRegistry.js" in text, "canvas.js 缺少 seam 迁移的说明性注释"
    # registry 内以 defineProperty 挂载
    reg_text = REGISTRY.read_text(encoding="utf-8")
    for key in ("canvasPromptTemplates", "canvasPromptTemplatesLoaded", "canvasPromptTemplateOverrides"):
        assert f"'{key}'" in reg_text, f"templateRegistry.js 未把 {key} 装到 window（defineProperty）"


# ---------------------------------------------------------------------------
# T298: loader retry / fallback 契约保持
# ---------------------------------------------------------------------------
def test_t298_loader_retry_and_fallback_contract_preserved():
    """`loadCanvasPromptTemplates`：`canvasPromptTemplatesLoaded` 幂等短路 +
    `try/catch` 空态回落 + `canvasPromptTemplatesLoaded = true` 尾置写。"""
    text = CANVAS_JS.read_text(encoding="utf-8")
    # 短路：if(canvasPromptTemplatesLoaded) return canvasPromptTemplates;
    assert re.search(r"if\s*\(\s*canvasPromptTemplatesLoaded\s*\)\s*return\s+canvasPromptTemplates", text), (
        "loadCanvasPromptTemplates 幂等短路契约缺失"
    )
    # 空态回落
    assert "canvasPromptTemplates = []" in text, "loadCanvasPromptTemplates 失败回落 [] 契约缺失"
    assert "canvasPromptLibraries = []" in text, "loadCanvasPromptTemplates 失败回落 libraries=[] 契约缺失"
    # 尾置置 loaded=true
    assert re.search(r"canvasPromptTemplatesLoaded\s*=\s*true", text), (
        "loadCanvasPromptTemplates 尾置 loaded=true 契约缺失"
    )


# ---------------------------------------------------------------------------
# T299: 前端冻结契约 §7.11 段存在且描述与实现一致
# ---------------------------------------------------------------------------
def test_t299_freeze_contract_section_7_11_present():
    text = COMPAT.read_text(encoding="utf-8")
    assert "### 7.11 前端 PR-11 · PromptTemplateDrawer seam 契约" in text, (
        "docs/frontend-freeze/compat-contract.md §7.11 段缺失"
    )
    # 关键契约点必须写在文档里
    for keyword in (
        "static/js/shared/prompt/PromptTemplateDrawer/templateRegistry.js",
        "static/js/shared/prompt/PromptTemplateDrawer/promptEditor.js",
        "static/js/shared/prompt/PromptTemplateDrawer/index.js",
        "openPromptTemplateModal(nodeId)",
        "renderPromptTemplateModal()",
        "closePromptTemplateModal()",
        "canvas_prompt_template_groups_v1",
        "canvas_prompt_template_overrides",
        "PromptTemplateDrawerReady",
        "byte-equivalent",
    ):
        assert keyword in text, f"§7.11 缺少契约关键点: {keyword}"
