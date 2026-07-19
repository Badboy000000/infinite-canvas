// static/js/shared/stores/canvasMetaStore.js
//
// 前端 PR-5：Canvas meta store（[[前端组件化治理实施计划与PR清单]] PR-5）。
//
// 语义：只承接 Canvas **元数据** 订阅面：title / icon / pinned / color / owner / updated_at / base_updated_at。
// **不含** nodes / connections / viewport 内容体（那些由前端 PR-6 canvasEditStore 承接）。
//
// 消费方：canvas-list 页 refetch 后刷新卡片；canvas / smart-canvas 页保存后更新自身 meta。
// 冻结要点：
//   - `base_updated_at` 字段名不改（compat-contract §11 冻结）。
//   - `client_id` 语义仍由 canvas.js / smart-canvas.js 侧顶层 CLIENT_ID 常量承担；本 store 不参与自我识别。

import { createStore } from './_createStore.js';

export const CANVAS_META_FIELDS = Object.freeze([
  'id', 'title', 'icon', 'pinned', 'color', 'owner', 'kind',
  'updated_at', 'base_updated_at', 'project',
]);

/**
 * 只保留白名单字段（防御性；防止内容体误落 meta）。
 */
function pickMeta(input) {
  if (!input || typeof input !== 'object') return null;
  const out = {};
  CANVAS_META_FIELDS.forEach(k => { if (k in input) out[k] = input[k]; });
  return out;
}

export const canvasMetaStore = createStore({
  name: 'canvasMeta',
  initialState: {
    // canvasId → meta 快照
    byId: {},
    // 最近关注的 canvasId（可选）
    activeId: '',
  },
  fetcher: null, // meta 由页面主动写入 / 从服务端响应中提取，不做统一 refetch
});

/**
 * 页面侧写入 meta（如 canvas-list 拉到画布卡片列表后调用）。
 */
export function upsertCanvasMeta(meta, reason = 'upsert') {
  const picked = pickMeta(meta);
  if (!picked || !picked.id) return;
  const byId = { ...canvasMetaStore.state.byId, [picked.id]: { ...(canvasMetaStore.state.byId[picked.id] || {}), ...picked } };
  canvasMetaStore.setState({ byId }, reason);
}

/**
 * 批量 upsert（canvas-list 页初始化时 O(1) 载入）。
 */
export function upsertManyCanvasMeta(list, reason = 'upsert-many') {
  if (!Array.isArray(list)) return;
  const byId = { ...canvasMetaStore.state.byId };
  list.forEach(item => {
    const picked = pickMeta(item);
    if (picked && picked.id) byId[picked.id] = { ...(byId[picked.id] || {}), ...picked };
  });
  canvasMetaStore.setState({ byId }, reason);
}

export function setActiveCanvas(id, reason = 'set-active') {
  canvasMetaStore.setState({ activeId: id || '' }, reason);
}
