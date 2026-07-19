// static/js/modules/canvas/interactions/drag.js
//
// 前端 PR-6：Drag session 互斥表 seam（[[前端组件化治理实施计划与PR清单]] PR-6）。
//
// 定位：
//   - **互斥表**：`dragNode` / `resizeNode` / `tempLink` / `llmPaneDrag`
//     / `portDragState` / `selectionState` / `connectionEraseState` 显式登记
//     开始/结束/取消协议。
//   - **僵尸态检出**：`connectionEraseState` 等异常残留会阻塞后续交互；本
//     模块提供 `isActive(kind)` / `snapshot()` / `endAll(reason)` 检测与
//     兜底清理接口，配合测试锁行为。
//   - **认领而非重写**：`canvas.js` / `smart-canvas.js` 现有交互实现保留；
//     本模块作为**追加登记层**记录 session 生命周期事件，不替换现有变量。
//
// Session kinds（**冻结**）：
export const DRAG_SESSION_KINDS = Object.freeze([
  'dragNode',
  'resizeNode',
  'tempLink',
  'llmPaneDrag',
  'portDragState',
  'selectionState',
  'connectionEraseState',
]);

/** 互斥策略（**冻结**）：某 kind 活跃时，禁止启动这些 kind */
export const MUTEX_RULES = Object.freeze({
  dragNode:              ['tempLink', 'portDragState', 'selectionState', 'connectionEraseState', 'llmPaneDrag'],
  resizeNode:            ['tempLink', 'portDragState', 'selectionState', 'connectionEraseState'],
  tempLink:              ['dragNode', 'resizeNode', 'selectionState', 'connectionEraseState'],
  llmPaneDrag:           ['dragNode', 'resizeNode', 'selectionState'],
  portDragState:         ['dragNode', 'resizeNode', 'selectionState', 'connectionEraseState'],
  selectionState:        ['dragNode', 'resizeNode', 'tempLink', 'portDragState', 'connectionEraseState', 'llmPaneDrag'],
  connectionEraseState:  ['dragNode', 'resizeNode', 'tempLink', 'portDragState', 'selectionState'],
});

function createDragSessionRegistry() {
  /** @type {Map<string, { kind:string, startedAt:number, meta:object }>} */
  const sessions = new Map();
  const listeners = new Set();

  function notify(event) {
    listeners.forEach(fn => {
      try { fn(event); }
      catch (err) { if (globalThis.console) console.error('[dragSessions] listener failed:', err); }
    });
  }

  /**
   * 开始一个 session。返回 { ok, reason }。
   * 若与已活跃 session 互斥，则 ok=false，`reason=blocked-by:<kind>`。
   */
  function begin(kind, meta = {}) {
    if (!DRAG_SESSION_KINDS.includes(kind)) {
      return { ok: false, reason: `unknown-kind:${kind}` };
    }
    // 互斥检查
    for (const active of sessions.keys()) {
      const rules = MUTEX_RULES[active] || [];
      if (rules.includes(kind)) {
        return { ok: false, reason: `blocked-by:${active}` };
      }
    }
    if (sessions.has(kind)) {
      return { ok: false, reason: `already-active:${kind}` };
    }
    const record = { kind, startedAt: Date.now(), meta: { ...meta } };
    sessions.set(kind, record);
    notify({ phase: 'begin', kind, meta: record.meta });
    return { ok: true };
  }

  /**
   * 结束 session（正常结束 or 取消 or 提交）。
   * `reason` 语义：'end' / 'cancel' / 'commit'（各画布自定义）。
   */
  function end(kind, reason = 'end') {
    if (!sessions.has(kind)) return { ok: false, reason: `not-active:${kind}` };
    const record = sessions.get(kind);
    sessions.delete(kind);
    notify({ phase: 'end', kind, reason, elapsed: Date.now() - record.startedAt });
    return { ok: true };
  }

  /** 强制结束所有 session（如页面切换、错误恢复）。返回被结束的 kind 列表。 */
  function endAll(reason = 'endAll') {
    const kinds = [...sessions.keys()];
    kinds.forEach(k => end(k, reason));
    return kinds;
  }

  function isActive(kind) {
    return sessions.has(kind);
  }

  function snapshot() {
    const out = {};
    sessions.forEach((v, k) => { out[k] = { startedAt: v.startedAt, meta: { ...v.meta } }; });
    return out;
  }

  function subscribe(fn) {
    if (typeof fn !== 'function') throw new TypeError('subscribe: fn 必须是函数');
    listeners.add(fn);
    return () => listeners.delete(fn);
  }

  function _resetForTests() {
    sessions.clear();
    listeners.clear();
  }

  return Object.freeze({
    begin,
    end,
    endAll,
    isActive,
    snapshot,
    subscribe,
    _resetForTests,
  });
}

/** 每画布页各自实例化（同 `canvasEditStore` 语义），本页共享单例。 */
export const dragSessions = createDragSessionRegistry();

export default dragSessions;
