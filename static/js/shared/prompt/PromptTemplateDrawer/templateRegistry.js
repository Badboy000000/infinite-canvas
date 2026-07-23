// static/js/shared/prompt/PromptTemplateDrawer/templateRegistry.js
//
// Seam-period 提示词模板抽屉「模块级状态」承接（[[前端组件化治理实施计划与PR清单]] PR-11）。
//
// 定位：PR-11 之前 `canvas.js` 顶部（L425-433）以 `let canvasPromptTemplates`、
// `let canvasPromptTemplatesLoaded`、`let canvasPromptTemplateOverrides` 三条模块级
// 变量承载抽屉状态。本 seam 期把这三条状态迁到 shared/prompt 下，并通过
// `Object.defineProperty(window, ...)` 装到全局，保留原变量名（byte-equivalent，
// 允许 wrapper/export 微小抖动）以避免业务逻辑漂移。
//
// 硬约束（[[前端组件化治理方案]] + task book PR-11）：
//   - 前端 seam 期无构建。本模块是 classic IIFE 脚本，不引入任何依赖。
//   - `overrides` 字段 shape 与 baseline `97ba98a` 完全对齐：
//     `{ hiddenBuiltinIds:string[], editedBuiltins:Record<string, object> }`。
//   - `libraries` / `activeLibraryId` / `groups` / `groupEditMode` 归 canvas.js
//     持有；本 registry 只承接迁移前 canvas.js 中命名带 `canvasPromptTemplate*`
//     前缀的三条模块级状态。
//   - 与 canvas.js 顶部 `let` 声明字节等价：canvas.js 移除三条 `let` 后，函数体内
//     `canvasPromptTemplates = X` 通过 non-strict 全局赋值 → window setter → 本 registry。
//
// 载入顺序：HTML 中位于 canvas.js 之前。
// 迁移前 canvas.js 中同名 localStorage key，seam 期保持不变。

(function installPromptTemplateRegistry(global) {
  'use strict';

  // 幂等：同页多次 include 兜底。
  if (global.__PromptTemplateDrawerRegistry) return;

  /**
   * 抽屉共享注册表。canvas.js 通过 `window.PromptTemplateDrawer.registry` 访问，
   * 或通过 `window.canvasPromptTemplates` / `window.canvasPromptTemplatesLoaded` /
   * `window.canvasPromptTemplateOverrides` 的 defineProperty 代理访问。
   * 字段与迁移前的 canvas.js 顶部 `let` 一一对应。
   */
  const registry = {
    /** @type {Array<object>} 当前 library items 列表（活跃库派生结果）。 */
    templates: [],
    /** @type {boolean} 是否已完成首次 `loadCanvasPromptTemplates`。 */
    templatesLoaded: false,
    /**
     * 覆盖态：`hiddenBuiltinIds` 隐藏的内置模板 id 列表；
     * `editedBuiltins` 内置模板本地覆盖字段。
     */
    overrides: { hiddenBuiltinIds: [], editedBuiltins: {} },
  };

  // 冻结的 localStorage key（迁移前 canvas.js 使用同名 key，seam 期保持不变）。
  const CANVAS_PROMPT_TEMPLATE_GROUPS_KEY = 'canvas_prompt_template_groups_v1';
  const CANVAS_PROMPT_TEMPLATE_OVERRIDES_KEY = 'canvas_prompt_template_overrides';

  /**
   * 把 registry 三字段以旧 `let` 变量的同名 window 属性形式挂到全局，
   * 使 canvas.js 内 `canvasPromptTemplates = X` 通过非严格 non-strict 全局
   * 赋值 → 触发 setter → 落回 registry。读取同理。
   */
  function installGlobalProxies(target) {
    if (!target) return;
    if (target.__promptTemplateProxiesInstalled) return;
    Object.defineProperty(target, 'canvasPromptTemplates', {
      configurable: true,
      enumerable: true,
      get() { return registry.templates; },
      set(next) { registry.templates = Array.isArray(next) ? next : []; },
    });
    Object.defineProperty(target, 'canvasPromptTemplatesLoaded', {
      configurable: true,
      enumerable: true,
      get() { return registry.templatesLoaded; },
      set(next) { registry.templatesLoaded = Boolean(next); },
    });
    Object.defineProperty(target, 'canvasPromptTemplateOverrides', {
      configurable: true,
      enumerable: true,
      get() { return registry.overrides; },
      set(next) {
        if (next && typeof next === 'object') {
          registry.overrides = {
            hiddenBuiltinIds: Array.isArray(next.hiddenBuiltinIds) ? next.hiddenBuiltinIds : [],
            editedBuiltins: (next.editedBuiltins && typeof next.editedBuiltins === 'object') ? next.editedBuiltins : {},
          };
        } else {
          registry.overrides = { hiddenBuiltinIds: [], editedBuiltins: {} };
        }
      },
    });
    target.__promptTemplateProxiesInstalled = true;
  }

  const api = Object.freeze({
    registry,
    installGlobalProxies,
    /** 读 `templates`。 */
    getTemplates() { return registry.templates; },
    /** 写 `templates`。 */
    setTemplates(next) { registry.templates = Array.isArray(next) ? next : []; },
    /** 读 `templatesLoaded`。 */
    isTemplatesLoaded() { return registry.templatesLoaded === true; },
    /** 写 `templatesLoaded`。 */
    setTemplatesLoaded(next) { registry.templatesLoaded = Boolean(next); },
    /** 读 `overrides`。 */
    getOverrides() { return registry.overrides; },
    /** 写 `overrides`（保持 shape 契约）。 */
    setOverrides(next) {
      if (next && typeof next === 'object') {
        registry.overrides = {
          hiddenBuiltinIds: Array.isArray(next.hiddenBuiltinIds) ? next.hiddenBuiltinIds : [],
          editedBuiltins: (next.editedBuiltins && typeof next.editedBuiltins === 'object') ? next.editedBuiltins : {},
        };
      } else {
        registry.overrides = { hiddenBuiltinIds: [], editedBuiltins: {} };
      }
    },
    /** 复位工具（单测用）。 */
    reset() {
      registry.templates = [];
      registry.templatesLoaded = false;
      registry.overrides = { hiddenBuiltinIds: [], editedBuiltins: {} };
    },
    CANVAS_PROMPT_TEMPLATE_GROUPS_KEY,
    CANVAS_PROMPT_TEMPLATE_OVERRIDES_KEY,
  });

  global.__PromptTemplateDrawerRegistry = api;
  installGlobalProxies(global);
})(typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : this));
