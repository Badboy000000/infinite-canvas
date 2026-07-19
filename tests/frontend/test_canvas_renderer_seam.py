"""Frontend PR-6: modules/canvas renderer + interactions + canvasEditStore seam tests.

Uses `node --experimental-default-type=module` to run assertion scripts against
the native ES modules on disk. Follows the pattern established by
`test_shared_stores_seam.py` (前端 PR-5) and `test_media_editor_seam.py` (前端 PR-4).

Baseline (Wave 3-G closing): 549 passed / 35 skipped. This module adds
`test_canvas_renderer_seam.py` and increases the total by its own count.

Covers:
    T1  renderer 模块 import 无副作用
    T2  viewport.js 语义快照 + pickViewportForStorage 契约
    T3  connections.js 两 SVG 图层分层契约 + 落盘 shape 冻结
    T4  hitTest.js 命中测试基准 + rectsIntersect / pointInRect 纯函数
    T5  render-loop.js 单 rAF 主循环单例 + request 合并
    T6  render-loop.js pause('media-editor') / resume('media-editor') 竞态测试
    T7  Drag session 互斥表：dragNode 期间 tempLink start 被拒
    T8  Drag session 互斥表：portDragState 结束态僵尸检出（endAll）
    T9  canvasEditStore 6 字段初始态 + snapshot 契约
    T10 canvasEditStore.save() 409 两种 shape 兼容读
    T11 canvasEditStore.save() client_id === CLIENT_ID 自我识别
    T12 canvasEditStore.save() base_updated_at 递增校验
    T13 _renderPatchToken 清理清单：canvas.js / smart-canvas.js 内 grep 抗回归
    T14 should-skip.js 语义等价 touch-mouse.js skip 规则（快照对比）
    T15 canvasEditStore.applyRemoteUpdate 语义等价 handleCanvasUpdatedMessage
    T16 wheel-zoom.js 两画布策略描述冻结 + 纯函数 factor
    T17 marquee.js 纯函数正规化 + 命中集合
    T18 hotkey.js normalizeCombo + register/dispatch
    T19 focus.js shouldSuppressHotkey 语义
    T20 canvasEditStore save() applyingRemoteCanvas 入口守卫
"""
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

VIEWPORT = (ROOT / "static/js/modules/canvas/renderer/viewport.js").as_uri()
CONNECTIONS = (ROOT / "static/js/modules/canvas/renderer/connections.js").as_uri()
NODES_LAYER = (ROOT / "static/js/modules/canvas/renderer/nodesLayer.js").as_uri()
HIT_TEST = (ROOT / "static/js/modules/canvas/renderer/hitTest.js").as_uri()
RENDER_LOOP = (ROOT / "static/js/modules/canvas/renderer/render-loop.js").as_uri()
POINTER = (ROOT / "static/js/modules/canvas/interactions/pointer.js").as_uri()
DRAG = (ROOT / "static/js/modules/canvas/interactions/drag.js").as_uri()
WHEEL_ZOOM = (ROOT / "static/js/modules/canvas/interactions/wheel-zoom.js").as_uri()
HOTKEY = (ROOT / "static/js/modules/canvas/interactions/hotkey.js").as_uri()
FOCUS = (ROOT / "static/js/modules/canvas/interactions/focus.js").as_uri()
MARQUEE = (ROOT / "static/js/modules/canvas/interactions/marquee.js").as_uri()
SHOULD_SKIP = (ROOT / "static/js/shared/interaction/pointer/should-skip.js").as_uri()
CANVAS_EDIT_STORE = (ROOT / "static/js/modules/canvas/store/canvasEditStore.js").as_uri()

CANVAS_JS = ROOT / "static/js/canvas.js"
SMART_CANVAS_JS = ROOT / "static/js/smart-canvas.js"
TOUCH_MOUSE = ROOT / "static/js/touch-mouse.js"


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
# T1. renderer 模块 import 无副作用
# -------------------------------------------------------------------------

def test_renderer_modules_import_pure():
    result = run_node(
        f"""
        import viewport from {json.dumps(VIEWPORT)};
        import connections from {json.dumps(CONNECTIONS)};
        import nodesLayer from {json.dumps(NODES_LAYER)};
        import hitTest from {json.dumps(HIT_TEST)};
        import renderLoop from {json.dumps(RENDER_LOOP)};
        console.log(JSON.stringify({{
          viewport: typeof viewport,
          connections: typeof connections,
          nodesLayer: typeof nodesLayer,
          hitTest: typeof hitTest,
          renderLoop: typeof renderLoop,
          renderLoopPaused: renderLoop.isPaused(),
          renderLoopPending: renderLoop.pendingCount(),
        }}));
        """
    )
    assert result["viewport"] == "object"
    assert result["connections"] == "object"
    assert result["nodesLayer"] == "object"
    assert result["hitTest"] == "object"
    assert result["renderLoop"] == "object"
    # import 后主循环应该处于空闲状态（没有 pending，没有 pause）
    assert result["renderLoopPaused"] is False
    assert result["renderLoopPending"] == 0


# -------------------------------------------------------------------------
# T2. viewport.js 语义快照
# -------------------------------------------------------------------------

def test_viewport_module_contract_and_pick_for_storage():
    result = run_node(
        f"""
        import mod from {json.dumps(VIEWPORT)};
        const kinds = [...mod.CANVAS_KINDS].sort();
        const fields = [...mod.VIEWPORT_STORAGE_FIELDS];
        const picked1 = mod.pickViewportForStorage({{x:100, y:200, scale:1.5, __extra:'no'}});
        const picked2 = mod.pickViewportForStorage(null);
        const picked3 = mod.pickViewportForStorage({{x:5, y:6}});
        const picked4 = mod.pickViewportForStorage({{x:0, y:0, scale:0}});
        console.log(JSON.stringify({{ kinds, fields, picked1, picked2, picked3, picked4 }}));
        """
    )
    assert result["kinds"] == ["classic", "smart"]
    assert result["fields"] == ["x", "y", "scale"]
    # extra 字段被剥离
    assert result["picked1"] == {"x": 100, "y": 200, "scale": 1.5}
    assert result["picked2"] == {"x": 0, "y": 0, "scale": 1}
    # scale 缺失回落到 1
    assert result["picked3"] == {"x": 5, "y": 6, "scale": 1}
    # scale <= 0 fall back to 1
    assert result["picked4"]["scale"] == 1


# -------------------------------------------------------------------------
# T3. connections.js 两 SVG 图层分层 + 落盘 shape
# -------------------------------------------------------------------------

def test_connections_module_layers_and_shape_fields():
    result = run_node(
        f"""
        import mod from {json.dumps(CONNECTIONS)};
        // 使用一个假 canvasKind 保证独立于其他测试
        mod.registerConnectionsAdapter('test-classic', {{
          getStableLayer: () => ({{tag:'stable-layer'}}),
          getDraggingLayer: () => ({{tag:'dragging-layer'}}),
          renderConnections: () => 'ok',
        }});
        const stable = mod.getStableLayer('test-classic');
        const dragging = mod.getDraggingLayer('test-classic');
        const rendered = mod.renderConnections('test-classic');
        const classicOk = mod.validateConnectionShape('classic', {{id:'c1', from:'a', to:'b'}});
        const smartOk = mod.validateConnectionShape('smart', {{from:'a', to:'b', kind:'ctrl'}});
        const smartLoose = mod.validateConnectionShape('smart', {{from:'a', to:'b'}});
        const bad = mod.validateConnectionShape('classic', {{id:'c1', from:'a'}});
        console.log(JSON.stringify({{
          layers: [...mod.LAYER_KINDS],
          classicFields: [...mod.CLASSIC_CONNECTION_FIELDS],
          smartFields: [...mod.SMART_CONNECTION_FIELDS],
          stableTag: stable.tag,
          draggingTag: dragging.tag,
          layersDiffer: stable.tag !== dragging.tag,
          rendered,
          classicOk, smartOk, smartLoose, bad,
        }}));
        """
    )
    # 两 SVG 图层 kind 冻结
    assert result["layers"] == ["stable", "dragging"]
    # 落盘 shape 字段冻结
    assert result["classicFields"] == ["id", "from", "to"]
    assert result["smartFields"] == ["from", "to", "kind"]
    # 两图层实体不同（分层证据）
    assert result["stableTag"] == "stable-layer"
    assert result["draggingTag"] == "dragging-layer"
    assert result["layersDiffer"] is True
    assert result["rendered"] == "ok"
    # shape 校验
    assert result["classicOk"] is True
    assert result["smartOk"] is True
    assert result["smartLoose"] is True  # kind 可选
    assert result["bad"] is False


# -------------------------------------------------------------------------
# T4. hitTest.js 命中测试基准
# -------------------------------------------------------------------------

def test_hit_test_pure_functions_intersect_and_point_in_rect():
    result = run_node(
        f"""
        import mod from {json.dumps(HIT_TEST)};
        const r1 = {{x:0, y:0, width:10, height:10}};
        const r2 = {{x:5, y:5, width:10, height:10}};
        const r3 = {{x:100, y:100, width:5, height:5}};
        console.log(JSON.stringify({{
          intersect12: mod.rectsIntersect(r1, r2),
          intersect13: mod.rectsIntersect(r1, r3),
          pointIn: mod.pointInRect({{x:3, y:3}}, r1),
          pointOut: mod.pointInRect({{x:100, y:100}}, r1),
          targets: [...mod.HIT_TARGETS].sort(),
        }}));
        """
    )
    assert result["intersect12"] is True
    assert result["intersect13"] is False
    assert result["pointIn"] is True
    assert result["pointOut"] is False
    assert result["targets"] == sorted(["node", "port", "link", "blank", "handle", "unknown"])


# -------------------------------------------------------------------------
# T5. render-loop.js 单 rAF 主循环 + request 合并
# -------------------------------------------------------------------------

def test_render_loop_singleton_batches_multiple_requests():
    result = run_node(
        f"""
        import {{ renderLoop }} from {json.dumps(RENDER_LOOP)};
        renderLoop._resetForTests();
        // 记录 flush 次数与 callback 命中次数
        let cbHits = 0;
        renderLoop.request(() => {{ cbHits += 1; }});
        renderLoop.request(() => {{ cbHits += 1; }});
        renderLoop.request(() => {{ cbHits += 1; }});
        const pendingBefore = renderLoop.pendingCount();
        renderLoop._flushSync();
        const pendingAfter = renderLoop.pendingCount();
        // 同一 tick 内 3 次 request 合并为一次 flush，callback 均执行一次
        console.log(JSON.stringify({{ cbHits, pendingBefore, pendingAfter }}));
        """
    )
    assert result["cbHits"] == 3
    assert result["pendingBefore"] == 3
    assert result["pendingAfter"] == 0


# -------------------------------------------------------------------------
# T6. render-loop.js pause('media-editor') / resume 竞态测试（承接前端 PR-4 F-2）
# -------------------------------------------------------------------------

def test_render_loop_pause_media_editor_suspends_callbacks():
    result = run_node(
        f"""
        import {{ renderLoop }} from {json.dumps(RENDER_LOOP)};
        renderLoop._resetForTests();
        let cbHits = 0;
        renderLoop.pause('media-editor');
        renderLoop.request(() => {{ cbHits += 1; }});
        renderLoop.request(() => {{ cbHits += 1; }});
        renderLoop._flushSync();
        const hitsWhilePaused = cbHits;
        const pausedSources = renderLoop.pauseSources();
        renderLoop.resume('media-editor');
        renderLoop._flushSync();
        const hitsAfterResume = cbHits;
        // 引用计数：pause 两次需 resume 两次
        renderLoop.pause('media-editor');
        renderLoop.pause('media-editor');
        renderLoop.resume('media-editor');
        const stillPaused = renderLoop.isPaused();
        renderLoop.resume('media-editor');
        const finallyIdle = renderLoop.isPaused();
        renderLoop._resetForTests();
        console.log(JSON.stringify({{
          hitsWhilePaused, hitsAfterResume, pausedSources, stillPaused, finallyIdle,
        }}));
        """
    )
    # 挂起期间 callback 不执行
    assert result["hitsWhilePaused"] == 0
    # resume 后 callback 补执行
    assert result["hitsAfterResume"] == 2
    # pauseSources 报告来源
    sources = [entry["source"] for entry in result["pausedSources"]]
    assert "media-editor" in sources
    # 引用计数：pause×2 + resume×1 仍然挂起
    assert result["stillPaused"] is True
    # pause×2 + resume×2 后回到 idle（isPaused()===False）
    assert result["finallyIdle"] is False
    # Note: `isPaused()` returns True while any source count>0; False = fully idle.


def test_render_loop_pause_reference_counting():
    result = run_node(
        f"""
        import {{ renderLoop }} from {json.dumps(RENDER_LOOP)};
        renderLoop._resetForTests();
        renderLoop.pause('media-editor');
        renderLoop.pause('media-editor');
        const after2Pauses = renderLoop.isPaused();
        renderLoop.resume('media-editor');
        const after1Resume = renderLoop.isPaused();
        renderLoop.resume('media-editor');
        const after2Resumes = renderLoop.isPaused();
        renderLoop._resetForTests();
        console.log(JSON.stringify({{ after2Pauses, after1Resume, after2Resumes }}));
        """
    )
    assert result["after2Pauses"] is True
    assert result["after1Resume"] is True
    assert result["after2Resumes"] is False


# -------------------------------------------------------------------------
# T7. Drag session 互斥表：dragNode 期间 tempLink start 被拒
# -------------------------------------------------------------------------

def test_drag_sessions_mutex_dragNode_blocks_tempLink():
    result = run_node(
        f"""
        import {{ dragSessions, DRAG_SESSION_KINDS, MUTEX_RULES }} from {json.dumps(DRAG)};
        dragSessions._resetForTests();
        const r1 = dragSessions.begin('dragNode', {{nodeId:'n1'}});
        const r2 = dragSessions.begin('tempLink', {{}});
        const r3 = dragSessions.begin('portDragState', {{}});
        const r4 = dragSessions.begin('connectionEraseState', {{}});
        const activeBefore = Object.keys(dragSessions.snapshot()).sort();
        dragSessions.end('dragNode', 'commit');
        const r5 = dragSessions.begin('tempLink', {{}});
        const activeAfter = Object.keys(dragSessions.snapshot()).sort();
        dragSessions._resetForTests();
        console.log(JSON.stringify({{
          kinds: [...DRAG_SESSION_KINDS].sort(),
          r1, r2, r3, r4, r5,
          activeBefore, activeAfter,
          mutexOfDragNode: MUTEX_RULES.dragNode,
        }}));
        """
    )
    assert result["kinds"] == sorted([
        "dragNode", "resizeNode", "tempLink", "llmPaneDrag",
        "portDragState", "selectionState", "connectionEraseState",
    ])
    assert result["r1"]["ok"] is True
    assert result["r2"]["ok"] is False
    assert result["r2"]["reason"] == "blocked-by:dragNode"
    assert result["r3"]["ok"] is False
    assert result["r4"]["ok"] is False
    assert result["activeBefore"] == ["dragNode"]
    # dragNode 结束后，tempLink 可开始
    assert result["r5"]["ok"] is True
    assert result["activeAfter"] == ["tempLink"]


# -------------------------------------------------------------------------
# T8. Drag session 互斥表：僵尸态检出（endAll）
# -------------------------------------------------------------------------

def test_drag_sessions_zombie_detection_and_end_all():
    result = run_node(
        f"""
        import {{ dragSessions }} from {json.dumps(DRAG)};
        dragSessions._resetForTests();
        dragSessions.begin('portDragState', {{}});
        // 模拟僵尸：portDragState 没有正常 end 就要求切换到 dragNode
        const blocked = dragSessions.begin('dragNode', {{}});
        const zombieList = dragSessions.endAll('zombie-cleanup');
        const activeAfter = dragSessions.snapshot();
        const after = dragSessions.begin('dragNode', {{}});
        dragSessions._resetForTests();
        console.log(JSON.stringify({{
          blocked, zombieList, activeAfter, after,
        }}));
        """
    )
    assert result["blocked"]["ok"] is False
    assert result["blocked"]["reason"] == "blocked-by:portDragState"
    assert result["zombieList"] == ["portDragState"]
    assert result["activeAfter"] == {}
    assert result["after"]["ok"] is True


# -------------------------------------------------------------------------
# T9. canvasEditStore 6 字段初始态
# -------------------------------------------------------------------------

def test_canvas_edit_store_initial_state_has_six_conflict_fields():
    result = run_node(
        f"""
        import {{ createCanvasEditStore, CANVAS_EDIT_CONFLICT_FIELDS }} from {json.dumps(CANVAS_EDIT_STORE)};
        const store = createCanvasEditStore({{ name:'classic', clientId:'c1' }});
        const snap = store.snapshot();
        const keys = Object.keys(snap).sort();
        console.log(JSON.stringify({{
          conflictFields: [...CANVAS_EDIT_CONFLICT_FIELDS].sort(),
          initial: {{
            serverSnapshot: snap.serverSnapshot,
            lastServerUpdatedAt: snap.lastServerUpdatedAt,
            localDirty: snap.localDirty,
            saveInFlight: snap.saveInFlight,
            pendingResave: snap.pendingResave,
            conflictResolution: snap.conflictResolution,
            applyingRemoteCanvas: snap.applyingRemoteCanvas,
          }},
          keys,
        }}));
        """
    )
    assert result["conflictFields"] == sorted([
        "serverSnapshot", "lastServerUpdatedAt", "localDirty",
        "saveInFlight", "pendingResave", "conflictResolution",
    ])
    assert result["initial"] == {
        "serverSnapshot": None,
        "lastServerUpdatedAt": 0,
        "localDirty": False,
        "saveInFlight": False,
        "pendingResave": False,
        "conflictResolution": "idle",
        "applyingRemoteCanvas": False,
    }
    # snapshot 必须包含 6 冲突字段 + viewport / selection / undoStack / applyingRemoteCanvas
    for k in [
        "serverSnapshot", "lastServerUpdatedAt", "localDirty", "saveInFlight",
        "pendingResave", "conflictResolution", "viewport", "selection",
        "undoStack", "applyingRemoteCanvas",
    ]:
        assert k in result["keys"], f"snapshot missing key {k}"


# -------------------------------------------------------------------------
# T10. canvasEditStore.save() 409 两种 shape 兼容读
# -------------------------------------------------------------------------

def test_canvas_edit_store_save_409_reads_both_shapes():
    result = run_node(
        f"""
        import {{ createCanvasEditStore, readConflictRemoteCanvas }} from {json.dumps(CANVAS_EDIT_STORE)};

        // shape A: data.detail.canvas
        const shapeA = {{ detail: {{ canvas: {{ id:'c1', updated_at: 111 }}, updated_at: 111 }} }};
        // shape B: data.canvas
        const shapeB = {{ canvas: {{ id:'c1', updated_at: 222 }}, updated_at: 222 }};
        // both shapes: prefer detail.canvas
        const both = {{
          canvas: {{ id:'x', updated_at: 333 }},
          detail: {{ canvas: {{ id:'preferred', updated_at: 333 }}, updated_at: 333 }},
        }};

        const readA = readConflictRemoteCanvas(shapeA);
        const readB = readConflictRemoteCanvas(shapeB);
        const readBoth = readConflictRemoteCanvas(both);

        // 集成测试：apply 逻辑
        const appliedA = [];
        const storeA = createCanvasEditStore({{
          name:'a', clientId:'c1',
          putCanvas: async () => ({{ status: 409, ok: false, json: async () => shapeA }}),
          buildPayload: () => ({{ client_id:'c1', base_updated_at: 0 }}),
          applyRemote: (r) => appliedA.push(r),
        }});
        const outA = await storeA.save();

        const appliedB = [];
        const storeB = createCanvasEditStore({{
          name:'b', clientId:'c1',
          putCanvas: async () => ({{ status: 409, ok: false, json: async () => shapeB }}),
          buildPayload: () => ({{ client_id:'c1', base_updated_at: 0 }}),
          applyRemote: (r) => appliedB.push(r),
        }});
        const outB = await storeB.save();

        console.log(JSON.stringify({{
          readA, readB, readBoth,
          outA, outB,
          appliedA, appliedB,
          serverSnapshotA: storeA.serverSnapshot,
          serverSnapshotB: storeB.serverSnapshot,
          lastAtA: storeA.lastServerUpdatedAt,
          lastAtB: storeB.lastServerUpdatedAt,
        }}));
        """
    )
    # 两种 shape 都被识别
    assert result["readA"] == {"id": "c1", "updated_at": 111}
    assert result["readB"] == {"id": "c1", "updated_at": 222}
    # 同时存在时优先 detail.canvas
    assert result["readBoth"] == {"id": "preferred", "updated_at": 333}
    # 集成：shape A 与 shape B 都成功 apply
    assert result["outA"]["conflict"] is True
    assert result["outB"]["conflict"] is True
    assert result["appliedA"] == [{"id": "c1", "updated_at": 111}]
    assert result["appliedB"] == [{"id": "c1", "updated_at": 222}]
    assert result["lastAtA"] == 111
    assert result["lastAtB"] == 222


# -------------------------------------------------------------------------
# T11. canvasEditStore.save() client_id === CLIENT_ID 自我识别
# -------------------------------------------------------------------------

def test_canvas_edit_store_apply_remote_update_self_identification():
    result = run_node(
        f"""
        import {{ createCanvasEditStore }} from {json.dumps(CANVAS_EDIT_STORE)};
        const store = createCanvasEditStore({{ name:'classic', clientId:'CANVAS_ABC' }});
        store.setLastServerUpdatedAt(100);

        const selfEvent = {{ type:'canvas_updated', client_id:'CANVAS_ABC', updated_at: 200 }};
        const otherEvent = {{ type:'canvas_updated', client_id:'CANVAS_XYZ', updated_at: 200 }};
        const staleEvent = {{ type:'canvas_updated', client_id:'CANVAS_XYZ', updated_at: 50 }};
        const equalEvent = {{ type:'canvas_updated', client_id:'CANVAS_XYZ', updated_at: 100 }};

        const rSelf = store.applyRemoteUpdate(selfEvent);
        const rOther = store.applyRemoteUpdate(otherEvent);
        const rStale = store.applyRemoteUpdate(staleEvent);
        const rEqual = store.applyRemoteUpdate(equalEvent);

        console.log(JSON.stringify({{ rSelf, rOther, rStale, rEqual }}));
        """
    )
    # 自我事件被短路
    assert result["rSelf"] == {"skipped": "self"}
    # 他人事件通过
    assert result["rOther"]["skipped"] is None
    assert result["rOther"]["remoteUpdatedAt"] == 200
    # 时间戳较小 → stale 短路
    assert result["rStale"] == {"skipped": "stale"}
    # 时间戳相等 → stale 短路（<= 语义与 compat-contract §11.3 一致）
    assert result["rEqual"] == {"skipped": "stale"}


# -------------------------------------------------------------------------
# T12. canvasEditStore.save() base_updated_at 递增校验
# -------------------------------------------------------------------------

def test_canvas_edit_store_base_updated_at_monotonic_on_ok():
    result = run_node(
        f"""
        import {{ createCanvasEditStore }} from {json.dumps(CANVAS_EDIT_STORE)};
        const putCalls = [];
        let counter = 100;
        const store = createCanvasEditStore({{
          name:'classic', clientId:'CID',
          putCanvas: async (payload) => {{
            putCalls.push(payload);
            counter += 50;
            return {{ ok:true, status:200, json: async () => ({{ canvas: {{ id:'c1', updated_at: counter }} }}) }};
          }},
          buildPayload: () => ({{ client_id: 'CID', base_updated_at: store.lastServerUpdatedAt }}),
        }});
        store.setLastServerUpdatedAt(100);
        await store.save();
        const at1 = store.lastServerUpdatedAt;
        await store.save();
        const at2 = store.lastServerUpdatedAt;
        await store.save();
        const at3 = store.lastServerUpdatedAt;
        // base_updated_at 单调递增
        console.log(JSON.stringify({{
          putBaseSeq: putCalls.map(p => p.base_updated_at),
          at1, at2, at3,
        }}));
        """
    )
    # base_updated_at 每次 save 递增（100 → 150 → 200 → 250）
    assert result["putBaseSeq"] == [100, 150, 200]
    assert result["at1"] == 150
    assert result["at2"] == 200
    assert result["at3"] == 250


# -------------------------------------------------------------------------
# T13. _renderPatchToken / _pending 清理清单：canvas.js / smart-canvas.js grep
# -------------------------------------------------------------------------

def test_render_patch_token_not_written_to_save_payload():
    """
    Grep 抗回归：canvas.js / smart-canvas.js 的 saveCanvas 落盘 payload 中不能
    直接引用 `_renderPatchToken` 或 `_pending`。这些临时字段必须走
    `serializableCanvasNode()` / `canvasForStorage()` 清理清单。
    """
    canvas_src = CANVAS_JS.read_text(encoding='utf-8')
    smart_src = SMART_CANVAS_JS.read_text(encoding='utf-8')

    # `_renderPatchToken` 目前不会在 canvas.js / smart-canvas.js 中出现（PR-6
    # 引入清理清单条目，但字段本身可能只出现在 renderer 侧）
    canvas_token = canvas_src.count('_renderPatchToken')
    smart_token = smart_src.count('_renderPatchToken')

    # `_pending` 在 canvas.js 中的 output 计时逻辑存在（合法），但不能出现在
    # PUT /api/canvases body 附近（saveCanvas 内）
    save_canvas_pattern = re.search(
        r'async function saveCanvas\(\)\s*\{.*?\n\}',
        canvas_src,
        flags=re.DOTALL,
    )
    smart_save_pattern = re.search(
        r'async function saveCanvas\(\)\s*\{.*?\n\}',
        smart_src,
        flags=re.DOTALL,
    )
    assert save_canvas_pattern, "canvas.js: saveCanvas 函数未找到"
    assert smart_save_pattern, "smart-canvas.js: saveCanvas 函数未找到"

    canvas_save_body = save_canvas_pattern.group(0)
    smart_save_body = smart_save_pattern.group(0)

    # saveCanvas body 内不许出现 _renderPatchToken（PR-6 清理清单守护）
    assert '_renderPatchToken' not in canvas_save_body, \
        "canvas.js saveCanvas body 出现 _renderPatchToken（应走 serializableCanvasNode 清理）"
    assert '_renderPatchToken' not in smart_save_body, \
        "smart-canvas.js saveCanvas body 出现 _renderPatchToken（应走 canvasForStorage 清理）"

    # 记录当前 _renderPatchToken 使用量（PR-6 引入后可能在 renderer 里出现）
    # 本 PR 尚未真正在两画布中注入 token → 期望仍为 0
    assert canvas_token == 0, f"canvas.js _renderPatchToken 意外出现 {canvas_token} 处"
    assert smart_token == 0, f"smart-canvas.js _renderPatchToken 意外出现 {smart_token} 处"


# -------------------------------------------------------------------------
# T14. should-skip.js 语义等价 touch-mouse.js
# -------------------------------------------------------------------------

def test_should_skip_module_matches_touch_mouse_bridge_snapshot():
    """
    should-skip.js 语义快照锁死 touch-mouse.js:23-34。改动任一处必须
    同时改另一处，且本测试更新快照版本。
    """
    result = run_node(
        f"""
        import mod from {json.dumps(SHOULD_SKIP)};
        console.log(JSON.stringify({{
          selector: mod.INPUT_SELECTOR,
          snapshot: mod.skipRuleSnapshot(),
        }}));
        """
    )
    # selector 与 touch-mouse.js 同源
    expected_selector = 'input, textarea, select, audio, video, [contenteditable=""], [contenteditable="true"]'
    assert result["selector"] == expected_selector

    # snapshot 字段冻结
    snap = result["snapshot"]
    assert snap["inputSelector"] == expected_selector
    assert snap["source"] == "static/js/touch-mouse.js:23-34"
    assert snap["scrollDetection"]["scrollHeightThreshold"] == "scrollHeight > clientHeight + 1"
    assert snap["scrollDetection"]["scrollWidthThreshold"] == "scrollWidth > clientWidth + 1"

    # 事实核对：touch-mouse.js 中的 selector 字面量与本模块一致
    tm_src = TOUCH_MOUSE.read_text(encoding='utf-8')
    assert expected_selector in tm_src, "touch-mouse.js 的 selector 已漂移，请同步 should-skip.js"


# -------------------------------------------------------------------------
# T15. canvasEditStore.applyRemoteUpdate 合并 handleCanvasUpdatedMessage 语义
# -------------------------------------------------------------------------

def test_canvas_edit_store_apply_remote_update_matches_legacy_semantics():
    result = run_node(
        f"""
        import {{ createCanvasEditStore }} from {json.dumps(CANVAS_EDIT_STORE)};
        const store = createCanvasEditStore({{ name:'smart', clientId:'SMART_XYZ' }});
        store.setLastServerUpdatedAt(1000);

        // 智能画布语义：saveInFlight 期间 canvas_updated 也短路
        // （由 guardSaveInFlight 选项控制，对应 canvasSyncInFlight）
        // 模拟 saveInFlight
        const putCalls = [];
        const inFlightStore = createCanvasEditStore({{
          name:'smart2', clientId:'S2',
          putCanvas: async (p) => {{
            putCalls.push(p);
            // 在 saveInFlight 期间尝试 applyRemoteUpdate
            const r = inFlightStore.applyRemoteUpdate(
              {{ type:'canvas_updated', client_id:'S3', updated_at: 9999 }},
              {{ guardSaveInFlight: true }}
            );
            putCalls.push({{ inflight_apply: r }});
            return {{ ok:true, status:200, json: async () => ({{ canvas: {{ id:'c1', updated_at: 1500 }} }}) }};
          }},
          buildPayload: () => ({{ client_id:'S2', base_updated_at: 0 }}),
        }});
        await inFlightStore.save();

        // 非 canvas_updated 类型短路
        const wrongType = store.applyRemoteUpdate({{ type:'other', client_id:'X', updated_at: 3000 }});
        console.log(JSON.stringify({{
          putCalls, wrongType,
        }}));
        """
    )
    # saveInFlight 期间 applyRemoteUpdate 被 guardSaveInFlight 短路
    inflight_entry = next(x for x in result["putCalls"] if isinstance(x, dict) and "inflight_apply" in x)
    assert inflight_entry["inflight_apply"]["skipped"] == "save-in-flight"
    # 非 canvas_updated 类型短路
    assert result["wrongType"] == {"skipped": "not-canvas-updated"}


# -------------------------------------------------------------------------
# T16. wheel-zoom.js 两画布策略描述冻结 + factor 纯函数
# -------------------------------------------------------------------------

def test_wheel_zoom_module_preserves_dual_strategies():
    result = run_node(
        f"""
        import mod from {json.dumps(WHEEL_ZOOM)};
        console.log(JSON.stringify({{
          classicStrategy: mod.ZOOM_STRATEGIES.classic,
          smartStrategy: mod.ZOOM_STRATEGIES.smart,
          classicUp: mod.classicZoomFactor(-100),
          classicDown: mod.classicZoomFactor(100),
          smartUp: mod.smartZoomFactor(-100).toFixed(4),
          smartDown: mod.smartZoomFactor(100).toFixed(4),
        }}));
        """
    )
    # 两画布策略描述冻结
    assert result["classicStrategy"]["clamp"] == "none"
    assert result["classicStrategy"]["source"] == "canvas.js:14599-14611"
    assert result["smartStrategy"]["clamp"] == "safeScale (positive-only)"
    assert result["smartStrategy"]["source"] == "smart-canvas.js:16154-16167"
    # 经典 factor 冻结
    assert result["classicUp"] == 1.08
    assert result["classicDown"] == 0.92
    # 智能 factor 冻结（exp(-deltaY*0.001) → deltaY=-100 → exp(0.1) ≈ 1.1052；deltaY=100 → exp(-0.1) ≈ 0.9048）
    assert result["smartUp"] == "1.1052"
    assert result["smartDown"] == "0.9048"


# -------------------------------------------------------------------------
# T17. marquee.js 纯函数
# -------------------------------------------------------------------------

def test_marquee_module_pure_functions():
    result = run_node(
        f"""
        import mod from {json.dumps(MARQUEE)};
        // 反向拖拽也能正确正规化
        const rect1 = mod.normalizeMarqueeRect({{x:50, y:60}}, {{x:10, y:20}});
        const rect2 = mod.normalizeMarqueeRect({{x:10, y:20}}, {{x:50, y:60}});
        // 命中集合
        const nodes = [
          {{id:'n1', x:0, y:0, w:5, h:5}},
          {{id:'n2', x:20, y:20, w:10, h:10}},
          {{id:'n3', x:100, y:100, w:5, h:5}},
        ];
        const hits = mod.nodesIntersectingMarquee({{x:0, y:0, width:30, height:30}}, nodes);
        console.log(JSON.stringify({{ rect1, rect2, hits }}));
        """
    )
    assert result["rect1"] == result["rect2"]
    assert result["rect1"] == {"x": 10, "y": 20, "width": 40, "height": 40}
    assert sorted(result["hits"]) == ["n1", "n2"]


# -------------------------------------------------------------------------
# T18. hotkey.js normalizeCombo + register/dispatch
# -------------------------------------------------------------------------

def test_hotkey_module_normalize_combo_and_dispatch():
    result = run_node(
        f"""
        import {{ hotkey }} from {json.dumps(HOTKEY)};
        hotkey._resetForTests();
        const c1 = hotkey.normalizeCombo({{ctrl:true, key:'S'}});
        const c2 = hotkey.normalizeCombo({{shift:true, ctrl:true, key:'k'}});
        const fake = {{ctrlKey:true, key:'s'}};
        const c3 = hotkey.comboFromEvent(fake);
        let hits = 0;
        hotkey.register({{ctrl:true, key:'s'}}, () => hits += 1);
        hotkey.dispatch(fake);
        hotkey.dispatch({{ctrlKey:false, key:'s'}});
        hotkey._resetForTests();
        console.log(JSON.stringify({{c1, c2, c3, hits}}));
        """
    )
    assert result["c1"] == "ctrl+s"
    assert result["c2"] == "ctrl+shift+k"
    assert result["c3"] == "ctrl+s"
    # dispatch 只匹配 ctrl+s，第二次无 ctrl 不命中
    assert result["hits"] == 1


# -------------------------------------------------------------------------
# T19. focus.js shouldSuppressHotkey
# -------------------------------------------------------------------------

def test_focus_module_suppress_hotkey_selector():
    result = run_node(
        f"""
        import mod from {json.dumps(FOCUS)};
        console.log(JSON.stringify({{
          selector: mod.INPUT_SELECTOR,
        }}));
        """
    )
    # selector 与 shouldSkip 输入元素部分保持一致（不含 audio/video——focus 语义仅屏蔽键盘输入）
    assert 'input' in result["selector"]
    assert 'textarea' in result["selector"]
    assert 'contenteditable' in result["selector"]


# -------------------------------------------------------------------------
# T20. canvasEditStore save() applyingRemoteCanvas 入口守卫
# -------------------------------------------------------------------------

def test_canvas_edit_store_save_short_circuits_when_applying_remote():
    result = run_node(
        f"""
        import {{ createCanvasEditStore }} from {json.dumps(CANVAS_EDIT_STORE)};
        const putCalls = [];
        const store = createCanvasEditStore({{
          name:'classic', clientId:'C',
          putCanvas: async (p) => {{ putCalls.push(p); return {{ok:true, status:200, json:async()=>({{}})}}; }},
          buildPayload: () => ({{ client_id:'C', base_updated_at: 0 }}),
        }});
        store.beginApplyingRemote();
        const r1 = await store.save();
        store.endApplyingRemote();
        const r2 = await store.save();
        console.log(JSON.stringify({{ r1, r2, putCalls }}));
        """
    )
    # applyingRemoteCanvas 期间 save() 被短路
    assert result["r1"] == {"ok": False, "skipped": "applyingRemote"}
    # 清除标志后 save() 正常
    assert result["r2"]["ok"] is True
    # putCanvas 只被调用一次（第二次）
    assert len(result["putCalls"]) == 1


# -------------------------------------------------------------------------
# T21. renderer / interactions 13 seam 文件全部存在
# -------------------------------------------------------------------------

def test_thirteen_seam_files_exist():
    """
    硬门槛 1：新增 5 renderer + 6 interactions + 1 should-skip + 1 canvasEditStore = 13 seam 文件全部存在。
    """
    expected = [
        "static/js/modules/canvas/renderer/viewport.js",
        "static/js/modules/canvas/renderer/connections.js",
        "static/js/modules/canvas/renderer/nodesLayer.js",
        "static/js/modules/canvas/renderer/hitTest.js",
        "static/js/modules/canvas/renderer/render-loop.js",
        "static/js/modules/canvas/interactions/pointer.js",
        "static/js/modules/canvas/interactions/drag.js",
        "static/js/modules/canvas/interactions/wheel-zoom.js",
        "static/js/modules/canvas/interactions/hotkey.js",
        "static/js/modules/canvas/interactions/focus.js",
        "static/js/modules/canvas/interactions/marquee.js",
        "static/js/shared/interaction/pointer/should-skip.js",
        "static/js/modules/canvas/store/canvasEditStore.js",
    ]
    missing = [p for p in expected if not (ROOT / p).is_file()]
    assert not missing, f"seam files missing: {missing}"
    assert len(expected) == 13


# -------------------------------------------------------------------------
# T22. Wrapper 兜底：老全局函数 saveCanvas / renderConnections / renderNode 仍可用
# -------------------------------------------------------------------------

def test_legacy_wrappers_remain_defined_in_two_canvas_files():
    canvas_src = CANVAS_JS.read_text(encoding='utf-8')
    smart_src = SMART_CANVAS_JS.read_text(encoding='utf-8')

    # canvas.js 保留 saveCanvas / renderNode / renderLinks
    assert 'async function saveCanvas()' in canvas_src, "canvas.js: saveCanvas 全局函数被移除"
    assert 'function renderNode(' in canvas_src, "canvas.js: renderNode 全局函数被移除"
    assert 'function renderLinks(' in canvas_src or 'renderConnections' in canvas_src, \
        "canvas.js: renderLinks/renderConnections 全局函数被移除"

    # smart-canvas.js 保留 saveCanvas / renderConnections
    assert 'async function saveCanvas()' in smart_src, "smart-canvas.js: saveCanvas 全局函数被移除"
    assert 'function renderConnections()' in smart_src, "smart-canvas.js: renderConnections 全局函数被移除"


# -------------------------------------------------------------------------
# T23. canvasEditStore.subscribe 通知语义
# -------------------------------------------------------------------------

def test_canvas_edit_store_subscribe_and_revision():
    result = run_node(
        f"""
        import {{ createCanvasEditStore }} from {json.dumps(CANVAS_EDIT_STORE)};
        const store = createCanvasEditStore({{name:'x', clientId:'ID'}});
        const events = [];
        const un = store.subscribe((snap, rev, reason) => events.push({{rev, reason}}));
        store.setLocalDirty(true);
        store.setLastServerUpdatedAt(500);
        store.setViewport({{x:10, y:20, scale:1.5}});
        un();
        store.setLocalDirty(false);
        console.log(JSON.stringify({{ events, finalRev: store.revision }}));
        """
    )
    reasons = [e["reason"] for e in result["events"]]
    assert reasons == ["setLocalDirty", "setLastServerUpdatedAt", "setViewport"]
    # revision 单调递增
    revs = [e["rev"] for e in result["events"]]
    assert revs == sorted(set(revs)) and len(set(revs)) == len(revs)
    # unsubscribe 后 revision 仍 +1（notify 被跳过因为无订阅方）
    assert result["finalRev"] >= revs[-1]


# -------------------------------------------------------------------------
# T24. compat-contract §13.4 追加 _renderPatchToken 条目
# -------------------------------------------------------------------------

def test_compat_contract_lists_render_patch_token():
    contract = (ROOT / "docs/frontend-freeze/compat-contract.md").read_text(encoding='utf-8')
    # PR-6 追加清理条目
    assert '_renderPatchToken' in contract
    # PR-6 明确注解
    assert re.search(r'_renderPatchToken.*(PR-6|前端 PR-6)', contract), \
        "compat-contract 未把 _renderPatchToken 归到 PR-6"
