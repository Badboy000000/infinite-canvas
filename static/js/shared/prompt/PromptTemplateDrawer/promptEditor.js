// static/js/shared/prompt/PromptTemplateDrawer/promptEditor.js
//
// Seam-period 提示词模板抽屉「编辑器 seam」（[[前端组件化治理实施计划与PR清单]] PR-11）。
//
// 定位：与 MediaEditor（PR-4）逐字对齐——canvas.js 内已有的抽屉实现
// （`openPromptTemplateModal` / `renderPromptTemplateModal` / `closePromptTemplateModal`
// + `loadCanvasPromptTemplates` + 保存/删除/分组管理若干函数）保持不动，
// 通过 `PromptTemplateDrawer.register('classic', adapter)` 认领为一个组件。
//
// 本模块只提供**分派实现**：把 `PromptTemplateDrawer.open/close/render/loadTemplates/
// saveTemplate` 转发给已注册 adapter。**不搬 canvas.js 中的抽屉 DOM/事件逻辑**，
// 因此不引入 fabric/前端框架、不引入构建。业务逻辑 byte-equivalent 保持
// （见 tests/frontend/test_pr_11_prompt_template_drawer.py T296）。
//
// adapter 契约（PR-11 冻结）：
//   {
//     open(nodeId, options): 打开抽屉（对齐 canvas.js `openPromptTemplateModal(nodeId)`）
//     close(): 关闭抽屉（对齐 canvas.js `closePromptTemplateModal()`）
//     renderCallback(): 重渲染（对齐 canvas.js `renderPromptTemplateModal()`）
//     loadTemplates(): 拉取活跃库模板列表（对齐 canvas.js `loadCanvasPromptTemplates`）
//     saveTemplate(payload): 保存/新建模板（可选；缺省时 seam 层返回 no-op）
//   }
//
// 硬约束：
//   - 前端 seam 期无构建。本模块是 classic IIFE 脚本，不引入任何依赖。
//   - canvas.js 中的抽屉函数体保持 byte-equivalent；任何"业务分派"发生在本 seam。

(function installPromptEditor(global) {
  'use strict';

  if (global.__PromptTemplateDrawerEditor) return;

  const CANVAS_KINDS = Object.freeze(['classic']); // seam 期仅经典画布使用；扩展需同步 [[前端兼容合同冻结清单]]。

  function validateKind(canvasKind) {
    if (!CANVAS_KINDS.includes(canvasKind)) {
      throw new Error(`PromptTemplateDrawer: 未知 canvasKind: ${canvasKind}`);
    }
  }

  function getAdapter(state, canvasKind) {
    validateKind(canvasKind);
    const adapter = state.adapters.get(canvasKind);
    return adapter || null;
  }

  /**
   * 分派 open：把 `{ canvasKind, nodeId, options }` 转发给 adapter.open(nodeId, options)。
   * 返回 Promise，`finally` 内保证会话释放（供未来渲染循环 / 状态挂起判定使用）。
   */
  function open(state, args) {
    if (!args || typeof args !== 'object') {
      return Promise.reject(new Error('PromptTemplateDrawer.open 需要 { canvasKind, nodeId, options } 参数对象'));
    }
    const canvasKind = args.canvasKind || 'classic';
    const nodeId = args.nodeId || '';
    const options = args.options || {};
    const adapter = getAdapter(state, canvasKind);
    if (!adapter) {
      return Promise.reject(new Error(`PromptTemplateDrawer.open 未找到 ${canvasKind} adapter；canvas.js 尚未加载或未 register()`));
    }
    if (typeof adapter.open !== 'function') {
      return Promise.reject(new Error(`PromptTemplateDrawer.open ${canvasKind} adapter 未提供 open()`));
    }
    const session = {
      id: `${canvasKind}:${nodeId}:${Date.now()}:${Math.random().toString(36).slice(2, 6)}`,
      canvasKind,
      nodeId,
      options,
      startedAt: Date.now(),
    };
    state.active = session;
    return Promise.resolve()
      .then(() => adapter.open(nodeId, options))
      .then(v => ({ ok: true, canvasKind, nodeId, adapterResult: v === undefined ? null : v }))
      .finally(() => {
        if (state.active === session) state.active = null;
      });
  }

  /** 分派 close。同步返回 adapter.close() 的返回值。 */
  function close(state, canvasKind) {
    const kind = canvasKind || 'classic';
    const adapter = getAdapter(state, kind);
    if (!adapter || typeof adapter.close !== 'function') return null;
    try { return adapter.close(); }
    finally { state.active = null; }
  }

  /** 分派 render（外部重渲染触发点）。 */
  function render(state, canvasKind) {
    const kind = canvasKind || 'classic';
    const adapter = getAdapter(state, kind);
    if (!adapter || typeof adapter.renderCallback !== 'function') return null;
    return adapter.renderCallback();
  }

  /** 分派 loadTemplates（可用于外部预热）。 */
  function loadTemplates(state, canvasKind) {
    const kind = canvasKind || 'classic';
    const adapter = getAdapter(state, kind);
    if (!adapter || typeof adapter.loadTemplates !== 'function') return Promise.resolve([]);
    return Promise.resolve().then(() => adapter.loadTemplates());
  }

  /** 分派 saveTemplate（可选 adapter 能力）。 */
  function saveTemplate(state, canvasKind, payload) {
    const kind = canvasKind || 'classic';
    const adapter = getAdapter(state, kind);
    if (!adapter || typeof adapter.saveTemplate !== 'function') return Promise.resolve(null);
    return Promise.resolve().then(() => adapter.saveTemplate(payload));
  }

  const api = Object.freeze({
    CANVAS_KINDS,
    open,
    close,
    render,
    loadTemplates,
    saveTemplate,
    validateKind,
    getAdapter,
  });

  global.__PromptTemplateDrawerEditor = api;
})(typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : this));
