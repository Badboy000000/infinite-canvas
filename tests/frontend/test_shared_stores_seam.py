"""Frontend PR-5: shared/stores seam tests.

Uses `node --experimental-default-type=module` to run assertion scripts against
the native ES modules on disk. Follows the pattern established by
`test_media_editor_seam.py` (前端 PR-4) and `test_shared_messaging_storage.py`
(前端 PR-3).

Baseline (Wave 3-B closing): 411 passed / 35 skipped. This module adds
`test_shared_stores_seam.py` and increases the total by its own count.
"""
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

CREATE_STORE = (ROOT / "static/js/shared/stores/_createStore.js").as_uri()
PROVIDERS = (ROOT / "static/js/shared/stores/providersStore.js").as_uri()
WORKFLOWS = (ROOT / "static/js/shared/stores/workflowsStore.js").as_uri()
CONFIG = (ROOT / "static/js/shared/stores/configStore.js").as_uri()
CANVAS_META = (ROOT / "static/js/shared/stores/canvasMetaStore.js").as_uri()
ASSET_LIBRARY = (ROOT / "static/js/shared/stores/assetLibraryStore.js").as_uri()
PROMPT = (ROOT / "static/js/shared/stores/promptStore.js").as_uri()
STORES_INDEX = (ROOT / "static/js/shared/stores/index.js").as_uri()
BOOTSTRAP = ROOT / "static/js/shared/stores/bootstrap.js"


HTML_PAGES = (
    "static/canvas.html",
    "static/smart-canvas.html",
    "static/api-settings.html",
    "static/comfyui-settings.html",
    "static/canvas-list.html",
    "static/asset-manager.html",
)


def run_node(script: str) -> dict:
    completed = subprocess.run(
        ["node", "--experimental-default-type=module", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return json.loads(completed.stdout)


# -------------------------------------------------------------------------
# _createStore 单元
# -------------------------------------------------------------------------

def test_create_store_revision_monotone_and_subscribe_unsubscribe():
    result = run_node(
        f"""
        import {{ createStore }} from {json.dumps(CREATE_STORE)};
        const store = createStore({{ name:'demo', initialState:{{ n:0 }} }});
        const calls = [];
        const un = store.subscribe((s, r, reason) => calls.push({{ r, reason, n:s.n }}));
        const r0 = store.revision;
        store.setState({{ n:1 }}, 'inc');
        store.setState({{ n:2 }}, 'inc');
        store.invalidate('bust');
        const r1 = store.revision;
        un();
        store.setState({{ n:99 }}, 'after-unsub');
        console.log(JSON.stringify({{ r0, r1, calls, revisionFinal: store.revision, stateFinal: store.state }}));
        """
    )
    assert result["r0"] == 0
    assert result["r1"] == 3  # 2 setState + 1 invalidate
    assert result["revisionFinal"] == 4  # +1 after unsub
    # Only 3 calls before unsubscribe
    assert len(result["calls"]) == 3
    assert [c["reason"] for c in result["calls"]] == ["inc", "inc", "bust"]
    assert result["calls"][0]["n"] == 1
    assert result["calls"][1]["n"] == 2
    assert result["calls"][2]["n"] == 2  # invalidate did not patch state
    assert result["stateFinal"]["n"] == 99


def test_create_store_refetch_idempotent_same_flight():
    """两次同时调用 refetch() 复用同一 flight（in-flight promise）。"""
    result = run_node(
        f"""
        import {{ createStore }} from {json.dumps(CREATE_STORE)};
        let calls = 0;
        const store = createStore({{
          name:'demo',
          initialState:{{ n:0 }},
          fetcher: async () => {{ calls += 1; await new Promise(r => setTimeout(r, 30)); return {{ n: calls }}; }},
        }});
        // 三个同步启动的 refetch 只应触发 fetcher 一次（in-flight 复用）
        const p1 = store.refetch();
        const p2 = store.refetch();
        const p3 = store.refetch();
        // 断言：p1 === p2 === p3（同一 Promise 实例）
        const sameRef = (p1 === p2 && p2 === p3);
        const [a, b, c] = await Promise.all([p1, p2, p3]);
        // 立即快照第一波 fetch 结果（state 是可变对象，之后再 refetch 会 mutate）
        const nAfterFirst = store.state.n;
        const callsAfterFirst = calls;
        // 结束后再次 refetch → 第二次调用
        await store.refetch();
        const nAfterSecond = store.state.n;
        console.log(JSON.stringify({{
          sameRef, calls, callsAfterFirst, nAfterFirst, nAfterSecond,
          revision: store.revision,
        }}));
        """
    )
    # in-flight 复用：三个 refetch 返回同一 Promise 实例
    assert result["sameRef"] is True
    # 第一波结束后 fetcher 只被调 1 次；state.n = 1
    assert result["callsAfterFirst"] == 1
    assert result["nAfterFirst"] == 1
    # 第二波 fetch 独立触发 → calls = 2；state.n = 2
    assert result["calls"] == 2
    assert result["nAfterSecond"] == 2
    # 一次 fetch 对应一次 revision bump
    assert result["revision"] == 2


# -------------------------------------------------------------------------
# providersStore — 凭据不落 store（P0 硬约束）
# -------------------------------------------------------------------------

def test_providers_store_credential_never_persisted():
    """P0：Provider 凭据字段永不进入 providersStore.state；抗回归 grep=0。"""
    result = run_node(
        f"""
        import {{ providersStore, sanitizeProvider, findCredentialLeaks, credentialSafe }} from {json.dumps(PROVIDERS)};
        // 手工塞一份"污染的" provider 列表（模拟后端回归带上原始凭据）
        const dirty = [
          {{ id:'p1', name:'P1', enabled:true,
             api_key:'sk-shouldnotpersist',
             key_env:'P1_API_KEY',
             has_key:true,
             key_preview:'sk-...abcd' }},
          {{ id:'volcengine', name:'Volc',
             volcengine_access_key:'AKIAxxxxx',
             volcengine_secret_key:'SECRETxxx',
             has_volcengine_access_key:true }},
          {{ id:'runninghub', wallet_key:'wallet-should-not-persist', has_wallet_key:true }},
        ];
        // sanitizeProvider 应剔除四个禁字段（值非空时）
        const cleaned = dirty.map(sanitizeProvider);
        // 直接 setState —— providersStore.setState 不走 sanitize；我们必须在 fetcher 里 sanitize，
        // 因此这里"故意"绕开 fetcher 塞入脏数据，验证 findCredentialLeaks 能定位泄漏。
        providersStore.setState({{ providers: dirty }}, 'test-dirty');
        const leaksDirty = findCredentialLeaks(providersStore.state, '$state');
        const safeDirty = credentialSafe(providersStore);
        // 现在用 sanitize 后的数据 setState —— 应无泄漏
        providersStore.setState({{ providers: cleaned }}, 'test-clean');
        const leaksClean = findCredentialLeaks(providersStore.state, '$state');
        const safeClean = credentialSafe(providersStore);
        // 元数据字段 (has_key / key_env / key_preview) 仍保留
        const stillHasMetadata = providersStore.state.providers[0].has_key === true
                              && providersStore.state.providers[0].key_env === 'P1_API_KEY'
                              && providersStore.state.providers[0].key_preview === 'sk-...abcd';
        console.log(JSON.stringify({{
          leaksDirty, safeDirty, leaksClean, safeClean, stillHasMetadata,
          cleanedFirstKeys: Object.keys(cleaned[0]).sort(),
        }}));
        """
    )
    # 脏数据应命中 4 处泄漏（api_key + volcengine_access_key + volcengine_secret_key + wallet_key）
    assert len(result["leaksDirty"]) == 4
    assert result["safeDirty"] is False
    # 清洗后 grep=0
    assert result["leaksClean"] == []
    assert result["safeClean"] is True
    assert result["stillHasMetadata"] is True
    # 清洗后的 provider 不再含 api_key
    assert "api_key" not in result["cleanedFirstKeys"]
    # 但保留元数据
    assert "has_key" in result["cleanedFirstKeys"]
    assert "key_env" in result["cleanedFirstKeys"]
    assert "key_preview" in result["cleanedFirstKeys"]


def test_providers_store_source_file_bans_credential_field_names():
    """静态源码断言：`providersStore.state` 初始化不含凭据字段名。"""
    src = (ROOT / "static/js/shared/stores/providersStore.js").read_text(encoding="utf-8")
    # initialState 只应含 `providers: []`（没有 api_key / wallet_key 等）
    # 我们只检查这几个字段名不作为 initialState key 出现
    # FORBIDDEN 字段应仅出现在字符串常量 / 注释里
    assert "initialState: { providers: [] }" in src


# -------------------------------------------------------------------------
# workflowsStore — 三类 workflow 互不污染 revision
# -------------------------------------------------------------------------

def test_workflows_store_three_kinds_isolated():
    """三 kind 的 revision 独立；一次 comfy invalidate 不推高 runninghub / canvasSubgraph 的 revision。"""
    result = run_node(
        f"""
        import {{ workflowsStore, WORKFLOW_KINDS }} from {json.dumps(WORKFLOWS)};
        const before = {{
          comfy: workflowsStore.comfy.revision,
          rh: workflowsStore.runninghub.revision,
          cs: workflowsStore.canvasSubgraph.revision,
          top: workflowsStore.revision,
        }};
        workflowsStore.comfy.setState({{ workflows:[{{name:'a.json'}}] }}, 'test');
        const afterComfy = {{
          comfy: workflowsStore.comfy.revision,
          rh: workflowsStore.runninghub.revision,
          cs: workflowsStore.canvasSubgraph.revision,
          top: workflowsStore.revision,
        }};
        workflowsStore.runninghub.setState({{ list:['w1'] }}, 'test');
        const afterRh = {{
          comfy: workflowsStore.comfy.revision,
          rh: workflowsStore.runninghub.revision,
          cs: workflowsStore.canvasSubgraph.revision,
          top: workflowsStore.revision,
        }};
        console.log(JSON.stringify({{ kinds: WORKFLOW_KINDS, before, afterComfy, afterRh }}));
        """
    )
    assert result["kinds"] == ["comfy", "runninghub", "canvasSubgraph"]
    # comfy 单独 bump：comfy +1，rh / cs 不变
    assert result["afterComfy"]["comfy"] == result["before"]["comfy"] + 1
    assert result["afterComfy"]["rh"] == result["before"]["rh"]
    assert result["afterComfy"]["cs"] == result["before"]["cs"]
    assert result["afterComfy"]["top"] == result["before"]["top"] + 1
    # 之后 rh 再 bump：rh +1，comfy 不变
    assert result["afterRh"]["rh"] == result["afterComfy"]["rh"] + 1
    assert result["afterRh"]["comfy"] == result["afterComfy"]["comfy"]


def test_workflows_store_subscribe_dispatches_per_kind():
    """subscribe 回调 payload 包含 kind 字段，方便订阅方按需过滤。"""
    result = run_node(
        f"""
        import {{ workflowsStore }} from {json.dumps(WORKFLOWS)};
        const events = [];
        const un = workflowsStore.subscribe(evt => events.push({{ kind: evt.kind, reason: evt.reason }}));
        workflowsStore.comfy.setState({{ workflows:[] }}, 'r1');
        workflowsStore.runninghub.invalidate('rh-refresh');
        workflowsStore.canvasSubgraph.invalidate('cs-refresh');
        un();
        console.log(JSON.stringify({{ events }}));
        """
    )
    kinds = [e["kind"] for e in result["events"]]
    assert kinds == ["comfy", "runninghub", "canvasSubgraph"]


# -------------------------------------------------------------------------
# configStore — `broadcastStudioApiChange` 函数名保留 wrapper
# -------------------------------------------------------------------------

def test_config_store_preserves_broadcast_studio_api_change_name():
    """compat-contract §6 冻结：`broadcastStudioApiChange` 函数名必须保留。"""
    result = run_node(
        f"""
        import * as mod from {json.dumps(CONFIG)};
        const hasFn = typeof mod.broadcastStudioApiChange === 'function';
        // stub BroadcastChannel
        let posted = null;
        globalThis.BroadcastChannel = class {{
          constructor(name) {{ this.name = name; }}
          postMessage(msg) {{ posted = {{ channel:this.name, msg }}; }}
          close() {{}}
        }};
        const msg = mod.broadcastStudioApiChange('providers-changed');
        console.log(JSON.stringify({{
          hasFn,
          broadcastTypes: mod.CONFIG_BROADCAST_TYPES,
          posted,
          msg,
        }}));
        """
    )
    assert result["hasFn"] is True
    assert result["broadcastTypes"] == ["providers-changed", "workflows-changed", "comfy-instances-changed"]
    assert result["posted"]["channel"] == "studio-api"
    assert result["posted"]["msg"]["type"] == "providers-changed"
    assert isinstance(result["posted"]["msg"]["updated_at"], int)
    assert result["msg"]["type"] == "providers-changed"


# -------------------------------------------------------------------------
# canvasMetaStore
# -------------------------------------------------------------------------

def test_canvas_meta_store_only_stores_whitelisted_fields():
    """canvasMeta 只保留元数据字段；nodes / connections / viewport 被丢弃。"""
    result = run_node(
        f"""
        import {{ canvasMetaStore, upsertCanvasMeta, CANVAS_META_FIELDS }} from {json.dumps(CANVAS_META)};
        upsertCanvasMeta({{
          id:'c1', title:'Hello', icon:'🧩', pinned:true, color:'red', owner:'me',
          updated_at:100, base_updated_at:99,
          // 以下字段应被剔除
          nodes:[{{id:'n1'}}], connections:[], viewport:{{x:0,y:0}},
        }});
        console.log(JSON.stringify({{
          fields: CANVAS_META_FIELDS,
          meta: canvasMetaStore.state.byId.c1,
        }}));
        """
    )
    assert "nodes" not in result["meta"]
    assert "connections" not in result["meta"]
    assert "viewport" not in result["meta"]
    assert result["meta"]["title"] == "Hello"
    assert result["meta"]["base_updated_at"] == 99


# -------------------------------------------------------------------------
# assetLibraryStore
# -------------------------------------------------------------------------

def test_asset_library_store_snapshot_and_active_id():
    result = run_node(
        f"""
        import {{ assetLibraryStore, applyAssetLibrarySnapshot }} from {json.dumps(ASSET_LIBRARY)};
        applyAssetLibrarySnapshot({{
          library:{{ libraries:[{{id:'lib1', name:'Lib 1'}}], categories:[] }},
          asset_library:{{ id:'lib1' }},
          updated_at: 1234,
        }});
        console.log(JSON.stringify({{
          library: assetLibraryStore.state.library,
          active: assetLibraryStore.state.active_library_id,
          updatedAt: assetLibraryStore.state.updated_at,
        }}));
        """
    )
    assert result["library"]["libraries"][0]["id"] == "lib1"
    assert result["active"] == "lib1"
    assert result["updatedAt"] == 1234


# -------------------------------------------------------------------------
# promptStore — 读五 key，但不合并 key 本身
# -------------------------------------------------------------------------

def test_prompt_store_reads_five_legacy_keys_but_does_not_merge_keys():
    """promptStore 内部读五个 legacy localStorage key；五 key 未被改写、未被合并。"""
    result = run_node(
        f"""
        // 手工 stub localStorage
        const store = {{}};
        globalThis.localStorage = {{
          getItem(k) {{ return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; }},
          setItem(k, v) {{ store[k] = String(v); }},
          removeItem(k) {{ delete store[k]; }},
        }};
        // 写入五个 legacy key
        localStorage.setItem('canvas_prompt_template_groups_v1', JSON.stringify([{{name:'g1'}}]));
        localStorage.setItem('canvas_prompt_template_overrides', JSON.stringify({{'a':1}}));
        localStorage.setItem('smart_canvas_prompt_presets_v1', JSON.stringify([{{id:'p1'}}]));
        localStorage.setItem('smart_canvas_prompt_template_groups_v1', JSON.stringify([{{name:'sg1'}}]));
        localStorage.setItem('smart_canvas_prompt_template_overrides_v1', JSON.stringify({{'b':2}}));
        const {{ promptStore, readLegacyPromptSnapshot, refreshPromptSnapshot, PROMPT_LEGACY_KEYS }} = await import({json.dumps(PROMPT)});
        // 首次读取应把五 key 数据全 merge 到 state 的两个命名空间下
        refreshPromptSnapshot('test-init');
        const snapshot = promptStore.state;
        // 断言五 key 在 localStorage 中还完整存在（key 名未被改写、未被合并成一个大 key）
        const legacyKeys = {{
          [PROMPT_LEGACY_KEYS.canvasTemplateGroups]: localStorage.getItem(PROMPT_LEGACY_KEYS.canvasTemplateGroups),
          [PROMPT_LEGACY_KEYS.canvasTemplateOverrides]: localStorage.getItem(PROMPT_LEGACY_KEYS.canvasTemplateOverrides),
          [PROMPT_LEGACY_KEYS.smartPresets]: localStorage.getItem(PROMPT_LEGACY_KEYS.smartPresets),
          [PROMPT_LEGACY_KEYS.smartTemplateGroups]: localStorage.getItem(PROMPT_LEGACY_KEYS.smartTemplateGroups),
          [PROMPT_LEGACY_KEYS.smartTemplateOverrides]: localStorage.getItem(PROMPT_LEGACY_KEYS.smartTemplateOverrides),
        }};
        // 断言 store 没有合并出新 key —— snapshot 只有 canvas / smart 两个命名空间投影
        const snapshotTopKeys = Object.keys(snapshot).sort();
        console.log(JSON.stringify({{ snapshot, legacyKeys, snapshotTopKeys, PROMPT_LEGACY_KEYS }}));
        """
    )
    # 五 key 的原始 JSON 全部保留（key 名不合并；shape 不改）
    keys = result["legacyKeys"]
    assert keys["canvas_prompt_template_groups_v1"] == '[{"name":"g1"}]'
    assert keys["canvas_prompt_template_overrides"] == '{"a":1}'
    assert keys["smart_canvas_prompt_presets_v1"] == '[{"id":"p1"}]'
    assert keys["smart_canvas_prompt_template_groups_v1"] == '[{"name":"sg1"}]'
    assert keys["smart_canvas_prompt_template_overrides_v1"] == '{"b":2}'
    # store 内部只做两个命名空间的合并读取投影
    assert result["snapshotTopKeys"] == ["canvas", "smart"]
    # 值透传到 state 命名空间
    assert result["snapshot"]["canvas"]["templateGroups"][0]["name"] == "g1"
    assert result["snapshot"]["smart"]["presets"][0]["id"] == "p1"
    # PROMPT_LEGACY_KEYS 常量表覆盖五 key
    assert set(result["PROMPT_LEGACY_KEYS"].values()) == {
        "canvas_prompt_template_groups_v1",
        "canvas_prompt_template_overrides",
        "smart_canvas_prompt_presets_v1",
        "smart_canvas_prompt_template_groups_v1",
        "smart_canvas_prompt_template_overrides_v1",
    }


# -------------------------------------------------------------------------
# index re-exports + bootstrap
# -------------------------------------------------------------------------

def test_stores_index_reexports_six_stores():
    result = run_node(
        f"""
        import * as mod from {json.dumps(STORES_INDEX)};
        console.log(JSON.stringify({{
          providers: typeof mod.providersStore,
          workflows: typeof mod.workflowsStore,
          config: typeof mod.configStore,
          canvasMeta: typeof mod.canvasMetaStore,
          assetLibrary: typeof mod.assetLibraryStore,
          prompt: typeof mod.promptStore,
          broadcast: typeof mod.broadcastStudioApiChange,
          createStore: typeof mod.createStore,
          sanitizeProvider: typeof mod.sanitizeProvider,
        }}));
        """
    )
    for k in ("providers", "workflows", "config", "canvasMeta", "assetLibrary", "prompt"):
        assert result[k] == "object"
    assert result["broadcast"] == "function"
    assert result["createStore"] == "function"
    assert result["sanitizeProvider"] == "function"


def test_stores_bootstrap_is_module_free_and_installs_window_globals():
    """bootstrap.js 是 IIFE 非模块脚本；通过动态 import 装配 window.stores 六件套。"""
    assert BOOTSTRAP.exists(), "shared/stores/bootstrap.js 缺失"
    text = BOOTSTRAP.read_text(encoding="utf-8")
    # 非模块（IIFE）；不能出现顶层 import / export
    assert "\nimport " not in "\n" + text, "bootstrap.js 不应包含顶层 import"
    assert "\nexport " not in "\n" + text, "bootstrap.js 不应包含 export"
    # 六 store + broadcast wrapper 必须挂上
    assert "global.stores" in text, "bootstrap.js 未使用 global.stores 装配 window 全局"
    for key in ("providers", "workflows", "config", "canvasMeta", "assetLibrary", "prompt"):
        assert key in text, f"bootstrap.js 缺少 window.stores.{key}"
    assert "broadcastStudioApiChange" in text
    # 动态 ESM import 指向本 PR 落地的 index 模块
    assert "/static/js/shared/stores/index.js" in text
    # StoresReady 与 messaging bus 绑定
    assert "StoresReady" in text
    assert "StudioMessaging" in text


def test_stores_bootstrap_included_in_six_html_pages():
    """6 页 HTML 都必须引 shared/stores/bootstrap.js。"""
    missing = []
    for html in HTML_PAGES:
        content = (ROOT / html).read_text(encoding="utf-8")
        if "/static/js/shared/stores/bootstrap.js" not in content:
            missing.append(html)
    assert missing == [], f"以下页面未引入 stores bootstrap：{missing}"


# -------------------------------------------------------------------------
# canvas.js / smart-canvas.js / asset-manager.js 顶层变量 wrapper 兼容
# -------------------------------------------------------------------------

def test_top_level_variable_wrappers_defined_property_uses_store_snapshots():
    """canvas.js / smart-canvas.js / asset-manager.js 的顶层 `apiProviders`
    / `comfyWorkflows` / `assetLibrary` 已 wrapper 化为 `Object.defineProperty`
    的 getter，其读取路径投影到 `window.stores.*.state`。"""
    tests = [
        ("static/js/canvas.js", ["'apiProviders'", "'comfyWorkflows'", "stores?.providers?.state", "stores?.workflows?.comfy?.state"]),
        ("static/js/smart-canvas.js", ["'apiProviders'", "'comfyWorkflows'", "'assetLibrary'", "stores?.providers?.state", "stores?.workflows?.comfy?.state", "stores?.assetLibrary?.state"]),
        ("static/js/asset-manager.js", ["'apiProviders'", "'assetLibrary'", "stores?.providers?.state", "stores?.assetLibrary?.state"]),
    ]
    for path, must_have in tests:
        src = (ROOT / path).read_text(encoding="utf-8")
        assert "Object.defineProperty(globalThis" in src, f"{path} 未使用 Object.defineProperty wrapper"
        for token in must_have:
            assert token in src, f"{path} 缺少 wrapper 标记 {token}"


def test_canvas_and_smart_canvas_no_bare_let_apiproviders():
    """canvas.js / smart-canvas.js 不再存在 `let apiProviders = [];` 顶层裸声明
    （已改为 defineProperty wrapper）。"""
    for path in ("static/js/canvas.js", "static/js/smart-canvas.js", "static/js/asset-manager.js"):
        src = (ROOT / path).read_text(encoding="utf-8")
        # 保证没有 legacy 顶层裸声明（避免 wrapper 被"影子"变量覆盖）
        assert "\nlet apiProviders = [];" not in "\n" + src, f"{path} 仍有裸 let apiProviders = []"


def test_canvas_and_smart_canvas_function_body_reference_points_preserved():
    """硬门槛 5：canvas.js / smart-canvas.js 函数体 6+ 处引用点保持不变。"""
    canvas_src = (ROOT / "static/js/canvas.js").read_text(encoding="utf-8")
    smart_src = (ROOT / "static/js/smart-canvas.js").read_text(encoding="utf-8")
    # canvas.js 的经典引用点（compat-contract 与 PR-4 前的 grep 事实一致）
    assert canvas_src.count("apiProviders.find(p => p.id === providerId)") >= 3
    assert canvas_src.count("apiProviders.length ? apiProviders") >= 3
    assert canvas_src.count("comfyWorkflows[0]?.name") >= 3
    # smart-canvas 引用点
    assert smart_src.count("(apiProviders || [])") >= 6
    assert smart_src.count("comfyWorkflows") >= 5
