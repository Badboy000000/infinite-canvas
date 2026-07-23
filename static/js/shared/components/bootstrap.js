// static/js/shared/components/bootstrap.js
//
// Wave 3-N.6 Batch 1 主线 B · 前端 PR-8 (候选 A) · SharedComponents bootstrap.
//
// 非模块脚本(`<script src>`),通过动态 ESM `import()` 装配以下 9 个组件并挂到
// `window.SharedComponents`,同时暴露 `window.SharedComponentsReady`(Promise)
// 供 canvas.js / smart-canvas.js 等 non-module 脚本消费。
//
// 结构:
//   window.SharedComponents = {
//     Modal, Toast, Tooltip, Dropdown, Splitter, Panel,   // shared/components/
//     AssetSidePanel, ProviderSelector, ModelSelector,    // modules/asset,modules/provider (有状态)
//   }
//   window.SharedComponentsReady: Promise<SharedComponents>
//
// **单飞标记**(参照 modules/node/bootstrap.js pattern):`window.__sharedComponentsBootstrapped`
// 防止 HTML 里重复 include 造成双装配。
//
// 使用(canvas.html / smart-canvas.html / asset-manager.html / api-settings.html /
//        comfyui-settings.html):
//   <script src="/static/js/shared/components/bootstrap.js"></script>
//   <!-- 后续 canvas.js 内: window.SharedComponentsReady.then(sc => sc.Modal.open(...)) -->
//
// 零构建 / 零依赖。所有 URL 相对 origin,浏览器原生 ESM 解析。

(function installSharedComponentsBootstrap(global) {
    'use strict';

    if (typeof global === 'undefined') return;
    if (global.__sharedComponentsBootstrapped) return;
    global.__sharedComponentsBootstrapped = true;

    const urls = {
        Modal: '/static/js/shared/components/Modal/index.js',
        Toast: '/static/js/shared/components/Toast/index.js',
        Tooltip: '/static/js/shared/components/Tooltip/index.js',
        Dropdown: '/static/js/shared/components/Dropdown/index.js',
        Splitter: '/static/js/shared/components/Splitter/index.js',
        Panel: '/static/js/shared/components/Panel/index.js',
        AssetSidePanel: '/static/js/modules/asset/AssetSidePanel/index.js',
        ProviderSelector: '/static/js/modules/provider/ProviderSelector/index.js',
        ModelSelector: '/static/js/modules/provider/ModelSelector/index.js',
    };

    const ready = Promise.all(Object.keys(urls).map((key) => (
        import(urls[key]).then((mod) => [key, (mod && mod.default) ? mod.default : mod])
    ))).then((entries) => {
        const sc = {};
        entries.forEach(([k, v]) => { sc[k] = v; });
        global.SharedComponents = Object.freeze(sc);
        return global.SharedComponents;
    }).catch((err) => {
        if (global.console && global.console.error) {
            global.console.error('[SharedComponents bootstrap] failed:', err);
        }
        throw err;
    });

    global.SharedComponentsReady = ready;
})(typeof window !== 'undefined' ? window : this);
