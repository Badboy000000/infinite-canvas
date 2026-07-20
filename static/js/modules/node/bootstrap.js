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
            // classic canvas create menu
            'menuAddImage', 'menuAddPrompt', 'menuAddLoop', 'menuAddLLM',
            'menuAddGenerator', 'menuAddMsgen', 'menuAddVideo', 'menuAddRh',
            'menuAddComfy', 'menuAddLtxDirector', 'menuAddOutput',
            // smart canvas topbar / menu
            'backToCanvasList', 'openSmartCanvasShortcuts', 'openSmartCanvasLog',
            'closeSmartWorkflowTransferModal', 'closeSmartCanvasLog',
            'closeSmartCanvasShortcuts',
            // ambient
            'closeOutputLightbox', 'closeWorkflowTransferModal',
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
