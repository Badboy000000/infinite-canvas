// static/js/shared/media/MediaEditor/grid-join.js
//
// mode: 'grid-join' —— 宫格拼接（智能画布"整个分组为数据源"契约）。
//
// source shape（[[前端组件化治理实施计划与PR清单]] PR-4 冻结）：
//   {
//     items: [{ url: string, w?: number, h?: number, ... }],
//     layout?: { rows?: number, cols?: number },
//     gap?:   number,
//     // 兼容调起方：从分组打开时携带 groupId + nodeId 便于 adapter 定位
//     groupId?: string,
//     nodeId?:  string,
//     imageIndex?: number,
//   }
//
// classic 画布不参与 grid-join（当前实现只在 smart-canvas 内）。若 classic
// 需要 grid-join，adapter 在 register 时不提供该能力即可 —— MediaEditor
// 在此显式失败提示，供上层降级处理。

/** grid-join source 字段冻结契约（供测试快照断言）。 */
export const GRID_JOIN_SOURCE_FIELDS = Object.freeze([
  'items',
  'layout',
  'gap',
  'groupId',
  'nodeId',
  'imageIndex',
]);

/** items 元素字段冻结契约。 */
export const GRID_JOIN_ITEM_FIELDS = Object.freeze([
  'url',
  'w',
  'h',
]);

function validateSource(source) {
  if (!source || typeof source !== 'object') {
    throw new Error("MediaEditor.open({mode:'grid-join'}) source 参数必填");
  }
  if (!Array.isArray(source.items)) {
    throw new Error("MediaEditor.open({mode:'grid-join'}) source.items 必须为数组");
  }
  if (source.items.length < 2) {
    throw new Error('分组至少需要 2 张图片才能宫格拼接');
  }
  for (const item of source.items) {
    if (!item || typeof item !== 'object' || !item.url) {
      throw new Error("MediaEditor.open({mode:'grid-join'}) source.items[].url 必填");
    }
  }
  return source;
}

export const gridJoin = Object.freeze({
  GRID_JOIN_SOURCE_FIELDS,
  GRID_JOIN_ITEM_FIELDS,
  open(session, adapter) {
    const source = validateSource(session.source);
    if (session.canvasKind !== 'smart') {
      // 经典画布现阶段无 grid-join；显式失败以便调起方降级（PR-4 明确不做）。
      throw new Error("mode='grid-join' 目前仅智能画布支持（seam 期 canvasKind='smart'）");
    }
    // smart-canvas 端的 grid-join 由 openGroupGridJoin(group) 承接（内部会
    // 调 openImageEditor + setImageEditMode('grid') + setGridOperationMode('join')）。
    // adapter.openGridJoin(source) 由 smart-canvas.js 侧实现，参数校验对齐 source 契约。
    if (typeof adapter.openGridJoin === 'function') {
      adapter.openGridJoin(source);
    } else if (typeof adapter.openImageEditor === 'function') {
      // 兜底：若 adapter 尚未实现专用 openGridJoin，退化到旧路径
      // （openImageEditor + setImageEditMode + setGridOperationMode）。
      const anchor = source.nodeId || (source.items[0] && source.items[0].nodeId);
      if (!anchor) throw new Error("grid-join 需要 source.nodeId 或第一 item.nodeId 作为锚点");
      adapter.openImageEditor(anchor, source.imageIndex || 0);
      if (typeof adapter.setImageEditMode === 'function') adapter.setImageEditMode('grid', true);
      if (typeof adapter.setGridOperationMode === 'function') adapter.setGridOperationMode('join');
    } else {
      throw new Error('smart-canvas adapter 未提供 openGridJoin / openImageEditor');
    }
    return { ok: true, mode: 'grid-join', canvasKind: session.canvasKind, itemCount: source.items.length };
  },
});
