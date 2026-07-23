"""Wave 3-N.6 Batch 3 主线 B · 前端 PR-9 契约测试 · sessionStore + FrontRequestContext + Can 骨架 + capabilities 消费.

Editorial:
    Runs Node ESM subprocesses to exercise the newly landed native ES modules on disk.
    Follows the pattern established by `test_pr_8_shared_components.py` (前端 PR-8)
    and `test_shared_stores_seam.py` (前端 PR-5).

Covers T410-T425 (16 items):

    T410  sessionStore 默认状态 (clientId/legacyUserKey/workspaceId/projectId 全 null;
          authMode='anonymous_or_legacy'; capabilities 全 true)
    T411  sessionStore.refresh() 成功场景 (mock fetch /api/whoami · 填 6 字段)
    T412  sessionStore.refresh() 404 场景 (端点未上线 · 全 true 降级 · 不抛错)
    T413  sessionStore.refresh() 网络失败场景 (fetch reject · 全 true 降级 · 不抛错)
    T414  sessionStore.refresh() 500 场景 (全 true 降级 · 不抛错)
    T415  FrontRequestContext.toHeaders() 序列化 (clientId → X-Client-Id · null 不产生空 header)
    T416  interceptors.defaultRequestInterceptor 合并 headers (不覆盖用户显式传入)
    T417  interceptors.defaultResponseInterceptor 提取 X-Request-Id · 更新 sessionStore.requestId
    T418  Can.mount 订阅 sessionStore.capabilities · true 显示 · false hide
    T419  Can.unmount 撤销订阅 · 不留监听
    T420  Can 权限未上线时透明放行 (capabilities 全 true → 所有 element 可见)
    T421  sessionStore + interceptors + Can 端到端集成 · fake DOM 场景
    T422  5 HTML cache-buster 闭环 (参照 PR-8 T344)
    T423  SessionStoreReady Promise 就绪信号
    T424  X-Client-Id 通过 interceptors 注入 · legacy 后端不强制
    T425  服务端未上线场景 · Can 组件不阻断任何 UI · 全量断言

**T412 / T413 / T414 / T420 权限未上线降级契约** 是 TRA 最容易挑战的点 · 全部写成真实
网络 mock 场景 (globalThis.fetch 替换) · 不是重言式。
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

SESSION_STORE = (ROOT / "static/js/shared/stores/sessionStore.js").as_uri()
CONTEXT = (ROOT / "static/js/shared/api-client/context.js").as_uri()
INTERCEPTORS = (ROOT / "static/js/shared/api-client/interceptors.js").as_uri()
CAN = (ROOT / "static/js/shared/components/Can/index.js").as_uri()
SESSION_BOOTSTRAP = ROOT / "static/js/shared/session/bootstrap.js"

HTML_PAGES = [
    ROOT / "static/canvas.html",
    ROOT / "static/smart-canvas.html",
    ROOT / "static/asset-manager.html",
    ROOT / "static/api-settings.html",
    ROOT / "static/comfyui-settings.html",
]


def _run_node_esm(script: str) -> dict:
    completed = subprocess.run(
        ["node", "--experimental-default-type=module", "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"node exited with {completed.returncode}\n"
            f"--- stderr ---\n{completed.stderr}\n"
            f"--- stdout ---\n{completed.stdout}"
        )
    out = completed.stdout.strip().splitlines()
    return json.loads(out[-1])


# ---------------------------------------------------------------------------
# Mock fetch prelude (T411 / T412 / T413 / T414):真实网络场景 mock · 不是重言.
# 每个 test 独立 fetch stub · 通过 payload 控制返回 status / body / 是否 reject.
# ---------------------------------------------------------------------------
def _fetch_stub_prelude(fetch_spec: dict) -> str:
    """构造 globalThis.fetch stub JS 前缀.

    fetch_spec:
      { "kind": "ok", "body": {...} }        → 200 JSON
      { "kind": "404" }                       → 404 空 body
      { "kind": "500" }                       → 500 空 body
      { "kind": "network" }                    → fetch reject
      { "kind": "requestId-header", "requestId": "..." } → 200 + X-Request-Id
    """
    spec_json = json.dumps(fetch_spec)
    return f"""
        const _fetchSpec = {spec_json};
        globalThis._fetchCalls = [];
        globalThis.fetch = async function(url, init) {{
            globalThis._fetchCalls.push({{ url: String(url), init: init || null }});
            if (_fetchSpec.kind === 'network') {{
                throw new TypeError('network down');
            }}
            const headers = new Map();
            if (_fetchSpec.kind === 'requestId-header') {{
                headers.set('x-request-id', _fetchSpec.requestId);
                headers.set('content-type', 'application/json');
            }} else if (_fetchSpec.kind === 'ok') {{
                headers.set('content-type', 'application/json');
            }}
            const status =
                _fetchSpec.kind === 'ok' || _fetchSpec.kind === 'requestId-header' ? 200
                : _fetchSpec.kind === '404' ? 404
                : _fetchSpec.kind === '500' ? 500
                : 200;
            const bodyStr = _fetchSpec.body != null ? JSON.stringify(_fetchSpec.body) : '';
            return {{
                ok: status >= 200 && status < 300,
                status,
                statusText: '',
                headers: {{
                    get: (k) => headers.get(String(k).toLowerCase()) || null,
                }},
                async json() {{ return _fetchSpec.body != null ? _fetchSpec.body : {{}}; }},
                async text() {{ return bodyStr; }},
                clone() {{ return this; }},
            }};
        }};
    """


# ===========================================================================
# T410 · sessionStore 默认状态
# ===========================================================================
def test_t410_session_store_default_state():
    script = f"""
        import {{ sessionStore, DEFAULT_CAPABILITIES }} from {json.dumps(SESSION_STORE)};
        const s = sessionStore.state;
        console.log(JSON.stringify({{
            clientId: s.clientId,
            legacyUserKey: s.legacyUserKey,
            workspaceId: s.workspaceId,
            projectId: s.projectId,
            authMode: s.authMode,
            requestId: s.requestId,
            capabilities: s.capabilities,
            defaultCapsAllTrue: Object.values(DEFAULT_CAPABILITIES).every(v => v === true),
        }}));
    """
    result = _run_node_esm(script)
    assert result["clientId"] is None
    assert result["legacyUserKey"] is None
    assert result["workspaceId"] is None
    assert result["projectId"] is None
    assert result["authMode"] == "anonymous_or_legacy"
    assert result["requestId"] is None
    assert result["defaultCapsAllTrue"] is True
    # capabilities 至少含约定动作 · 全 true
    assert all(v is True for v in result["capabilities"].values())
    assert "canvas.delete" in result["capabilities"]
    assert "provider.delete" in result["capabilities"]
    assert "workflow.overwrite" in result["capabilities"]


# ===========================================================================
# T411 · refresh() 成功场景 (真实 fetch mock)
# ===========================================================================
def test_t411_session_store_refresh_success_fills_context():
    fetch_stub = _fetch_stub_prelude({
        "kind": "ok",
        "body": {
            "principal_kind": "user",
            "user_id": "alice",
            "workspace_id": "w1",
            "project_id": "p1",
            "request_id": "req-abc",
        },
    })
    script = f"""
        {fetch_stub}
        const mod = await import({json.dumps(SESSION_STORE)});
        await mod.sessionStore.refetch('test');
        console.log(JSON.stringify({{
            state: mod.sessionStore.state,
            calls: globalThis._fetchCalls.map(c => ({{ url: c.url, method: (c.init && c.init.method) || 'GET' }})),
        }}));
    """
    result = _run_node_esm(script)
    state = result["state"]
    assert state["legacyUserKey"] == "alice"
    assert state["workspaceId"] == "w1"
    assert state["projectId"] == "p1"
    assert state["authMode"] == "legacy_alias"
    assert state["requestId"] == "req-abc"
    # capabilities 仍是全 true (whoami 骨架层不返回 capabilities · 权限 PR-3 承接)
    assert all(v is True for v in state["capabilities"].values())
    # 真实 fetch call:URL 含 /api/whoami · method=GET
    assert any("/api/whoami" in c["url"] for c in result["calls"])
    assert result["calls"][0]["method"] == "GET"


# ===========================================================================
# T412 · refresh() 404 场景 (端点未上线 · 全 true 降级 · 不抛错)
# ===========================================================================
def test_t412_session_store_refresh_404_degrades_to_all_true():
    fetch_stub = _fetch_stub_prelude({"kind": "404"})
    script = f"""
        {fetch_stub}
        const mod = await import({json.dumps(SESSION_STORE)});
        let thrown = null;
        try {{
            await mod.sessionStore.refetch('test-404');
        }} catch (e) {{
            thrown = String(e && e.message || e);
        }}
        console.log(JSON.stringify({{
            state: mod.sessionStore.state,
            thrown,
            fetchCalled: globalThis._fetchCalls.length,
        }}));
    """
    result = _run_node_esm(script)
    # 硬断言:404 不抛错
    assert result["thrown"] is None, f"404 场景不应抛错 · thrown={result['thrown']!r}"
    # 全 true 降级
    assert all(v is True for v in result["state"]["capabilities"].values())
    # legacyUserKey 保持 null (未从 body 填充)
    assert result["state"]["legacyUserKey"] is None
    assert result["fetchCalled"] >= 1


# ===========================================================================
# T413 · refresh() 网络失败场景 (fetch reject · 全 true 降级 · 不抛错)
# ===========================================================================
def test_t413_session_store_refresh_network_failure_degrades():
    fetch_stub = _fetch_stub_prelude({"kind": "network"})
    script = f"""
        {fetch_stub}
        const mod = await import({json.dumps(SESSION_STORE)});
        let thrown = null;
        try {{
            await mod.sessionStore.refetch('test-network');
        }} catch (e) {{
            thrown = String(e && e.message || e);
        }}
        console.log(JSON.stringify({{
            state: mod.sessionStore.state,
            thrown,
        }}));
    """
    result = _run_node_esm(script)
    assert result["thrown"] is None, f"网络失败不应抛错 · thrown={result['thrown']!r}"
    assert all(v is True for v in result["state"]["capabilities"].values())
    assert result["state"]["legacyUserKey"] is None


# ===========================================================================
# T414 · refresh() 500 场景 (全 true 降级 · 不抛错)
# ===========================================================================
def test_t414_session_store_refresh_500_degrades():
    fetch_stub = _fetch_stub_prelude({"kind": "500"})
    script = f"""
        {fetch_stub}
        const mod = await import({json.dumps(SESSION_STORE)});
        let thrown = null;
        try {{
            await mod.sessionStore.refetch('test-500');
        }} catch (e) {{
            thrown = String(e && e.message || e);
        }}
        console.log(JSON.stringify({{
            state: mod.sessionStore.state,
            thrown,
        }}));
    """
    result = _run_node_esm(script)
    assert result["thrown"] is None, f"500 场景不应抛错 · thrown={result['thrown']!r}"
    assert all(v is True for v in result["state"]["capabilities"].values())
    assert result["state"]["legacyUserKey"] is None


# ===========================================================================
# T415 · FrontRequestContext.toHeaders() 序列化
# ===========================================================================
def test_t415_front_request_context_to_headers_omits_null():
    script = f"""
        import {{ FrontRequestContext }} from {json.dumps(CONTEXT)};
        const ctxFull = new FrontRequestContext({{
            clientId: 'c1',
            legacyUserKey: 'lk',
            workspaceId: 'w1',
            projectId: 'p1',
            requestId: 'r1',
            authMode: 'legacy_alias',
        }});
        const ctxEmpty = new FrontRequestContext({{}});
        const ctxPartial = new FrontRequestContext({{ clientId: 'only-client' }});
        console.log(JSON.stringify({{
            full: ctxFull.toHeaders(),
            empty: ctxEmpty.toHeaders(),
            partial: ctxPartial.toHeaders(),
            frozen: Object.isFrozen(ctxFull),
        }}));
    """
    result = _run_node_esm(script)
    assert result["full"] == {
        "X-Client-Id": "c1",
        "X-Workspace-Id": "w1",
        "X-Project-Id": "p1",
    }, "full ctx 应含 3 个非空 header (X-Request-Id 不发送)"
    # 硬断言:null 字段不产生空 header
    assert result["empty"] == {}, f"empty ctx 应零 header · got {result['empty']}"
    assert result["partial"] == {"X-Client-Id": "only-client"}
    assert result["frozen"] is True, "FrontRequestContext 必须 frozen"


# ===========================================================================
# T416 · defaultRequestInterceptor 合并 headers (用户显式优先)
# ===========================================================================
def test_t416_default_request_interceptor_user_headers_win():
    script = f"""
        import {{ defaultRequestInterceptor, mergeHeaders }} from {json.dumps(INTERCEPTORS)};
        const fakeStore = {{
            state: {{
                clientId: 'ctx-client',
                workspaceId: 'ctx-ws',
                projectId: 'ctx-proj',
                requestId: null,
                authMode: 'legacy_alias',
                legacyUserKey: null,
            }},
        }};
        // 用户显式 headers (大小写不敏感 · 应覆盖 ctx)
        const merged = defaultRequestInterceptor(
            {{ headers: {{ 'x-client-id': 'user-client', 'Authorization': 'Bearer x' }} }},
            fakeStore,
        );
        // 无 user header 情形
        const noUser = defaultRequestInterceptor({{ headers: null }}, fakeStore);
        console.log(JSON.stringify({{
            merged: merged.headers,
            noUser: noUser.headers,
        }}));
    """
    result = _run_node_esm(script)
    # 用户显式 x-client-id 优先 · ctx X-Client-Id 被丢弃
    hdrs = result["merged"]
    lower = {k.lower(): v for k, v in hdrs.items()}
    assert lower.get("x-client-id") == "user-client", f"user header 应优先 · got {hdrs}"
    assert lower.get("authorization") == "Bearer x"
    assert lower.get("x-workspace-id") == "ctx-ws"
    assert lower.get("x-project-id") == "ctx-proj"
    # 无 user header 时 · ctx 3 个 header 完整注入
    no_user_lower = {k.lower(): v for k, v in result["noUser"].items()}
    assert no_user_lower.get("x-client-id") == "ctx-client"
    assert no_user_lower.get("x-workspace-id") == "ctx-ws"
    assert no_user_lower.get("x-project-id") == "ctx-proj"


# ===========================================================================
# T417 · defaultResponseInterceptor 提取 X-Request-Id
# ===========================================================================
def test_t417_default_response_interceptor_extracts_request_id():
    script = f"""
        import {{ defaultResponseInterceptor }} from {json.dumps(INTERCEPTORS)};
        // 迷你 store shim · 只需 state + setState
        const store = {{
            state: {{ requestId: null }},
            setState(patch, reason) {{
                Object.keys(patch).forEach(k => {{ this.state[k] = patch[k]; }});
                this.lastReason = reason;
            }},
        }};
        // fake Response
        const responseWithRid = {{ headers: {{ get: (k) => k.toLowerCase() === 'x-request-id' ? 'req-xyz' : null }} }};
        defaultResponseInterceptor(responseWithRid, store);
        const afterFirst = store.state.requestId;
        // 幂等:同 rid 不重复触发 setState
        store.lastReason = null;
        defaultResponseInterceptor(responseWithRid, store);
        const idempotentReason = store.lastReason;
        // 无 rid 场景:不触发
        const responseNoRid = {{ headers: {{ get: () => null }} }};
        store.lastReason = null;
        defaultResponseInterceptor(responseNoRid, store);
        console.log(JSON.stringify({{
            afterFirst,
            idempotentReason,
            noRidReason: store.lastReason,
        }}));
    """
    result = _run_node_esm(script)
    assert result["afterFirst"] == "req-xyz"
    assert result["idempotentReason"] is None, "同 rid 二次 · 不应重复 setState"
    assert result["noRidReason"] is None, "无 rid · 不应 setState"


# ===========================================================================
# T418 · Can.mount 订阅 sessionStore.capabilities · true 显示 · false hide
# ===========================================================================
def test_t418_can_mount_toggles_display_on_capability_change():
    script = f"""
        import Can from {json.dumps(CAN)};
        // fake sessionStore
        const subs = new Set();
        const store = {{
            state: {{ capabilities: {{ 'provider.delete': true }} }},
            subscribe(fn) {{ subs.add(fn); return () => subs.delete(fn); }},
            _notify() {{ subs.forEach(fn => fn(this.state, 1, 'test')); }},
        }};
        const el = {{ style: {{ display: '' }}, _attrs: {{}},
            setAttribute(k,v){{ this._attrs[k]=String(v); }},
            getAttribute(k){{ return this._attrs[k] || null; }},
            removeAttribute(k){{ delete this._attrs[k]; }},
        }};
        Can.mount(el, store, 'provider.delete');
        const initialDisplay = el.style.display;
        // 翻转到 false
        store.state.capabilities = {{ 'provider.delete': false }};
        store._notify();
        const afterFalseDisplay = el.style.display;
        const hiddenAttr = el.getAttribute('data-can-hidden');
        // 翻转回 true
        store.state.capabilities = {{ 'provider.delete': true }};
        store._notify();
        const afterTrueDisplay = el.style.display;
        const hiddenAttrAfter = el.getAttribute('data-can-hidden');
        console.log(JSON.stringify({{
            initialDisplay,
            afterFalseDisplay,
            hiddenAttr,
            afterTrueDisplay,
            hiddenAttrAfter,
            subCountAfterMount: subs.size,
        }}));
    """
    result = _run_node_esm(script)
    assert result["initialDisplay"] == "", "初始 true → display 为空 (浏览器默认)"
    assert result["afterFalseDisplay"] == "none", "false 后应 hide"
    assert result["hiddenAttr"] == "1", "hide 时应写 data-can-hidden=1"
    assert result["afterTrueDisplay"] == "", "true 后应恢复 display"
    assert result["hiddenAttrAfter"] is None, "恢复后 data-can-hidden 应清除"
    assert result["subCountAfterMount"] == 1


# ===========================================================================
# T419 · Can.unmount 撤销订阅 · 不留监听
# ===========================================================================
def test_t419_can_unmount_removes_subscription():
    script = f"""
        import Can from {json.dumps(CAN)};
        const subs = new Set();
        const store = {{
            state: {{ capabilities: {{ 'x': true }} }},
            subscribe(fn) {{ subs.add(fn); return () => subs.delete(fn); }},
        }};
        const el = {{ style: {{ display: '' }}, _attrs: {{}},
            setAttribute(k,v){{ this._attrs[k]=String(v); }},
            getAttribute(k){{ return this._attrs[k] || null; }},
            removeAttribute(k){{ delete this._attrs[k]; }},
        }};
        const unmount = Can.mount(el, store, 'x');
        const afterMount = subs.size;
        unmount();
        const afterUnmount = subs.size;
        // 二次 unmount 幂等
        Can.unmount(el);
        console.log(JSON.stringify({{ afterMount, afterUnmount }}));
    """
    result = _run_node_esm(script)
    assert result["afterMount"] == 1
    assert result["afterUnmount"] == 0, "unmount 后订阅应清空 · 不留监听"


# ===========================================================================
# T420 · Can 权限未上线时透明放行 (capabilities 全 true → 所有 element 可见)
# ===========================================================================
def test_t420_can_transparent_pass_when_capabilities_all_true():
    # 全真实:sessionStore 默认 state · 无 fetch · Can.autoMount 遍历多元素
    script = f"""
        import {{ sessionStore, DEFAULT_CAPABILITIES }} from {json.dumps(SESSION_STORE)};
        import Can from {json.dumps(CAN)};
        // fake root · 多个 [data-can] 元素模拟真实 DOM
        function makeEl(action) {{
            return {{
                style: {{ display: '' }},
                _attrs: {{ 'data-can': action }},
                setAttribute(k,v){{ this._attrs[k]=String(v); }},
                getAttribute(k){{ return this._attrs[k] == null ? null : String(this._attrs[k]); }},
                removeAttribute(k){{ delete this._attrs[k]; }},
            }};
        }}
        const elements = [
            makeEl('canvas.delete'),
            makeEl('provider.delete'),
            makeEl('workflow.overwrite'),
            makeEl('unregistered.action'),   // 未登记 → 透明放行
            makeEl('canvas.edit'),
        ];
        const root = {{
            querySelectorAll(sel) {{
                if (sel === '[data-can]') return elements;
                return [];
            }},
        }};
        const count = Can.autoMount(root, sessionStore);
        // 所有 element 应可见 (display 不为 'none')
        const visibleStatuses = elements.map(el => ({{
            action: el._attrs['data-can'],
            display: el.style.display,
            hidden: el._attrs['data-can-hidden'] || null,
        }}));
        console.log(JSON.stringify({{
            count,
            visibleStatuses,
            defaultAllTrue: Object.values(DEFAULT_CAPABILITIES).every(v => v === true),
        }}));
    """
    result = _run_node_esm(script)
    assert result["count"] == 5, "autoMount 应识别 5 个 [data-can] 元素"
    assert result["defaultAllTrue"] is True
    # 硬断言:所有 5 个 element 可见 · 包括未登记 action (透明放行)
    for status in result["visibleStatuses"]:
        assert status["display"] != "none", (
            f"权限未上线场景 · action={status['action']!r} 应可见 · "
            f"实际 display={status['display']!r}"
        )
        assert status["hidden"] is None, (
            f"action={status['action']!r} 不应带 data-can-hidden"
        )


# ===========================================================================
# T421 · 端到端集成:sessionStore + interceptors + Can · fake DOM
# ===========================================================================
def test_t421_end_to_end_integration_fake_dom():
    """真实网络成功场景:refresh 后 FrontRequestContext 字段 → interceptors 合并 →
    Can 组件基于 capabilities 全 true 透明放行."""
    fetch_stub = _fetch_stub_prelude({
        "kind": "ok",
        "body": {
            "principal_kind": "user",
            "user_id": "e2e-user",
            "workspace_id": "e2e-ws",
            "project_id": "e2e-proj",
            "request_id": "e2e-req",
        },
    })
    script = f"""
        {fetch_stub}
        const {{ sessionStore }} = await import({json.dumps(SESSION_STORE)});
        const {{ FrontRequestContext }} = await import({json.dumps(CONTEXT)});
        const {{ defaultRequestInterceptor }} = await import({json.dumps(INTERCEPTORS)});
        const Can = (await import({json.dumps(CAN)})).default;

        await sessionStore.refetch('e2e');
        const ctx = FrontRequestContext.from(sessionStore.state);
        const hdrs = ctx.toHeaders();
        const reqCfg = defaultRequestInterceptor({{ headers: {{ 'Content-Type': 'application/json' }} }}, sessionStore);

        // fake button
        const btn = {{
            style: {{ display: '' }},
            _attrs: {{ 'data-can': 'provider.delete' }},
            setAttribute(k,v){{ this._attrs[k]=String(v); }},
            getAttribute(k){{ return this._attrs[k] == null ? null : String(this._attrs[k]); }},
            removeAttribute(k){{ delete this._attrs[k]; }},
        }};
        const un = Can.mount(btn, sessionStore, 'provider.delete');
        const btnDisplayAfterMount = btn.style.display;

        console.log(JSON.stringify({{
            legacyUserKey: sessionStore.state.legacyUserKey,
            workspaceId: sessionStore.state.workspaceId,
            authMode: sessionStore.state.authMode,
            requestId: sessionStore.state.requestId,
            headers: hdrs,
            requestConfigHeaders: reqCfg.headers,
            btnDisplayAfterMount,
        }}));
    """
    result = _run_node_esm(script)
    # sessionStore 填充
    assert result["legacyUserKey"] == "e2e-user"
    assert result["workspaceId"] == "e2e-ws"
    assert result["authMode"] == "legacy_alias"
    assert result["requestId"] == "e2e-req"
    # FrontRequestContext headers 序列化正确
    assert result["headers"].get("X-Workspace-Id") == "e2e-ws"
    assert result["headers"].get("X-Project-Id") == "e2e-proj"
    # X-Request-Id 不发送
    assert "X-Request-Id" not in result["headers"]
    # 用户显式 Content-Type 保留 (case-insensitive)
    ci = {k.lower(): v for k, v in result["requestConfigHeaders"].items()}
    assert ci.get("content-type") == "application/json"
    # Can 组件:capabilities 全 true (whoami 骨架层不返回) → button 可见
    assert result["btnDisplayAfterMount"] != "none"


# ===========================================================================
# T422 · 5 HTML cache-buster 闭环 (参照 PR-8 T344)
# ===========================================================================
def test_t422_five_html_pages_include_session_bootstrap():
    missing = []
    unversioned = []
    for path in HTML_PAGES:
        text = path.read_text(encoding="utf-8")
        if "/static/js/shared/session/bootstrap.js" not in text:
            missing.append(path.name)
            continue
        m = re.search(
            r"/static/js/shared/session/bootstrap\.js\?v=[^\"'\s]+",
            text,
        )
        if not m:
            unversioned.append(path.name)
    assert missing == [], f"以下 HTML 缺 session/bootstrap.js 引入: {missing}"
    assert unversioned == [], f"以下 HTML session/bootstrap 未挂 cache-buster: {unversioned}"


# ===========================================================================
# T423 · SessionStoreReady Promise 就绪信号 (静态 + vm evaluate)
# ===========================================================================
def test_t423_session_store_ready_promise_declared():
    src = SESSION_BOOTSTRAP.read_text(encoding="utf-8")
    for keyword in [
        "SessionStore",
        "FrontRequestContext",
        "Can",
        "SessionStoreReady",
        "__sessionBootstrapped",
        "/static/js/shared/stores/sessionStore.js",
        "/static/js/shared/api-client/context.js",
        "/static/js/shared/api-client/interceptors.js",
        "/static/js/shared/components/Can/index.js",
    ]:
        assert keyword in src, f"session/bootstrap.js 缺关键字/URL: {keyword}"
    # vm evaluate:证明 SessionStoreReady 被赋值为 Promise-like
    node_script = r"""
        const fs = require('fs');
        const vm = require('vm');
        // 关键:async 步骤 (installInterceptors 等) 会 reject —— stub 返回空 module。
        // 但 SessionStoreReady 已赋值 · 我们只观测 Promise 存在性 · 不消费其结果。
        process.on('unhandledRejection', () => {});
        const path = %(path)s;
        const src = fs.readFileSync(path, 'utf-8');
        const sandbox = { window: {}, console };
        sandbox.globalThis = sandbox.window;
        sandbox.window.import = () => Promise.resolve({});
        const rewritten = src.replace(/\bimport\(/g, 'window.import(');
        vm.createContext(sandbox);
        vm.runInContext(rewritten, sandbox, { filename: path });
        const w = sandbox.window;
        process.stdout.write(JSON.stringify({
            hasReady: !!w.SessionStoreReady,
            readyType: typeof w.SessionStoreReady?.then,
            singleflight: !!w.__sessionBootstrapped,
        }));
    """ % {"path": json.dumps(str(SESSION_BOOTSTRAP))}
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=ROOT, check=False, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    # 允许非零退出:async rejection (installInterceptors stub) 会异步 raise,
    # 但 SessionStoreReady 的赋值已同步完成 · stdout 已写入 · 观测有效。
    out = completed.stdout.strip().splitlines()
    assert out, (
        f"vm bootstrap 未产生 stdout · rc={completed.returncode} · stderr={completed.stderr!r}"
    )
    result = json.loads(out[-1])
    assert result["hasReady"] is True
    assert result["readyType"] == "function", "SessionStoreReady 必须 Promise-like"
    assert result["singleflight"] is True


# ===========================================================================
# T424 · X-Client-Id 通过 interceptors 注入 · legacy 后端不强制 (仅前端契约)
# ===========================================================================
def test_t424_x_client_id_injected_when_set_but_optional():
    script = f"""
        import {{ defaultRequestInterceptor }} from {json.dumps(INTERCEPTORS)};
        // 场景 A:clientId 已填 → 应注入 X-Client-Id
        const storeWithClient = {{
            state: {{ clientId: 'device-42', workspaceId: null, projectId: null, requestId: null, authMode: 'anonymous_or_legacy', legacyUserKey: null }},
        }};
        const withClient = defaultRequestInterceptor({{ headers: {{}} }}, storeWithClient);
        // 场景 B:clientId 空 → 不产生空 X-Client-Id
        const storeNoClient = {{
            state: {{ clientId: null, workspaceId: null, projectId: null, requestId: null, authMode: 'anonymous_or_legacy', legacyUserKey: null }},
        }};
        const noClient = defaultRequestInterceptor({{ headers: {{}} }}, storeNoClient);
        console.log(JSON.stringify({{
            withClient: withClient.headers,
            noClient: noClient.headers,
        }}));
    """
    result = _run_node_esm(script)
    with_ci = {k.lower(): v for k, v in result["withClient"].items()}
    assert with_ci.get("x-client-id") == "device-42", "clientId 已填 · 应注入 header"
    no_ci = {k.lower(): v for k, v in result["noClient"].items()}
    assert "x-client-id" not in no_ci, "clientId 空 · 不应产生空 header (legacy 后端不强制)"


# ===========================================================================
# T425 · 服务端未上线场景 · Can 组件不阻断任何 UI · 全量 22 项烟测手动断言
# ===========================================================================
def test_t425_server_not_deployed_ui_never_blocked():
    """22 个动作在 capabilities 未上线场景下 · 全部透明放行 · 不阻断任何 UI 元素."""
    fetch_stub = _fetch_stub_prelude({"kind": "404"})  # 权限 PR-3 未上线
    script = f"""
        {fetch_stub}
        const {{ sessionStore, hasCapability }} = await import({json.dumps(SESSION_STORE)});
        const Can = (await import({json.dumps(CAN)})).default;
        // Refresh (会 404 降级 · 全 true)
        await sessionStore.refetch('t425');
        const actions = [
            'canvas.edit', 'canvas.delete', 'canvas.share', 'canvas.rename',
            'provider.edit', 'provider.delete', 'provider.create', 'provider.disable',
            'workflow.edit', 'workflow.overwrite', 'workflow.delete', 'workflow.upload',
            'asset.delete', 'asset.rename', 'asset.share',
            'node.delete', 'node.duplicate',
            'admin.reset', 'admin.audit-log',
            'unregistered.a', 'unregistered.b', 'unregistered.c',
        ];
        function makeEl(action) {{
            return {{
                style: {{ display: '' }},
                _attrs: {{ 'data-can': action }},
                setAttribute(k,v){{ this._attrs[k]=String(v); }},
                getAttribute(k){{ return this._attrs[k] == null ? null : String(this._attrs[k]); }},
                removeAttribute(k){{ delete this._attrs[k]; }},
            }};
        }}
        const rows = actions.map((a) => {{
            const el = makeEl(a);
            Can.mount(el, sessionStore, a);
            return {{
                action: a,
                display: el.style.display,
                hidden: el._attrs['data-can-hidden'] || null,
                capValue: hasCapability(sessionStore.state.capabilities, a),
            }};
        }});
        console.log(JSON.stringify({{ rows, count: rows.length }}));
    """
    result = _run_node_esm(script)
    assert result["count"] == 22, "全量断言应覆盖 22 个动作"
    # 硬断言:所有 22 个动作均可见 · hasCapability 全 true (无阻断)
    blocked = [r for r in result["rows"] if r["display"] == "none" or r["hidden"] == "1"]
    assert blocked == [], (
        f"权限未上线场景 · Can 组件应透明放行所有动作 · 阻断:{blocked}"
    )
    all_true = [r for r in result["rows"] if r["capValue"] is not True]
    assert all_true == [], (
        f"hasCapability 全 true 契约破裂 · 非 true:{all_true}"
    )
