// static/js/modules/canvas/renderer/render-loop.js
//
// 前端 PR-6：Canvas 单 rAF 主循环 seam（[[前端组件化治理实施计划与PR清单]] PR-6）。
//
// 定位：
//   - **单 rAF 主循环**：两画布现有多处 `requestAnimationFrame(...)` 调用点
//     统一走本模块的 `renderLoop.request(callback)`；同一 tick 内多次 request
//     合并为一次 flush（协调阶段）。
//   - **pause('media-editor') / resume('media-editor') 契约**：MediaEditor 打开
//     期间挂起主循环，避免与编辑器 UI 争用 rAF（**承接前端 PR-4 F-2 P3
//     遗留**：MediaEditor adapter register 竞态窗口）。
//   - 兼容 seam 期：本模块**不强制**接管所有 rAF，仅提供入口；两画布可以
//     渐进迁移（PR-14/PR-15 才做完整收敛）。
//
// 硬约束：
//   - 零构建零依赖；纯 ES module。
//   - pause() 是**引用计数式**——多个来源 pause 需各自 resume 才恢复。
//   - flush 期间 handler 抛错不影响其他 handler；捕获后 console.error 上报。
//
// 使用示例：
//     import { renderLoop } from '/static/js/modules/canvas/renderer/render-loop.js';
//     renderLoop.request(() => render());
//     renderLoop.pause('media-editor');
//     ...MediaEditor open...
//     renderLoop.resume('media-editor');

/** pause 来源枚举（**冻结**）——扩展时需在此登记并同步 KB 决策 */
export const PAUSE_SOURCES = Object.freeze(['media-editor', 'suspend', 'test']);

function createRenderLoop() {
  /** @type {Set<Function>} */
  const pending = new Set();
  /** @type {Map<string, number>} */
  const pauseCounts = new Map();
  let scheduled = null; // rAF id or setTimeout id
  let flushing = false;

  function isPaused() {
    for (const [, count] of pauseCounts) {
      if (count > 0) return true;
    }
    return false;
  }

  function pauseSources() {
    const out = [];
    for (const [key, count] of pauseCounts) {
      if (count > 0) out.push({ source: key, count });
    }
    return out;
  }

  function pause(source = 'suspend') {
    const key = String(source || 'suspend');
    pauseCounts.set(key, (pauseCounts.get(key) || 0) + 1);
  }

  function resume(source = 'suspend') {
    const key = String(source || 'suspend');
    const cur = pauseCounts.get(key) || 0;
    if (cur <= 1) {
      pauseCounts.delete(key);
    } else {
      pauseCounts.set(key, cur - 1);
    }
    // resume 时如果已解除所有暂停且仍有 pending 任务，重新调度一次 flush
    if (!isPaused() && pending.size > 0 && scheduled === null) {
      schedule();
    }
  }

  function schedule() {
    if (scheduled !== null || flushing) return;
    const raf = (typeof globalThis.requestAnimationFrame === 'function')
      ? globalThis.requestAnimationFrame.bind(globalThis)
      : (cb) => setTimeout(() => cb(Date.now()), 16);
    scheduled = raf(flush);
  }

  function flush() {
    scheduled = null;
    if (isPaused()) return; // paused：任务保留在 pending，resume 时再调度
    if (pending.size === 0) return;
    flushing = true;
    const batch = [...pending];
    pending.clear();
    try {
      for (const cb of batch) {
        try { cb(); }
        catch (err) {
          if (globalThis.console) console.error('[renderLoop] handler failed:', err);
        }
      }
    } finally {
      flushing = false;
    }
    // flush 期间新增的 request 已经在 pending 里，需要再排一次
    if (pending.size > 0 && !isPaused()) schedule();
  }

  function request(callback) {
    if (typeof callback !== 'function') throw new TypeError('renderLoop.request: callback 必须是函数');
    pending.add(callback);
    if (!isPaused()) schedule();
  }

  /** 测试用：立即清空所有状态 */
  function _resetForTests() {
    pending.clear();
    pauseCounts.clear();
    scheduled = null;
    flushing = false;
  }

  /** 测试用：手动触发 flush（无需等待 rAF） */
  function _flushSync() {
    if (scheduled !== null) {
      // 取消可能存在的 raf
      scheduled = null;
    }
    flush();
  }

  return Object.freeze({
    request,
    pause,
    resume,
    isPaused,
    pauseSources,
    pendingCount: () => pending.size,
    _resetForTests,
    _flushSync,
  });
}

/**
 * 全局单例——**同一页面内一份**。
 * canvas.html 与 smart-canvas.html 各自 load 一次，独立作用域。
 */
export const renderLoop = createRenderLoop();

/** 供 canvas.js / smart-canvas.js 无模块脚本消费（兜底 window 挂载） */
if (typeof globalThis !== 'undefined' && !globalThis.__canvasRenderLoop) {
  globalThis.__canvasRenderLoop = renderLoop;
}

export default renderLoop;
