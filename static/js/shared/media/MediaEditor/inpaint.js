// static/js/shared/media/MediaEditor/inpaint.js
//
// mode: 'inpaint' —— 涂抹重绘（brush 模式）。
// source shape：{ nodeId: string, imageIndex?: number }
//
// canvas.js / smart-canvas.js 内部命名为 `brush` 模式；本 seam 门面保留
// PR-4 章节声明的 5 种 mode 名称对外。

function ensureSource(source) {
  if (!source || typeof source !== 'object' || !source.nodeId) {
    throw new Error("MediaEditor.open({mode:'inpaint'}) source.nodeId 必填");
  }
  return source;
}

export const inpaint = Object.freeze({
  open(session, adapter) {
    const source = ensureSource(session.source);
    if (session.canvasKind === 'classic') {
      adapter.openImageEditor(source.nodeId, 'brush');
    } else {
      adapter.openImageEditor(source.nodeId, source.imageIndex || 0);
      if (typeof adapter.setImageEditMode === 'function') {
        adapter.setImageEditMode('brush', true);
      }
    }
    return { ok: true, mode: 'inpaint', canvasKind: session.canvasKind };
  },
});
