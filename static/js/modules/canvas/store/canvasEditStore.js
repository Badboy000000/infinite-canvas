// static/js/modules/canvas/store/canvasEditStore.js
//
// 前端 PR-6：Canvas 编辑保存冲突状态机 store（[[前端组件化治理实施计划与PR清单]] PR-6）。
//
// 定位（seam 期硬约束 · 认领而非重写）：
//   - **每画布页各自实例化**（不是全局单例）：canvas.html 与 smart-canvas.html
//     分别 `new createCanvasEditStore(...)` 一次。
//   - **保存冲突状态机 6 个字段**（[[docs/frontend-freeze/compat-contract.md]] §11
//     决策 6 · [[Wave 3-H 协调纲要#前端 PR-6 契约冻结要点]]）：
//         `serverSnapshot`
//         `lastServerUpdatedAt`
//         `localDirty`
//         `saveInFlight`
//         `pendingResave`
//         `conflictResolution`
//     叠加：`viewport` / `selection` / `undoStack` / `applyingRemoteCanvas`。
//
//   - `save()` 内部逻辑**收进 store action**，但对外行为完全等价：
//         * `applyingRemoteCanvas` 标志保留（`saveCanvas` / `scheduleSave` 入口守卫）
//         * 409 两种 shape 兼容读保留（`data.detail.canvas` 与 `data.canvas`；
//           `compat-contract.md` §10）
//         * `client_id === CLIENT_ID` 自我识别语义保留（`compat-contract.md` §11.3）
//         * `base_updated_at` / `updated_at` 递增校验保留（`compat-contract.md` §11.6）
//
//   - `handleCanvasUpdatedMessage` 合并进 `applyRemoteUpdate(event)`，**不新增协议**。
//
// 硬约束：
//   - **零构建零依赖**；纯 ES module。
//   - `_pending` / `_renderPatchToken` 等临时字段**不落盘**（`serializableCanvasNode()`
//     / `canvasForStorage()` 清理清单由两画布侧保持；本 store 通过 `sanitize` hook
//     在 save() 前调用画布侧提供的清理函数）。
//   - Provider 凭据永不落 store（跨 domain 抗回归约束——本 store 不接触 provider）。

import { pickViewportForStorage } from '../renderer/viewport.js';

/** 保存冲突状态机 6 个字段（**冻结**——`compat-contract.md` §11） */
export const CANVAS_EDIT_CONFLICT_FIELDS = Object.freeze([
  'serverSnapshot',
  'lastServerUpdatedAt',
  'localDirty',
  'saveInFlight',
  'pendingResave',
  'conflictResolution',
]);

/** 冲突解决模式（**冻结**） */
export const CONFLICT_MODES = Object.freeze(['idle', 'awaiting-remote', 'merged', 'overridden']);

/**
 * 工厂：创建一个 canvasEditStore 实例。
 *
 * @param {object} options
 * @param {string} options.name                       诊断用名字（'classic' / 'smart'）
 * @param {string} options.clientId                   CLIENT_ID 常量（每 tab 唯一）
 * @param {(payload:object)=>Promise<Response>} options.putCanvas     PUT /api/canvases/{id}（由消费者注入 fetch 语义）
 * @param {()=>object} options.buildPayload           构造 PUT body（包含 client_id / base_updated_at）
 * @param {(remote:object)=>void} [options.applyRemote]  409 时把远端画布覆盖本地（可选）
 * @param {(next:object,remote:object)=>void} [options.mergeRemote]   智能画布"合并写"回调（可选）
 * @param {(reason:string)=>void} [options.onStatus]  状态切换回调（'Syncing...' / 'Saved' / 'Save failed'）
 */
export function createCanvasEditStore(options = {}) {
  const name = String(options.name || 'anonymous');
  const clientId = String(options.clientId || '');
  const putCanvas = typeof options.putCanvas === 'function' ? options.putCanvas : null;
  const buildPayload = typeof options.buildPayload === 'function' ? options.buildPayload : null;
  const applyRemote = typeof options.applyRemote === 'function' ? options.applyRemote : null;
  const mergeRemote = typeof options.mergeRemote === 'function' ? options.mergeRemote : null;
  const onStatus = typeof options.onStatus === 'function' ? options.onStatus : null;

  /** @type {any} */
  let serverSnapshot = null;
  let lastServerUpdatedAt = 0;
  let localDirty = false;
  let saveInFlight = false;
  let pendingResave = false;
  let conflictResolution = 'idle';

  // 附加状态字段（协调纲要 6 字段 + 补充 3 字段）
  let viewport = { x: 0, y: 0, scale: 1 };
  let selection = { ids: [] };
  const undoStack = [];
  let applyingRemoteCanvas = false;

  const listeners = new Set();
  let revision = 0;

  function status(state) {
    if (onStatus) {
      try { onStatus(state); }
      catch (err) { if (globalThis.console) console.error(`[canvasEditStore/${name}] onStatus failed:`, err); }
    }
  }

  function notify(reason) {
    revision += 1;
    listeners.forEach(fn => {
      try { fn(snapshot(), revision, reason); }
      catch (err) { if (globalThis.console) console.error(`[canvasEditStore/${name}] handler failed:`, err); }
    });
  }

  function subscribe(handler) {
    if (typeof handler !== 'function') throw new TypeError('subscribe: handler 必须是函数');
    listeners.add(handler);
    return () => listeners.delete(handler);
  }

  function snapshot() {
    return {
      serverSnapshot,
      lastServerUpdatedAt,
      localDirty,
      saveInFlight,
      pendingResave,
      conflictResolution,
      viewport: { ...viewport },
      selection: { ids: [...(selection.ids || [])] },
      undoStack: [...undoStack],
      applyingRemoteCanvas,
    };
  }

  function setLocalDirty(flag = true, reason = 'setLocalDirty') {
    localDirty = Boolean(flag);
    notify(reason);
  }

  function setViewport(v, reason = 'setViewport') {
    viewport = pickViewportForStorage(v);
    notify(reason);
  }

  function setSelection(ids, reason = 'setSelection') {
    selection = { ids: Array.isArray(ids) ? [...ids] : [] };
    notify(reason);
  }

  function pushUndo(entry) {
    undoStack.push(entry);
    notify('pushUndo');
  }

  function beginApplyingRemote() {
    applyingRemoteCanvas = true;
    notify('beginApplyingRemote');
  }

  function endApplyingRemote() {
    applyingRemoteCanvas = false;
    notify('endApplyingRemote');
  }

  /**
   * 保存 action：把 saveCanvas 内部逻辑收进 store。
   * 语义（对外等价 `canvas.js:saveCanvas` / `smart-canvas.js:saveCanvas`）：
   *   1. `applyingRemoteCanvas` 期间入口守卫 → 直接返回
   *   2. `saveInFlight` 期间入口守卫 → 置 `pendingResave = true` 返回
   *   3. 触发 `putCanvas(buildPayload())`
   *   4. 200/OK：更新 `lastServerUpdatedAt`；`localDirty = pendingResave`
   *   5. 409：**两种 shape 兼容读**（`data.detail.canvas` 与 `data.canvas`）；
   *      调用 `applyRemote` / `mergeRemote` 后可能自我重试
   *   6. 其他错误：`onStatus('Save failed')`；不清 `pendingResave`
   *   7. finally：`saveInFlight = false`；若 `pendingResave` 且非 remote，
   *      置 `pendingResave = false, localDirty = true` 并触发下一轮
   */
  async function save() {
    if (applyingRemoteCanvas) return { ok: false, skipped: 'applyingRemote' };
    if (saveInFlight) {
      pendingResave = true;
      notify('save/queued');
      return { ok: false, skipped: 'inflight-queued' };
    }
    if (!putCanvas || !buildPayload) return { ok: false, skipped: 'no-adapter' };

    saveInFlight = true;
    pendingResave = false;
    notify('save/start');
    status('Saving...');
    try {
      const payload = buildPayload();
      // client_id / base_updated_at 由 buildPayload() 侧注入（保持两画布现有字段命名）
      const res = await putCanvas(payload);
      if (res && res.status === 409) {
        // **两种 shape 兼容读**（`compat-contract.md` §10）
        const data = await safelyReadJson(res);
        const remote = readConflictRemoteCanvas(data);
        const remoteUpdatedAt = Number(
          data?.detail?.updated_at
          ?? data?.updated_at
          ?? remote?.updated_at
          ?? lastServerUpdatedAt
          ?? 0,
        );
        if (localDirty || pendingResave) {
          lastServerUpdatedAt = remoteUpdatedAt;
          pendingResave = true;
          conflictResolution = 'awaiting-remote';
          notify('save/409-queue-resave');
          status('Saving...');
          return { ok: false, conflict: true, resave: true };
        }
        if (remote) {
          if (mergeRemote) {
            mergeRemote(remote, data);
            conflictResolution = 'merged';
          } else if (applyRemote) {
            applyRemote(remote);
            conflictResolution = 'overridden';
          }
        }
        serverSnapshot = remote || serverSnapshot;
        lastServerUpdatedAt = remoteUpdatedAt;
        status('Synced');
        notify('save/409-applied');
        return { ok: false, conflict: true, resave: false };
      }
      if (!res || !res.ok) {
        throw new Error(`save failed: ${res ? res.status : 'no-response'}`);
      }
      const data = await safelyReadJson(res);
      const remote = data?.canvas || null;
      if (remote) {
        serverSnapshot = remote;
        const t = Number(remote.updated_at || 0);
        if (t) lastServerUpdatedAt = t;
      }
      localDirty = Boolean(pendingResave);
      conflictResolution = 'idle';
      status('Saved');
      notify('save/ok');
      return { ok: true, conflict: false };
    } catch (err) {
      if (globalThis.console) console.error(`[canvasEditStore/${name}] save failed:`, err);
      status('Save failed');
      notify('save/error');
      return { ok: false, error: err };
    } finally {
      saveInFlight = false;
      if (pendingResave && !applyingRemoteCanvas) {
        pendingResave = false;
        localDirty = true;
        notify('save/resave-scheduled');
        // 交给消费者侧触发下一轮（scheduleSave / setTimeout），本 store 不硬编码 timing
      }
    }
  }

  /**
   * 处理远端 canvas_updated 事件（合并 `handleCanvasUpdatedMessage` 逻辑）。
   * 语义（对齐 `canvas.js:2178-2190` / `smart-canvas.js:5213-5219`）：
   *   1. 自我识别短路：`event.client_id === clientId` → return
   *   2. 时间戳短路：`event.updated_at <= lastServerUpdatedAt` → return
   *   3. saveInFlight 期间：智能画布语义要求短路（`canvasSyncInFlight`），
   *      本 store 交由消费者通过 `guardSaveInFlight` 选项决定
   *   4. 通过判定后：置 `localDirty = false`，`conflictResolution = 'awaiting-remote'`
   *      并通知订阅方（订阅方可触发 `syncRemoteCanvasNow`）
   */
  function applyRemoteUpdate(event, opts = {}) {
    if (!event || event.type !== 'canvas_updated') return { skipped: 'not-canvas-updated' };
    if (event.client_id && event.client_id === clientId) return { skipped: 'self' };
    const remoteAt = Number(event.updated_at || 0);
    if (remoteAt && remoteAt <= Number(lastServerUpdatedAt || 0)) return { skipped: 'stale' };
    if (opts.guardSaveInFlight && saveInFlight) return { skipped: 'save-in-flight' };
    localDirty = false;
    conflictResolution = 'awaiting-remote';
    notify('applyRemoteUpdate');
    return { skipped: null, remoteUpdatedAt: remoteAt };
  }

  /** 更新 lastServerUpdatedAt（供保存成功后 / 初始化 load 时同步） */
  function setLastServerUpdatedAt(t, reason = 'setLastServerUpdatedAt') {
    const n = Number(t) || 0;
    if (n) {
      lastServerUpdatedAt = n;
      notify(reason);
    }
  }

  function setServerSnapshot(remote, reason = 'setServerSnapshot') {
    serverSnapshot = remote || null;
    if (remote && remote.updated_at) lastServerUpdatedAt = Number(remote.updated_at) || lastServerUpdatedAt;
    notify(reason);
  }

  function _resetForTests() {
    serverSnapshot = null;
    lastServerUpdatedAt = 0;
    localDirty = false;
    saveInFlight = false;
    pendingResave = false;
    conflictResolution = 'idle';
    viewport = { x: 0, y: 0, scale: 1 };
    selection = { ids: [] };
    undoStack.length = 0;
    applyingRemoteCanvas = false;
    listeners.clear();
    revision = 0;
  }

  return Object.freeze({
    name,
    clientId,
    get revision() { return revision; },
    snapshot,
    subscribe,
    setLocalDirty,
    setViewport,
    setSelection,
    pushUndo,
    beginApplyingRemote,
    endApplyingRemote,
    setLastServerUpdatedAt,
    setServerSnapshot,
    save,
    applyRemoteUpdate,
    _resetForTests,
    // 只读投影 getter（供订阅方与测试直接读取字段值）
    get serverSnapshot() { return serverSnapshot; },
    get lastServerUpdatedAt() { return lastServerUpdatedAt; },
    get localDirty() { return localDirty; },
    get saveInFlight() { return saveInFlight; },
    get pendingResave() { return pendingResave; },
    get conflictResolution() { return conflictResolution; },
    get viewport() { return { ...viewport }; },
    get selection() { return { ids: [...(selection.ids || [])] }; },
    get undoStack() { return [...undoStack]; },
    get applyingRemoteCanvas() { return applyingRemoteCanvas; },
  });
}

/**
 * 409 两种 shape 兼容读（**冻结** · compat-contract.md §10）：
 *   - 优先 `data.detail.canvas`（经典画布 + 智能画布共享路径）
 *   - 兜底 `data.canvas`（经典画布回落路径；智能画布不走此路径）
 */
export function readConflictRemoteCanvas(data) {
  if (!data || typeof data !== 'object') return null;
  return (data.detail && data.detail.canvas) || data.canvas || null;
}

async function safelyReadJson(res) {
  if (!res || typeof res.json !== 'function') return {};
  try { return await res.json(); }
  catch { return {}; }
}

export default createCanvasEditStore;
