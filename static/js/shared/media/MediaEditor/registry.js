// static/js/shared/media/MediaEditor/registry.js
//
// mode 实现登记表。open() 时由 index.js 查表分发。

export function registerModeAdapters({ crop, mask, inpaint, gridSplit, gridJoin }) {
  return Object.freeze({
    'crop': crop,
    'mask': mask,
    'inpaint': inpaint,
    'grid-split': gridSplit,
    'grid-join': gridJoin,
  });
}
