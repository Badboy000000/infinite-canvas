// static/js/shared/media/MediaEditor/crop.js
//
// mode: 'crop' —— 裁剪。
// source shape：
//   - classic：{ nodeId: string, imageIndex?: number }
//   - smart:   { nodeId: string, imageIndex?: number }
//
// 语义：调用 adapter.openImageEditor(nodeId, 'crop')；实际编辑器逻辑仍在
// canvas.js / smart-canvas.js（`beginCropDrag` / `imageEditMode`）内运行，
// 保持 rAF 挂起 / pending 挂起 / touch-mouse skip 契约。

function ensureNodeId(source) {
  if (!source || typeof source !== 'object' || !source.nodeId) {
    throw new Error("MediaEditor.open({mode:'crop'}) source.nodeId 必填");
  }
  return source;
}

export const crop = Object.freeze({
  open(session, adapter) {
    const source = ensureNodeId(session.source);
    if (session.canvasKind === 'classic') {
      // classic: openImageEditor(nodeId, initialMode='crop')
      const initialMode = source.mode || 'crop';
      adapter.openImageEditor(source.nodeId, initialMode);
    } else {
      // smart: openImageEditor(nodeId, imageIndex=0) + setImageEditMode('crop')
      adapter.openImageEditor(source.nodeId, source.imageIndex || 0);
      if (typeof adapter.setImageEditMode === 'function') {
        adapter.setImageEditMode('crop', true);
      }
    }
    return { ok: true, mode: 'crop', canvasKind: session.canvasKind };
  },
});
