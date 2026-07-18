// static/js/shared/media/MediaEditor/grid-split.js
//
// mode: 'grid-split' —— 宫格切分。
// source shape：{ nodeId: string, imageIndex?: number }

function ensureSource(source) {
  if (!source || typeof source !== 'object' || !source.nodeId) {
    throw new Error("MediaEditor.open({mode:'grid-split'}) source.nodeId 必填");
  }
  return source;
}

export const gridSplit = Object.freeze({
  open(session, adapter) {
    const source = ensureSource(session.source);
    if (session.canvasKind === 'classic') {
      adapter.openImageEditor(source.nodeId, 'grid');
    } else {
      adapter.openImageEditor(source.nodeId, source.imageIndex || 0);
      if (typeof adapter.setImageEditMode === 'function') {
        adapter.setImageEditMode('grid', true);
      }
      // smart-canvas 内 `setGridOperationMode('split')` 保证进入切分子模式。
      if (typeof adapter.setGridOperationMode === 'function') {
        adapter.setGridOperationMode('split');
      }
    }
    return { ok: true, mode: 'grid-split', canvasKind: session.canvasKind };
  },
});
