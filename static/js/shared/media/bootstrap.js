// static/js/shared/media/bootstrap.js
//
// 非模块脚本（`<script src>`），把 shared/media/MediaEditor + shared/api-client/fileApi
// + shared/media/legacyUrlResolver 通过动态 ESM import 暴露到 window，
// 供仍是全局 `<script>` 加载的 canvas.js / smart-canvas.js（seam 期无构建）消费。
//
// [[前端组件化治理实施计划与PR清单]] PR-4；[[前端组件化治理方案]] shared/media/MediaEditor 章节。
//
// 使用（canvas.html / smart-canvas.html）：
//   <script src="/static/js/shared/media/bootstrap.js"></script>
//   <script src="/static/js/canvas.js"></script>
//
// canvas.js / smart-canvas.js 内的适配代码：
//   window.MediaEditorReady.then(() => {
//     window.MediaEditor.register('classic', { openImageEditor, setImageEditMode });
//   });

(function installMediaBootstrap(global) {
  'use strict';

  if (global.MediaEditorReady) return; // 幂等（同页多次 include 兜底）

  const moduleUrls = {
    editor: '/static/js/shared/media/MediaEditor/index.js',
    fileApi: '/static/js/shared/api-client/domains/fileApi.js',
    resolver: '/static/js/shared/media/legacyUrlResolver.js',
  };

  const ready = Promise.all([
    import(moduleUrls.editor),
    import(moduleUrls.fileApi),
    import(moduleUrls.resolver),
  ]).then(([editorMod, fileApiMod, resolverMod]) => {
    global.MediaEditor = editorMod.MediaEditor || editorMod.default;
    global.MediaEditorModes = editorMod.MEDIA_EDITOR_MODES;
    global.MediaEditorCanvasKinds = editorMod.MEDIA_EDITOR_CANVAS_KINDS;
    global.fileApi = fileApiMod.fileApi;
    global.LegacyUrlResolver = Object.freeze({
      resolve: resolverMod.resolveLegacyUrl,
      unwrap: resolverMod.unwrapMediaPreviewUrl,
      mediaPreview: resolverMod.buildMediaPreviewUrl,
      downloadOutput: resolverMod.buildDownloadOutputUrl,
      isLocal: resolverMod.isLocalMediaUrl,
    });
    return {
      MediaEditor: global.MediaEditor,
      fileApi: global.fileApi,
      LegacyUrlResolver: global.LegacyUrlResolver,
    };
  }).catch(err => {
    // seam 期严格容错：bootstrap 失败时不阻断页面渲染，仅打印警告；
    // canvas.js 依然可以走旧的 openImageEditor 全局函数（wrapper 内部有回退）。
    if (global.console) global.console.error('[MediaEditor bootstrap] failed:', err);
    throw err;
  });

  global.MediaEditorReady = ready;
})(typeof window !== 'undefined' ? window : this);
