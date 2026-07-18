// static/js/shared/media/MediaEditor/index.js
//
// Seam-period 媒体编辑器统一入口（[[前端组件化治理实施计划与PR清单]] PR-4）。
//
// 定位：MediaEditor 在 seam 期是一个**门面 + 注册表**——不重写现有 canvas.js
// / smart-canvas.js 内的 5 种编辑器实现（裁剪 / 遮罩 / 涂抹 / 宫格切分 / 宫格拼接），
// 而是把它们认领为组件：
//
//   1. `canvas.js` / `smart-canvas.js` 各自在自身作用域内实现打开编辑器的能力，
//      并调用 `MediaEditor.register(canvasKind, adapter)` 把入口注册进本门面。
//   2. 外部只调 `MediaEditor.open({source, mode, onCommit, canvasKind})`，
//      门面根据 canvasKind + mode 派发到已注册 adapter。
//   3. MediaEditor.open 返回 Promise；`finally` 中释放会话 / 事件。
//
// 硬约束（[[前端组件化治理治理方案]] + task book PR-4）：
//   - 打开期间 `render()` 挂起 / pending 状态挂起 / touch-mouse.js skip 规则**由 adapter 保持**。
//   - 输出 URL 语义不变（过渡期走 `/api/upload`）。
//   - 节点 JSON 落盘 shape 不变（`canvasForStorage` / `serializableCanvasNode` 清理清单不变）。
//   - 不引入 fabric.js / Konva / cropperjs。
//   - `mode: 'grid-join'` 的 `source` 契约字段：`{ items:[{url,w,h}...], layout, gap }`。
//
// 使用示例：
//
//     // 由 canvas.js 或 smart-canvas.js 引入并注册
//     import { MediaEditor } from '/static/js/shared/media/MediaEditor/index.js';
//     MediaEditor.register('classic', { openImageEditor, setImageEditMode, ... });
//
//     // 由外部（未来的 shared/interaction / node registry）调用
//     await MediaEditor.open({ canvasKind:'classic', mode:'crop', source:{ nodeId, imageIndex } });

import { registerModeAdapters } from './registry.js';
import { crop } from './crop.js';
import { mask } from './mask.js';
import { inpaint } from './inpaint.js';
import { gridSplit } from './grid-split.js';
import { gridJoin } from './grid-join.js';

/** 编辑器模式白名单；扩展时同步更新 [[前端兼容合同冻结清单]]。 */
export const MEDIA_EDITOR_MODES = Object.freeze(['crop', 'mask', 'inpaint', 'grid-split', 'grid-join']);

/** canvasKind 白名单；`classic` = canvas.js 经典画布，`smart` = smart-canvas.js 智能画布。 */
export const MEDIA_EDITOR_CANVAS_KINDS = Object.freeze(['classic', 'smart']);

const state = {
  /** @type {Map<string, object>} kind -> adapter */
  adapters: new Map(),
  /** 活跃会话；同一时间只允许一个（rAF 争用防护、[[前端组件化治理方案]] PR-4）。 */
  active: null,
  modes: registerModeAdapters({ crop, mask, inpaint, gridSplit, gridJoin }),
};

function validateOpenArgs(args) {
  if (!args || typeof args !== 'object') {
    throw new Error('MediaEditor.open 需要传入 { canvasKind, mode, source } 参数对象');
  }
  const { canvasKind, mode } = args;
  if (!MEDIA_EDITOR_CANVAS_KINDS.includes(canvasKind)) {
    throw new Error(`MediaEditor.open 未知 canvasKind: ${canvasKind}`);
  }
  if (!MEDIA_EDITOR_MODES.includes(mode)) {
    throw new Error(`MediaEditor.open 未知 mode: ${mode}`);
  }
}

/**
 * 注册 canvasKind 对应的 adapter。adapter 必须提供 `openImageEditor` 与
 * `setImageEditMode`（对齐 canvas.js / smart-canvas.js 现有全局函数语义）。
 *
 * @param {'classic'|'smart'} canvasKind
 * @param {object} adapter
 */
export function register(canvasKind, adapter) {
  if (!MEDIA_EDITOR_CANVAS_KINDS.includes(canvasKind)) {
    throw new Error(`MediaEditor.register 未知 canvasKind: ${canvasKind}`);
  }
  if (!adapter || typeof adapter !== 'object') {
    throw new Error('MediaEditor.register 需要传入 adapter 对象');
  }
  state.adapters.set(canvasKind, adapter);
}

/** 内部查询已注册 adapter（供各 mode 模块访问）。 */
export function _getAdapter(canvasKind) {
  return state.adapters.get(canvasKind) || null;
}

/**
 * 统一入口。返回 Promise；finally 内保证会话释放。
 *
 * @param {object} args
 * @param {'classic'|'smart'} args.canvasKind
 * @param {'crop'|'mask'|'inpaint'|'grid-split'|'grid-join'} args.mode
 * @param {object} args.source                 与 mode 对应的数据源描述
 * @param {(payload:any)=>void} [args.onCommit] 编辑器提交时回调（可选；adapter 侧仍原样触发 saveCanvas / patch）
 * @returns {Promise<{ok:boolean, mode:string, canvasKind:string}>}
 */
export function open(args) {
  validateOpenArgs(args);
  const { canvasKind, mode, source, onCommit } = args;
  const adapter = _getAdapter(canvasKind);
  if (!adapter) {
    return Promise.reject(new Error(`MediaEditor.open 未找到 ${canvasKind} adapter；canvas.js/smart-canvas.js 尚未加载或未 register()`));
  }
  const modeImpl = state.modes[mode];
  if (!modeImpl || typeof modeImpl.open !== 'function') {
    return Promise.reject(new Error(`MediaEditor.open 未知 mode 实现: ${mode}`));
  }
  const session = {
    id: `${canvasKind}:${mode}:${Date.now()}:${Math.random().toString(36).slice(2, 6)}`,
    canvasKind,
    mode,
    source,
    onCommit: typeof onCommit === 'function' ? onCommit : null,
    startedAt: Date.now(),
  };
  state.active = session;
  return Promise.resolve()
    .then(() => modeImpl.open(session, adapter))
    .finally(() => {
      if (state.active === session) state.active = null;
    });
}

/** 是否有活跃会话（供 canvas render 循环挂起判定使用）。 */
export function isOpen() {
  return Boolean(state.active);
}

/** 当前会话描述（read-only），无活跃返回 null。 */
export function current() {
  return state.active ? { ...state.active } : null;
}

/**
 * 公共门面对象。冻结防止意外覆盖。
 */
export const MediaEditor = Object.freeze({
  open,
  register,
  isOpen,
  current,
  MODES: MEDIA_EDITOR_MODES,
  CANVAS_KINDS: MEDIA_EDITOR_CANVAS_KINDS,
});

// 挂到 window 便于 canvas.js / smart-canvas.js 非模块脚本消费（seam 期无构建，
// 现有页面脚本非 ES module）。
if (typeof window !== 'undefined') {
  if (!window.MediaEditor) window.MediaEditor = MediaEditor;
}

export default MediaEditor;
