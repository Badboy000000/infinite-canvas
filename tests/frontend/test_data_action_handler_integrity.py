"""Wave 3-I 承接强化补丁 · handler-integrity 端到端抗回归测试。

反审背景（Reality Checker × 前端 PR-7 独立发现 P0-1）
====================================================
前端 PR-7 `bootstrap.js:autoBindLegacyGlobals` 列表中把 canvas.html 里
`data-action="menuAdd"`（唯一存在的 canvas.js:3543 函数）误列为 11 个不存在的
`menuAddImage` / `menuAddPrompt` / ... `menuAddOutput` 名字。由于
`autoBindLegacyGlobals` 的语义就是"函数不存在时静默 skip"，pytest 全绿而
主画布 createMenu 11 个"右键新建节点"按钮**全部无响应**（用户可见回归）。

治理机制候选（GM-08）
=====================
"data-action 迁移必须端到端可达" —— 任何 HTML 里出现 `data-action="X"` 的名字，
必须满足以下 三重契约：

    (a) `X` 在 `bootstrap.js` autoBind 列表里出现（**或**在
        `canvas.js`/`smart-canvas.js` 里显式 `actionBus.register('X', ...)`）
    (b) 在 `canvas.js` / `smart-canvas.js` 中存在 `function X\b` 定义
        （或 `data-action-arg` 分派场景下，目标 `X(arg)` 存在）
    (c) autoBind 名字都必须在两画布中被至少一处 `data-action=` 使用（
        避免"绑了没用"死配置；本条属 P2 强化，作为 WARN 而非 FAIL）

本模块是 GM-08 pattern 的 pre-commit 抗回归 —— 任何未来 PR 若破坏
上述三重契约，测试立即 FAIL 而不是等到人工发现按钮无响应。

配套治理机制候选（GM-09）
========================
"autoBind 静默 skip 反模式" —— 任何以"缺失即静默"为默认行为的注册型 API，
**必须**在测试层配套一条"引用完整性"断言，或改 API 语义为"缺失即报警"。
本文件的 T1/T2 就是 GM-09 pattern 的落地示范。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANVAS_HTML = ROOT / "static/canvas.html"
SMART_HTML = ROOT / "static/smart-canvas.html"
CANVAS_JS = ROOT / "static/js/canvas.js"
SMART_JS = ROOT / "static/js/smart-canvas.js"
BOOTSTRAP = ROOT / "static/js/modules/node/bootstrap.js"

_DATA_ACTION_RE = re.compile(r'data-action="([^"]+)"')


def _collect_data_action_names(html_path: Path) -> set[str]:
    """扫描 HTML,返回所有 `data-action="X"` 中的 X 名字集合。"""
    return set(_DATA_ACTION_RE.findall(html_path.read_text(encoding="utf-8")))


def _collect_autobind_names(bootstrap_path: Path) -> set[str]:
    """解析 bootstrap.js autoBindLegacyGlobals(['a','b',...]) 中的名字集合。

    实现:找到 `autoBindLegacyGlobals([` 到匹配 `])` 的段,
    再 grep 所有 `'X'` / `"X"` 字面量。
    """
    src = bootstrap_path.read_text(encoding="utf-8")
    m = re.search(r'autoBindLegacyGlobals\(\[(.*?)\]\)', src, re.DOTALL)
    assert m, "bootstrap.js 中未找到 autoBindLegacyGlobals([...]) 调用"
    body = m.group(1)
    return set(re.findall(r"['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]", body))


def _function_exists(js_src: str, name: str) -> bool:
    """检查 JS 源码中是否 `function <name>(...)` 定义。"""
    return re.search(rf"^function\s+{re.escape(name)}\s*\(", js_src, re.MULTILINE) is not None


def _has_action_bus_register(js_src: str, name: str) -> bool:
    """检查 JS 源码中是否 `actionBus.register('<name>', ...)` 显式注册。"""
    pat = re.compile(rf"actionBus\.register\s*\(\s*['\"]{re.escape(name)}['\"]")
    return pat.search(js_src) is not None


def test_all_html_data_action_names_are_bound() -> None:
    """T1 (GM-08 契约 a+b):HTML data-action 名字必须能被 dispatch 到 handler。

    每个 `data-action="X"`必须满足:
      (a) X 在 bootstrap.js autoBind 列表 OR X 有 actionBus.register 显式注册
      (b) 存在 `function X\\b` 定义 in canvas.js / smart-canvas.js

    P0-1 场景:HTML 有 `data-action="menuAdd"`,autoBind 列表只有不存在的
    `menuAddImage/Prompt/...` → autoBind FAIL + register FAIL → 用户可见回归。
    修复后 autoBind 列表补上 `menuAdd` → 断言过。
    """
    html_names = _collect_data_action_names(CANVAS_HTML) | _collect_data_action_names(SMART_HTML)
    autobind_names = _collect_autobind_names(BOOTSTRAP)
    canvas_src = CANVAS_JS.read_text(encoding="utf-8")
    smart_src = SMART_JS.read_text(encoding="utf-8")
    combined = canvas_src + "\n" + smart_src

    unbound: list[tuple[str, str]] = []
    undefined: list[str] = []
    for name in sorted(html_names):
        bound = (name in autobind_names) or _has_action_bus_register(combined, name)
        defined = _function_exists(combined, name)
        if not bound:
            unbound.append((name, "not in autoBind list nor actionBus.register()"))
        if not defined:
            undefined.append(name)

    assert not unbound, (
        f"[GM-08 契约 a] HTML data-action 名字未被 bind:\n"
        + "\n".join(f"  - {n}: {r}" for n, r in unbound)
        + f"\n\n  HTML 名字集合: {sorted(html_names)}"
        + f"\n  autoBind 集合: {sorted(autobind_names)}"
    )
    assert not undefined, (
        f"[GM-08 契约 b] HTML data-action 名字在两画布 JS 中无 function 定义:\n"
        + "\n".join(f"  - {n}" for n in undefined)
    )


def test_autobind_names_have_matching_js_function() -> None:
    """T2 (GM-08 契约 b · autoBind 侧):autoBind 列表里每个名字都必须在
    canvas.js / smart-canvas.js 里有对应 `function X(...)`。

    P0-1 场景:autoBind 列表里的 `menuAddImage` / `menuAddPrompt` / ... 11 个
    在两画布 JS 里都不存在 → 静默 skip → 用户可见回归。修复后删除 11 个死名 +
    加 `menuAdd` (唯一存在) → 断言过。

    这是 GM-09 "autoBind 静默 skip 反模式" 的直接对策 —— 引用完整性硬断言。
    """
    autobind_names = _collect_autobind_names(BOOTSTRAP)
    canvas_src = CANVAS_JS.read_text(encoding="utf-8")
    smart_src = SMART_JS.read_text(encoding="utf-8")
    combined = canvas_src + "\n" + smart_src

    missing = [name for name in sorted(autobind_names) if not _function_exists(combined, name)]
    assert not missing, (
        f"[GM-08 契约 b · GM-09 引用完整性] bootstrap.js autoBind 列表包含在两画布 JS 中"
        f"不存在的函数名:\n"
        + "\n".join(f"  - {n}" for n in missing)
        + "\n\n"
        "违反 GM-09:autoBindLegacyGlobals 语义 = 缺失即静默 skip;"
        "列表里的死名会让浏览器里默默不绑,而 pytest 却全绿 —— 生产回归风险高。\n"
        "修复:要么从列表中删除,要么在两画布中添加对应 function 定义。"
    )


def test_autobind_names_used_by_at_least_one_data_action() -> None:
    """T3 (GM-08 契约 c · autoBind 使用率 · P2 警告级):autoBind 列表里每个
    名字都应该在两 HTML 中至少一处 `data-action=` 使用。

    未使用的 autoBind 项属"绑了没用"死配置 —— 不构成运行时回归,但是死代码 +
    误导性配置(未来开发者可能以为在使用)。本 test 作为 GM-08 pattern 的
    P2 强化断言。

    豁免规则:某些名字属于"预备但未来 PR 承接",Wave 3-I 承接补丁已把明确的
    5 个死名 close* 系列删除;剩下的名字应该都是活的。
    """
    autobind_names = _collect_autobind_names(BOOTSTRAP)
    canvas_data_actions = _collect_data_action_names(CANVAS_HTML)
    smart_data_actions = _collect_data_action_names(SMART_HTML)
    all_html_names = canvas_data_actions | smart_data_actions

    unused = sorted(autobind_names - all_html_names)
    assert not unused, (
        f"[GM-08 契约 c] autoBind 列表包含未被任何 HTML `data-action=` 使用的名字:\n"
        + "\n".join(f"  - {n}" for n in unused)
        + "\n\n"
        + "这是'绑了没用'死配置 —— 从 autoBind 列表删除,或在 HTML 中加对应 data-action="
    )


def test_html_no_double_binding_onclick_and_data_action_on_same_element() -> None:
    """T4 (前端 PR-7 P1-2 双绑互斥):同一 HTML 元素不能同时出现 `onclick=`
    和 `data-action=` (会导致点击时 legacy onclick + action-bus dispatch 双触发)。

    协调纲要 §关键决策 8 明确"两通道互斥,无双触发风险"。承接补丁把此契约
    转为断言。
    """
    # 匹配包含 onclick + data-action 的同一开标签(<button ... onclick=... data-action=...>
    # 或反序 <button ... data-action=... onclick=...>)
    double_bind_re = re.compile(
        r'<[^>]*\bonclick="[^"]*"[^>]*\bdata-action="[^"]*"[^>]*>|'
        r'<[^>]*\bdata-action="[^"]*"[^>]*\bonclick="[^"]*"[^>]*>',
        re.DOTALL,
    )
    for html_path in (CANVAS_HTML, SMART_HTML):
        content = html_path.read_text(encoding="utf-8")
        matches = double_bind_re.findall(content)
        assert not matches, (
            f"[前端 PR-7 P1-2] {html_path.name} 中发现同一元素同时有 onclick 和 "
            f"data-action(双触发风险),需要二选一:\n"
            + "\n".join(f"  {m[:200]}..." for m in matches[:3])
        )


def test_menuadd_specifically_bound_and_defined() -> None:
    """T5 (GM-08 契约 a+b · P0-1 直接回归锚点):`menuAdd` 名字**必须**在
    autoBind 列表 + canvas.js 中都存在 —— 这是 P0-1 直接锚定的场景。

    P0-1 复现:去掉 `menuAdd` → 此 test FAIL。
    """
    autobind_names = _collect_autobind_names(BOOTSTRAP)
    assert "menuAdd" in autobind_names, (
        "[P0-1 抗回归锚点] `menuAdd` 必须在 bootstrap.js autoBind 列表中 —— "
        "canvas.html 有 11 个 `data-action=\"menuAdd\" data-action-arg=\"...\"` 按钮依赖此绑定。"
        "若删除会导致 createMenu 11 按钮全部失效(pytest 全绿 + 用户可见回归)。"
    )
    canvas_src = CANVAS_JS.read_text(encoding="utf-8")
    assert _function_exists(canvas_src, "menuAdd"), (
        "[P0-1 抗回归锚点] `function menuAdd(type)` 必须在 canvas.js 中定义 "
        "(canvas.js:3543 参数分发实现)。若删除,即使 autoBind 也无 handler 可调。"
    )


def test_action_bus_dispatches_menuadd_with_arg_split() -> None:
    """T6 (P0-1 端到端运行时验证):在 Node 环境模拟 action-bus.js dispatch,
    验证 `data-action="menuAdd" data-action-arg="image"` 会调用 `menuAdd('image')`。

    这是从"静态检查名字存在"升级到"运行时验证 dispatch 通路"的强化断言。
    """
    import subprocess as sp
    action_bus_uri = (ROOT / "static/js/shared/interaction/action-bus.js").as_uri()
    # action-bus.js exports a singleton `actionBus` as default. autoBindLegacyGlobals
    # 默认从 `window` 读函数;Node ESM 无 window,显式 pass {window: scope}。
    script = (
        f"import actionBus from '{action_bus_uri}';"
        "const calls = [];"
        "const scope = {};"
        "scope.menuAdd = function(type){ calls.push(['menuAdd', type]); };"
        "actionBus.clear();"
        "actionBus.autoBindLegacyGlobals(['menuAdd'], {window: scope});"
        # 模拟带 arg 的 dispatch:action-bus 会 split ',' 分派多参
        "const event = {"
        "  target: {"
        "    closest: (sel) => (sel === '[data-action]' ? {"
        "      getAttribute: (k) => (k === 'data-action' ? 'menuAdd' :"
        "                              k === 'data-action-arg' ? 'image' : null),"
        "    } : null),"
        "  },"
        "};"
        "const invoked = actionBus.dispatch(event);"
        "console.log(JSON.stringify({invoked, calls}));"
    )
    result = sp.run(
        ["node", "--experimental-default-type=module", "-e", script],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, f"node dispatch script failed: {result.stderr}"
    import json as _json
    payload = _json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["invoked"] is True, (
        f"[P0-1 端到端] bus.dispatch 未成功调用 menuAdd:{payload}"
    )
    assert payload["calls"] == [["menuAdd", "image"]], (
        f"[P0-1 端到端] menuAdd 应被以 'image' 参数调用:{payload}"
    )
