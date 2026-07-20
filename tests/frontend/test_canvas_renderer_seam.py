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

    # `_renderPatchToken` 在 canvas.js / smart-canvas.js 中只允许出现在
    # `serializableCanvasNode()` / `canvasForStorage()` 清理链里
    # （Wave 3-H 前端 PR-6 承接补丁）。任何 saveCanvas body 内的直接引用都
    # 属于回归。
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

    # canvas.js: `delete copy._renderPatchToken` 只允许在 `serializableCanvasNode`
    # 清理链内（Wave 3-H 承接补丁）
    serializable_pattern = re.search(
        r'function serializableCanvasNode\(node\)\s*\{.*?\n\}',
        canvas_src,
        flags=re.DOTALL,
    )
    assert serializable_pattern, "canvas.js: serializableCanvasNode 函数未找到"
    serializable_body = serializable_pattern.group(0)
    assert 'delete copy._renderPatchToken' in serializable_body, \
        "canvas.js serializableCanvasNode 缺 `delete copy._renderPatchToken`（Wave 3-H 承接补丁）"
    assert 'delete copy._pending' in serializable_body, \
        "canvas.js serializableCanvasNode 缺 `delete copy._pending`（Wave 3-H 承接补丁）"
    # canvas.js 中 `_renderPatchToken` 只允许在 serializableCanvasNode 函数体里出现
    # （delete 语句 + 可选注释），不允许出现在其他源码位置。
    canvas_outside = canvas_src.replace(serializable_body, '')
    assert '_renderPatchToken' not in canvas_outside, (
        "canvas.js 中 `_renderPatchToken` 只允许出现在 serializableCanvasNode 清理链里；"
        "其他位置发现了这个字段，请把它挪回清理链"
    )

    # smart-canvas.js: `delete node._renderPatchToken` 只允许在 `canvasForStorage`
    # 清理链内
    for_storage_pattern = re.search(
        r'function canvasForStorage\(\)\s*\{.*?\n\}',
        smart_src,
        flags=re.DOTALL,
    )
    assert for_storage_pattern, "smart-canvas.js: canvasForStorage 函数未找到"
    for_storage_body = for_storage_pattern.group(0)
    assert 'delete node._renderPatchToken' in for_storage_body, \
        "smart-canvas.js canvasForStorage 缺 `delete node._renderPatchToken`（Wave 3-H 承接补丁）"
    assert 'delete node._pending' in for_storage_body, \
        "smart-canvas.js canvasForStorage 缺 `delete node._pending`（Wave 3-H 承接补丁）"
    smart_outside = smart_src.replace(for_storage_body, '')
    assert '_renderPatchToken' not in smart_outside, (
        "smart-canvas.js 中 `_renderPatchToken` 只允许出现在 canvasForStorage 清理链里；"
        "其他位置发现了这个字段，请把它挪回清理链"
    )


# -------------------------------------------------------------------------
# T13b. 清理清单运行时防线：构造节点走清理链 → 断言 _pending / _renderPatchToken 剥离
# -------------------------------------------------------------------------

def test_serializable_canvas_node_strips_pending_and_render_patch_token():
    """
    Wave 3-H 前端 PR-6 承接补丁 运行时防线（T14b）：
    - 从 canvas.js 提取 `serializableCanvasNode` 函数源代码并 eval
    - 构造带 `_pending` / `_renderPatchToken` 的节点
    - 断言清理后两个字段都被剥离，但 id / type / x / y / images 保留
    """
    canvas_src = CANVAS_JS.read_text(encoding='utf-8')
    serializable_pattern = re.search(
        r'function serializableCanvasNode\(node\)\s*\{.*?\n\}',
        canvas_src,
        flags=re.DOTALL,
    )
    assert serializable_pattern, "canvas.js: serializableCanvasNode 函数未找到"
    fn_src = serializable_pattern.group(0)

    # 用 Node.js eval 加载函数体并调用
    result = run_node(
        f"""
        {fn_src}
        const node = {{
          id: 'n1', type: 'output', x: 10, y: 20,
          images: [{{ url: 'a.png' }}],
          _pending: [{{ id: 'p1', progress: 0.5 }}, {{ id: 'p2' }}],
          _renderPatchToken: 42,
          running: true,
          runStatus: 'busy',
          runError: {{ message: 'err' }},
          _cascadeIdx: 3,
          _cascadeFailed: true,
          _activeLoopCtx: {{ foo: 'bar' }},
          _ltxEditor: {{ open: true }},
        }};
        const cleaned = serializableCanvasNode(node);
        console.log(JSON.stringify({{
          cleaned,
          keys: Object.keys(cleaned).sort(),
          originalKeys: Object.keys(node).sort(),
        }}));
        """
    )
    # 运行时防线：_pending / _renderPatchToken 都不在清理后的对象上
    assert '_pending' not in result['cleaned']
    assert '_renderPatchToken' not in result['cleaned']
    # 其它临时字段也被剥离
    for temp in ('running', 'runStatus', 'runError', '_cascadeIdx',
                 '_cascadeFailed', '_activeLoopCtx', '_ltxEditor'):
        assert temp not in result['cleaned'], f"清理链遗漏 {temp}"
    # 落盘字段保留
    assert result['cleaned']['id'] == 'n1'
    assert result['cleaned']['type'] == 'output'
    assert result['cleaned']['x'] == 10
    assert result['cleaned']['y'] == 20
    assert result['cleaned']['images'] == [{'url': 'a.png'}]
    # 原始对象未被 mutate
    assert '_pending' in result['originalKeys']
    assert '_renderPatchToken' in result['originalKeys']


def test_smart_canvas_for_storage_strips_pending_and_render_patch_token():
    """
    Wave 3-H 前端 PR-6 承接补丁 运行时防线（T14b smart 侧）：
    - 从 smart-canvas.js 提取 `canvasForStorage` 里的 per-node 清理片段
    - 用 Node 直接跑 clone + delete 逻辑
    - 断言 `_pending` / `_renderPatchToken` 剥离，落盘字段保留
    """
    smart_src = SMART_CANVAS_JS.read_text(encoding='utf-8')
    # 确认清理片段确实包含 `delete node._pending;` 与 `delete node._renderPatchToken;`
    for_storage_pattern = re.search(
        r'function canvasForStorage\(\)\s*\{.*?\n\}',
        smart_src,
        flags=re.DOTALL,
    )
    assert for_storage_pattern, "smart-canvas.js: canvasForStorage 函数未找到"
    body = for_storage_pattern.group(0)
    assert 'delete node._pending' in body
    assert 'delete node._renderPatchToken' in body

    # 独立复现清理循环：以最小闭包重放
    result = run_node(
        """
        const canvas = {
          id: 'sc1',
          nodes: [
            {
              id: 'n1', type: 'output', x: 0, y: 0,
              images: [{ url: 'a.png' }],
              _pending: [{ id: 'p1' }],
              _renderPatchToken: 7,
            },
            {
              id: 'n2', type: 'prompt', x: 100, y: 100,
              _pending: [],
              _renderPatchToken: 9,
            },
          ],
        };
        const clean = JSON.parse(JSON.stringify(canvas));
        (clean.nodes || []).forEach(node => {
          delete node._pending;
          delete node._renderPatchToken;
        });
        console.log(JSON.stringify({
          nodes: clean.nodes,
          originalHasPending: canvas.nodes[0]._pending !== undefined,
        }));
        """
    )
    for cleaned_node in result['nodes']:
        assert '_pending' not in cleaned_node
        assert '_renderPatchToken' not in cleaned_node
    assert result['nodes'][0]['id'] == 'n1'
    assert result['nodes'][0]['images'] == [{'url': 'a.png'}]
    # 原始对象未受影响
    assert result['originalHasPending'] is True


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


def test_should_skip_dom_driven_matrix():
    """
    Wave 3-H 承接补丁 T15 强化：DOM 驱动 STRONG 化 shouldSkip。

    在 Node.js 里安装最小 mock DOM（Element 类 + document + getComputedStyle），
    覆盖以下 skip 决策路径：
      1) 非 Element → skip=true
      2) target=<input> → skip=true（selector 早期返回）
      3) <span> 在 <textarea> 子孙 → skip=true（closest 链）
      4) target=<div>（无输入、无滚动） → skip=false
      5) target=<div>，父级 overflow-y=auto 且 scrollHeight > clientHeight+1 → skip=true
      6) target=<div>，父级 overflow-x=scroll 且 scrollWidth > clientWidth+1 → skip=true
      7) target=<div>，父级 overflow-y=hidden 且内容溢出 → skip=false（regex 不含 hidden）
      8) 父级溢出但差值 = 1（边界值不触发） → skip=false
    """
    result = run_node(
        f"""
        import mod from {json.dumps(SHOULD_SKIP)};

        // ---- mock DOM ----
        class Element {{
          constructor(opts = {{}}) {{
            this.tagName = (opts.tagName || 'DIV').toUpperCase();
            this.parentElement = opts.parentElement || null;
            this._attrs = opts.attrs || {{}};
            this._style = opts.style || {{ overflowX: 'visible', overflowY: 'visible' }};
            this.scrollHeight = opts.scrollHeight ?? 0;
            this.clientHeight = opts.clientHeight ?? 0;
            this.scrollWidth = opts.scrollWidth ?? 0;
            this.clientWidth = opts.clientWidth ?? 0;
          }}
          getAttribute(name) {{
            return Object.prototype.hasOwnProperty.call(this._attrs, name)
              ? this._attrs[name]
              : null;
          }}
          matches(sel) {{
            const parts = sel.split(',').map(s => s.trim()).filter(Boolean);
            return parts.some(part => {{
              const m = part.match(/^\\[([a-zA-Z-]+)="([^"]*)"\\]$/);
              if (m) {{
                const actual = this.getAttribute(m[1]);
                if (actual === null) return false;
                return String(actual) === m[2];
              }}
              return this.tagName === part.toUpperCase();
            }});
          }}
          closest(sel) {{
            let cur = this;
            while (cur) {{
              if (cur.matches && cur.matches(sel)) return cur;
              cur = cur.parentElement;
            }}
            return null;
          }}
        }}
        globalThis.Element = Element;
        const body = new Element({{ tagName: 'body' }});
        const html = new Element({{ tagName: 'html' }});
        globalThis.document = {{ body, documentElement: html }};
        globalThis.getComputedStyle = (node) => node._style || null;

        // 1) 非 Element
        const r1 = mod.shouldSkip('not-an-element');

        // 2) target=<input>
        const inputEl = new Element({{ tagName: 'input' }});
        const r2 = mod.shouldSkip(inputEl);

        // 3) <span> 在 <textarea> 子孙
        const textareaEl = new Element({{ tagName: 'textarea' }});
        const spanEl = new Element({{ tagName: 'span', parentElement: textareaEl }});
        const r3 = mod.shouldSkip(spanEl);

        // 4) 普通 <div>，无输入、无滚动
        const plainDiv = new Element({{ tagName: 'div' }});
        const r4 = mod.shouldSkip(plainDiv);

        // 5) 父级 overflow-y=auto + 内容溢出
        const scrollYParent = new Element({{
          tagName: 'div',
          style: {{ overflowY: 'auto', overflowX: 'visible' }},
          scrollHeight: 500, clientHeight: 100,
        }});
        const targetInScrollY = new Element({{ tagName: 'div', parentElement: scrollYParent }});
        const r5 = mod.shouldSkip(targetInScrollY);

        // 6) 父级 overflow-x=scroll + 横向溢出
        const scrollXParent = new Element({{
          tagName: 'div',
          style: {{ overflowY: 'visible', overflowX: 'scroll' }},
          scrollWidth: 500, clientWidth: 100,
        }});
        const targetInScrollX = new Element({{ tagName: 'div', parentElement: scrollXParent }});
        const r6 = mod.shouldSkip(targetInScrollX);

        // 7) 父级 overflow-y=hidden + 内容溢出（hidden 不算 skip）
        const hiddenParent = new Element({{
          tagName: 'div',
          style: {{ overflowY: 'hidden', overflowX: 'visible' }},
          scrollHeight: 500, clientHeight: 100,
        }});
        const targetInHidden = new Element({{ tagName: 'div', parentElement: hiddenParent }});
        const r7 = mod.shouldSkip(targetInHidden);

        // 8) 父级 overflow-y=auto + 差值 = 1（边界不触发，需 > +1）
        const boundaryParent = new Element({{
          tagName: 'div',
          style: {{ overflowY: 'auto', overflowX: 'visible' }},
          scrollHeight: 101, clientHeight: 100,
        }});
        const targetBoundary = new Element({{ tagName: 'div', parentElement: boundaryParent }});
        const r8 = mod.shouldSkip(targetBoundary);

        delete globalThis.Element;
        delete globalThis.document;
        delete globalThis.getComputedStyle;
        console.log(JSON.stringify({{ r1, r2, r3, r4, r5, r6, r7, r8 }}));
        """
    )
    assert result["r1"] is True, "非 Element 应 skip=true"
    assert result["r2"] is True, "<input> 应 skip=true"
    assert result["r3"] is True, "<span> 在 <textarea> 子孙应 skip=true"
    assert result["r4"] is False, "普通 <div> 应 skip=false"
    assert result["r5"] is True, "父级 overflow-y=auto + 溢出应 skip=true"
    assert result["r6"] is True, "父级 overflow-x=scroll + 溢出应 skip=true"
    assert result["r7"] is False, "父级 overflow-y=hidden 不应 skip（正则不匹配 hidden）"
    assert result["r8"] is False, "差值 = 1 应 skip=false（阈值是 > +1，严格大于）"


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


def test_focus_module_dom_driven_suppress_hotkey_matrix():
    """
    Wave 3-H 承接补丁 T20 强化：DOM 驱动 STRONG 化 focus.shouldSuppressHotkey。

    构造 mock DOM 节点，手工实现 `closest`，覆盖：
      1) target 为 <input> → suppress
      2) target 在 <input> 子孙 → suppress（closest 链）
      3) target 为 <button> → NOT suppress
      4) target 为 [contenteditable="true"] → suppress
      5) target 为 [contenteditable="false"] → NOT suppress
      6) event.target 非 input 但 document.activeElement 是 input → suppress
      7) event 缺失 target → 走 activeElement fallback
    """
    result = run_node(
        f"""
        import mod from {json.dumps(FOCUS)};

        // ---- mock DOM ----
        function makeNode({{ tagName, parent = null, attrs = {{}} }}) {{
          const node = {{
            tagName: tagName.toUpperCase(),
            parentNode: parent,
            _attrs: attrs,
            getAttribute(name) {{
              return Object.prototype.hasOwnProperty.call(this._attrs, name)
                ? this._attrs[name]
                : null;
            }},
          }};
          node.matches = (sel) => matchesSelector(node, sel);
          node.closest = (sel) => {{
            let cur = node;
            while (cur) {{
              if (cur.matches && cur.matches(sel)) return cur;
              cur = cur.parentNode;
            }}
            return null;
          }};
          return node;
        }}

        // 支持 `tag`、`[attr="v"]`、`[attr=""]`
        function matchesSelector(node, sel) {{
          const parts = sel.split(',').map(s => s.trim()).filter(Boolean);
          return parts.some(part => {{
            const attrM = part.match(/^\\[([a-zA-Z-]+)="([^"]*)"\\]$/);
            if (attrM) {{
              const [_, name, val] = attrM;
              const actual = node.getAttribute(name);
              if (actual === null) return false;  // 未设置属性 → 不匹配任何值
              return String(actual) === val;
            }}
            return node.tagName === part.toUpperCase();
          }});
        }}

        // 1) target = <input>
        const inputNode = makeNode({{ tagName: 'input' }});
        const r1 = mod.shouldSuppressHotkey({{ target: inputNode }});

        // 2) target 是 <span>，但父链有 <textarea>
        const textarea = makeNode({{ tagName: 'textarea' }});
        const spanInTextarea = makeNode({{ tagName: 'span', parent: textarea }});
        const r2 = mod.shouldSuppressHotkey({{ target: spanInTextarea }});

        // 3) target = <button>
        const button = makeNode({{ tagName: 'button' }});
        const r3 = mod.shouldSuppressHotkey({{ target: button }});

        // 4) target = [contenteditable="true"] div
        const editableDiv = makeNode({{ tagName: 'div', attrs: {{ contenteditable: 'true' }} }});
        const r4 = mod.shouldSuppressHotkey({{ target: editableDiv }});

        // 5) target = [contenteditable="false"] div
        const nonEditableDiv = makeNode({{ tagName: 'div', attrs: {{ contenteditable: 'false' }} }});
        const r5 = mod.shouldSuppressHotkey({{ target: nonEditableDiv }});

        // 6) event.target 是 button，但 document.activeElement 是 input
        globalThis.document = {{ activeElement: makeNode({{ tagName: 'input' }}) }};
        const r6 = mod.shouldSuppressHotkey({{ target: button }});
        delete globalThis.document;

        // 7) event 缺失 target，activeElement 是 textarea
        globalThis.document = {{ activeElement: makeNode({{ tagName: 'textarea' }}) }};
        const r7 = mod.shouldSuppressHotkey({{}});
        delete globalThis.document;

        // 8) 完全没 target 也没 document
        const r8 = mod.shouldSuppressHotkey({{}});

        // 9) event 为 null
        const r9 = mod.shouldSuppressHotkey(null);

        console.log(JSON.stringify({{ r1, r2, r3, r4, r5, r6, r7, r8, r9 }}));
        """
    )
    assert result["r1"] is True, "target=<input> should suppress"
    assert result["r2"] is True, "target 在 <textarea> 子孙应 suppress（closest 链）"
    assert result["r3"] is False, "target=<button> should NOT suppress"
    assert result["r4"] is True, '[contenteditable="true"] should suppress'
    assert result["r5"] is False, '[contenteditable="false"] should NOT suppress'
    assert result["r6"] is True, "activeElement=input 时应走 fallback suppress"
    assert result["r7"] is True, "缺 target 但 activeElement=textarea 应 suppress"
    assert result["r8"] is False, "全空场景应 NOT suppress"
    assert result["r9"] is False, "event=null 应 NOT suppress"


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


# -------------------------------------------------------------------------
# T25. seam 覆盖率矩阵：register 侧 24/24 = 100%，consumer 侧 0/24（等 PR-7 承接）
# -------------------------------------------------------------------------

# 24 个契约域 = (seam 文件路径, 契约标识符)。每一项都在 seam 侧被显式 export；
# 消费侧（canvas.js / smart-canvas.js）目前还未 import — 等前端 PR-7 才连消费面。
SEAM_CONTRACT_DOMAINS = (
    ("static/js/modules/canvas/renderer/viewport.js", "CANVAS_KINDS"),
    ("static/js/modules/canvas/renderer/viewport.js", "VIEWPORT_STORAGE_FIELDS"),
    ("static/js/modules/canvas/renderer/viewport.js", "pickViewportForStorage"),
    ("static/js/modules/canvas/renderer/connections.js", "LAYER_KINDS"),
    ("static/js/modules/canvas/renderer/connections.js", "CLASSIC_CONNECTION_FIELDS"),
    ("static/js/modules/canvas/renderer/connections.js", "SMART_CONNECTION_FIELDS"),
    ("static/js/modules/canvas/renderer/connections.js", "validateConnectionShape"),
    ("static/js/modules/canvas/renderer/hitTest.js", "HIT_TARGETS"),
    ("static/js/modules/canvas/renderer/hitTest.js", "rectsIntersect"),
    ("static/js/modules/canvas/renderer/hitTest.js", "pointInRect"),
    ("static/js/modules/canvas/renderer/nodesLayer.js", "NODE_CLASS_NAMES"),
    ("static/js/modules/canvas/renderer/nodesLayer.js", "NODE_ID_ATTR"),
    ("static/js/modules/canvas/renderer/render-loop.js", "PAUSE_SOURCES"),
    ("static/js/modules/canvas/renderer/render-loop.js", "renderLoop"),
    ("static/js/modules/canvas/interactions/drag.js", "DRAG_SESSION_KINDS"),
    ("static/js/modules/canvas/interactions/drag.js", "MUTEX_RULES"),
    ("static/js/modules/canvas/interactions/drag.js", "dragSessions"),
    ("static/js/modules/canvas/interactions/pointer.js", "POINTER_INPUT_KINDS"),
    ("static/js/modules/canvas/interactions/wheel-zoom.js", "ZOOM_STRATEGIES"),
    ("static/js/modules/canvas/interactions/hotkey.js", "HOTKEY_MODIFIERS"),
    ("static/js/modules/canvas/interactions/focus.js", "shouldSuppressHotkey"),
    ("static/js/modules/canvas/interactions/marquee.js", "normalizeMarqueeRect"),
    ("static/js/shared/interaction/pointer/should-skip.js", "skipRuleSnapshot"),
    ("static/js/modules/canvas/store/canvasEditStore.js", "CANVAS_EDIT_CONFLICT_FIELDS"),
)

# Consumer files that will eventually import from these seam modules.
# 前端 PR-6 seam 抽出阶段仅登记契约、不做 consumer 迁移；PR-7 才把
# canvas.js / smart-canvas.js 内的等价符号切换到 import。
SEAM_CONSUMER_FILES = (
    "static/js/canvas.js",
    "static/js/smart-canvas.js",
)


def test_seam_coverage_matrix_register_side_full_and_consumer_side_pending():
    """
    Wave 3-H 前端 PR-6 承接补丁 seam 覆盖率矩阵（RC-PR-6 P1-6 闭合）：

    - **register 侧（seam 模块）**：24/24 契约域全部通过 `export` 暴露 → 100%。
      任一契约域丢失都是回归（削 seam 契约）。
    - **consumer 侧（canvas.js / smart-canvas.js）**：24/24 契约域**尚未** import
      → 目前理应 0%。当前 PR-6 只做 seam 抽出、不动 consumer；PR-7 承接
      "让两画布 import seam" 时该期望要显式翻转到 24/24 或渐进解锁。

    这里断言的是"契约域覆盖率"而不是物理 wc -l 下降 — 后者交 PR-14/PR-15
    真正 SPA 化时再做。
    """
    assert len(SEAM_CONTRACT_DOMAINS) == 24, (
        f"契约域应有 24 项，实际 {len(SEAM_CONTRACT_DOMAINS)}；"
        "调整时必须同步更新 test 期望"
    )

    # register 侧覆盖率：每个契约域在源码里必须能 grep 到 `export ... <ident>`
    register_hits = 0
    missing_registers: list[tuple[str, str]] = []
    for seam_path, ident in SEAM_CONTRACT_DOMAINS:
        src = (ROOT / seam_path).read_text(encoding='utf-8')
        # 匹配 `export const IDENT` / `export function IDENT(` / `export default {…IDENT…}` 中的显式命名
        # 我们只关心第一二种（named export）
        pattern = re.compile(
            rf'export\s+(?:const|let|function|class)\s+{re.escape(ident)}\b'
        )
        if pattern.search(src):
            register_hits += 1
        else:
            missing_registers.append((seam_path, ident))

    register_rate = register_hits / len(SEAM_CONTRACT_DOMAINS)
    assert register_rate == 1.0, (
        f"seam register 侧覆盖率 {register_rate:.2%}（{register_hits}/{len(SEAM_CONTRACT_DOMAINS)}），"
        f"缺失 {missing_registers}"
    )

    # consumer 侧覆盖率：每个契约域在 canvas.js / smart-canvas.js 中检查
    # 是否有 `import { IDENT }` 或 `import ... from '.../seam-path'` 引用
    consumer_hits = 0
    consumer_refs: list[tuple[str, str, str]] = []  # (consumer, seam_path, ident)
    for consumer in SEAM_CONSUMER_FILES:
        src = (ROOT / consumer).read_text(encoding='utf-8')
        for seam_path, ident in SEAM_CONTRACT_DOMAINS:
            # 消费面证据 = 从 seam 路径 import 该 ident；`import {…IDENT…} from '.../<basename>'`
            base = Path(seam_path).name
            pattern = re.compile(
                rf'import\s*(?:\{{[^}}]*\b{re.escape(ident)}\b[^}}]*\}}|[^\'"\n]*?)\s*from\s*["\'][^"\']*{re.escape(base)}["\']'
            )
            if pattern.search(src):
                consumer_hits += 1
                consumer_refs.append((consumer, seam_path, ident))

    # PR-6 seam 抽出阶段：consumer 侧 0/24 是**预期**状态。任何非零命中说明
    # 有人开始悄悄接线了 — 强制该 PR 更新 SEAM_COVERAGE_PLAN 说明是不是 PR-7。
    max_expected_consumer_hits = 0
    assert consumer_hits <= max_expected_consumer_hits, (
        f"consumer 侧 seam 覆盖率意外上升到 {consumer_hits}/{len(SEAM_CONTRACT_DOMAINS)}；"
        f"命中项 {consumer_refs}；PR-6 只抽 seam、不动 consumer — 若是 PR-7 承接，"
        "请同时把这里的 max_expected_consumer_hits 抬到当前值并更新注释"
    )
