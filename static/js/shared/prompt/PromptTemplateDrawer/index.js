// static/js/shared/prompt/PromptTemplateDrawer/index.js
//
// Seam-period 提示词模板抽屉「统一门面」（[[前端组件化治理实施计划与PR清单]] PR-11）。
//
// 定位：与 MediaEditor（PR-4）等价对齐。canvas.js 内的抽屉实现
// （openPromptTemplateModal / renderPromptTemplateModal / closePromptTemplateModal
// + loadCanvasPromptTemplates + 保存/删除/分组管理若干函数）保持不动，通过
// `PromptTemplateDrawer.register('classic', adapter)` 认领为组件。外部只调
// `PromptTemplateDrawer.open({ canvasKind, nodeId, options })`。
//
// 硬约束（[[前端组件化治理方案]] + task book PR-11 + [[前端兼容合同冻结清单]] §7.11）：
//   - `openPromptTemplateModal(nodeId)` / `renderPromptTemplateModal()` /
//     `closePromptTemplateModal()` 三个 window 全局函数**冻结签名**保持
//     （canvas.js 侧仍以 wrapper 形式对外暴露，body 走 `PromptTemplateDrawer.open()`）。
//   - localStorage key `canvas_prompt_template_groups_v1` / `canvas_prompt_template_overrides`
//     不变（seam 期兼容契约，见 §4）。
//   - 无 npm / webpack / babel / tsc / bundler；纯 vanilla JS 直接 `<script src>` 加载。
//   - templateRegistry.js 和 promptEditor.js 必须在本文件之前加载。

(function installPromptTemplateDrawer(global) {
  'use strict';

  if (global.PromptTemplateDrawer && global.PromptTemplateDrawerReady) return; // 幂等

  const CANVAS_KINDS = Object.freeze(['classic']);

  const state = {
    /** @type {Map<string, object>} canvasKind -> adapter */
    adapters: new Map(),
    /** 活跃会话；同一时间只允许一个。 */
    active: null,
  };

  /**
   * 注册 canvasKind 对应的 adapter。
   * adapter 必须提供 { open, close, renderCallback, loadTemplates, saveTemplate }。
   *
   * @param {'classic'} canvasKind
   * @param {object} adapter
   */
  function register(canvasKind, adapter) {
    if (!CANVAS_KINDS.includes(canvasKind)) {
      throw new Error(`PromptTemplateDrawer.register 未知 canvasKind: ${canvasKind}`);
    }
    if (!adapter || typeof adapter !== 'object') {
      throw new Error('PromptTemplateDrawer.register 需要传入 adapter 对象');
    }
    state.adapters.set(canvasKind, adapter);
  }

  /**
   * 内部查询已注册 adapter。
   */
  function _getAdapter(canvasKind) {
    return state.adapters.get(canvasKind) || null;
  }

  function requireEditor() {
    const editor = global.__PromptTemplateDrawerEditor;
    if (!editor) {
      throw new Error('PromptTemplateDrawer: promptEditor.js 未加载（应在 index.js 之前 `<script src>`）');
    }
    return editor;
  }

  /**
   * 统一入口。返回 Promise；finally 内保证会话释放。
   *
   * @param {object} args
   * @param {'classic'} args.canvasKind
   * @param {string}    args.nodeId       目标提示词节点 id
   * @param {object}    [args.options]    透传给 adapter.open 的额外参数
   * @returns {Promise<{ok:boolean, canvasKind:string, nodeId:string}>}
   */
  function open(args) {
    return requireEditor().open(state, args);
  }

  /** 关闭抽屉。 */
  function close(canvasKind) {
    return requireEditor().close(state, canvasKind);
  }

  /** 重渲染（外部触发点：canvas.js L12844+ / L12846）。 */
  function render(canvasKind) {
    return requireEditor().render(state, canvasKind);
  }

  /** 是否有活跃会话。 */
  function isOpen() {
    return Boolean(state.active);
  }

  /** 当前会话描述（read-only）。 */
  function current() {
    return state.active ? { ...state.active } : null;
  }

  /** 读取当前 adapter 的 loadTemplates()。 */
  function loadTemplates(canvasKind) {
    return requireEditor().loadTemplates(state, canvasKind);
  }

  /** 委托给 adapter.saveTemplate()（可选能力）。 */
  function saveTemplate(canvasKind, payload) {
    return requireEditor().saveTemplate(state, canvasKind, payload);
  }

  const registryApi = global.__PromptTemplateDrawerRegistry || null;

  const PromptTemplateDrawer = Object.freeze({
    register,
    open,
    close,
    render,
    isOpen,
    current,
    loadTemplates,
    saveTemplate,
    CANVAS_KINDS,
    _getAdapter, // 内部；测试使用
    registry: registryApi ? registryApi.registry : null,
    // 状态操作透传（canvas.js 迁移期通过它读写模块级状态）
    getTemplates: registryApi ? registryApi.getTemplates : () => [],
    setTemplates: registryApi ? registryApi.setTemplates : () => {},
    isTemplatesLoaded: registryApi ? registryApi.isTemplatesLoaded : () => false,
    setTemplatesLoaded: registryApi ? registryApi.setTemplatesLoaded : () => {},
    getOverrides: registryApi ? registryApi.getOverrides : () => ({ hiddenBuiltinIds: [], editedBuiltins: {} }),
    setOverrides: registryApi ? registryApi.setOverrides : () => {},
    CANVAS_PROMPT_TEMPLATE_GROUPS_KEY: registryApi ? registryApi.CANVAS_PROMPT_TEMPLATE_GROUPS_KEY : 'canvas_prompt_template_groups_v1',
    CANVAS_PROMPT_TEMPLATE_OVERRIDES_KEY: registryApi ? registryApi.CANVAS_PROMPT_TEMPLATE_OVERRIDES_KEY : 'canvas_prompt_template_overrides',
  });

  global.PromptTemplateDrawer = PromptTemplateDrawer;

  // 就绪 Promise：与 MediaEditor bootstrap 对齐；canvas.js 通过
  // `window.PromptTemplateDrawerReady.then(() => PromptTemplateDrawer.register(...))` 注册。
  global.PromptTemplateDrawerReady = Promise.resolve(PromptTemplateDrawer);
})(typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : this));
