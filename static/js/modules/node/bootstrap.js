// modules/node/bootstrap.js
//
// Non-module bootstrap for the NodeRenderRegistry / NodeConfigRegistry seam.
// Registered as a plain `<script>` tag by canvas.html / smart-canvas.html and
// dynamically imports the ES module registrations. Mirrors the pattern used
// by `static/js/shared/media/bootstrap.js` (前端 PR-4) and
// `static/js/shared/stores/bootstrap.js` (前端 PR-5).
//
// Effects:
//   - Registers `output` / `ltxDirector` / `rh` into NodeRenderRegistry and
//     NodeConfigRegistry via side-effect imports.
//   - Installs `data-action` delegation on `document` for the top-level
//     toolbar / topbar / menu buttons (Wave 3-I 决策 6).
//   - Exposes `window.NodeRenderRegistry`, `window.NodeConfigRegistry` and
//     `window.actionBus` for legacy code and tests to introspect.
//   - Fires `window` custom event `node-registry-ready` when import chain
//     resolves so canvas.js can consume the seam if needed.
//
// Zero build / zero dependency. All URLs are relative — the browser resolves
// them via native ESM import from the script's own origin.
(function bootstrapNodeRegistry() {
    if (typeof window === 'undefined' || typeof document === 'undefined') return;
    if (window.__nodeRegistryBootstrapped) return;
    window.__nodeRegistryBootstrapped = true;
    const base = '/static/js/modules/node/';
    Promise.all([
        import('/static/js/modules/node/registry/NodeRenderRegistry.js'),
        import('/static/js/modules/node/registry/NodeConfigRegistry.js'),
        import('/static/js/modules/node/components/output.js'),
        import('/static/js/modules/node/components/ltxDirector.js'),
        import('/static/js/modules/node/components/rh.js'),
        import('/static/js/shared/interaction/action-bus.js'),
    ]).then(([renderMod, configMod, _out, _ltx, _rh, busMod]) => {
        const NodeRenderRegistry = renderMod && renderMod.default ? renderMod.default : renderMod;
        const NodeConfigRegistry = configMod && configMod.default ? configMod.default : configMod;
        const actionBus = busMod && busMod.default ? busMod.default : busMod;
        window.NodeRenderRegistry = NodeRenderRegistry;
        window.NodeConfigRegistry = NodeConfigRegistry;
        window.actionBus = actionBus;
        // Install document-level `data-action` delegation.
        actionBus.install(document);
        // Auto-bind the toolbar / topbar / menu handler names to their
        // existing global functions. Buttons carrying `data-action="foo"`
        // will call `window.foo()`. Handlers missing from the current page
        // are silently skipped (canvas.html vs smart-canvas.html have
        // different handler sets).
        actionBus.autoBindLegacyGlobals([
            // classic canvas toolbar
            'toggleQuickToolbar',
            'addImageNode', 'addPromptNode', 'addLoopNode', 'addLLMNode',
            'addGeneratorNode', 'addMsGenNode', 'addVideoNode', 'addRhNode',
            'addComfyNode', 'addLTXDirectorNode', 'addOutputNode',
            'groupSelectedImages',
            'openCanvasLog',
            // classic canvas create menu — HTML 用 `data-action="menuAdd"
            // data-action-arg="image|prompt|..."`，action-bus.js 会 split 逗号
            // 分隔 arg 后调 `menuAdd(type)`（canvas.js:3543 参数分发实现）。
            // 承接补丁（Wave 3-I RC 反审 P0-1）：原列表 11 个 `menuAddImage` /
            // `menuAddPrompt` / ... 是不存在的函数名，autoBind 会静默 skip，
            // 导致 11 个 createMenu 按钮全部失效。修复为唯一存在的 `menuAdd`。
            'menuAdd',
            // smart canvas topbar buttons — HTML data-action= 命名实际存在的
            // 三个 handler（backToCanvasList / openSmartCanvasShortcuts /
            // openSmartCanvasLog），下方 close* 系列在 HTML 中仍以内联
            // `onclick=` 使用（未迁移），承接补丁 P2 清理已删除死名 5 个：
            // closeSmartWorkflowTransferModal / closeSmartCanvasLog /
            // closeSmartCanvasShortcuts / closeOutputLightbox /
            // closeWorkflowTransferModal（保留 onclick 即可，无需 autoBind）。
            'backToCanvasList', 'openSmartCanvasShortcuts', 'openSmartCanvasLog',
        ]);
        try {
            window.dispatchEvent(new CustomEvent('node-registry-ready', {
                detail: {
                    types: NodeRenderRegistry.list(),
                    aliases: NodeConfigRegistry.listAliases(),
                }
            }));
        } catch (_err) { /* ignore */ }
    }).catch((err) => {
        if (typeof console !== 'undefined' && console.error) {
            console.error('[node-registry] bootstrap failed', err);
        }
    });
})();
