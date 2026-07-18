// static/js/shared/media/MediaEditor/mask.js
//
// mode: 'mask' —— 遮罩编辑。
// source shape：{ nodeId: string, imageIndex?: number }
//
// classic 与 smart 均通过 adapter.openImageEditor + setImageEditMode('mask') 进入。

function ensureSource(source) {
  if (!source || typeof source !== 'object' || !source.nodeId) {
    throw new Error("MediaEditor.open({mode:'mask'}) source.nodeId 必填");
  }
  return source;
}

export const mask = Object.freeze({
  open(session, adapter) {
    const source = ensureSource(session.source);
    if (session.canvasKind === 'classic') {
      adapter.openImageEditor(source.nodeId, 'mask');
    } else {
      adapter.openImageEditor(source.nodeId, source.imageIndex || 0);
      if (typeof adapter.setImageEditMode === 'function') {
        adapter.setImageEditMode('mask', true);
      }
    }
    return { ok: true, mode: 'mask', canvasKind: session.canvasKind };
  },
});
