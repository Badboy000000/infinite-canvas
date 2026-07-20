// modules/node/components/ltxDirector.js
//
// Registry entry for the `ltxDirector` node type. Wave 3-I / 前端 PR-7 决策 2
// requires 认领而非重写: this file only registers a wrapper that directly
// invokes the legacy body renderer `window.renderLTXDirectorBody` from
// canvas.js (Line 11135 at baseline `c3f2d83`).
//
// Zero build / zero dependency.

import NodeRenderRegistry from '../registry/NodeRenderRegistry.js';
import NodeConfigRegistry from '../registry/NodeConfigRegistry.js';

NodeConfigRegistry.register('ltxDirector', {
    defaultSize: { w: 1000, h: 800 },
    canInput: true,
    canOutput: true,
    hasStatus: true,    // runStatus 徽标显示
    canvasKind: 'classic',
});

function renderBody(node, opts) {
    const options = opts || {};
    const win = options.window || (typeof window !== 'undefined' ? window : null);
    if (!win || typeof win.renderLTXDirectorBody !== 'function') {
        return '<div class="ltx-director-body" data-registry-body="ltxDirector"></div>';
    }
    // 直接调用 canvas.js:11135 renderLTXDirectorBody —— 认领模式
    return win.renderLTXDirectorBody(node);
}

NodeRenderRegistry.register({
    type: 'ltxDirector',
    canvasKind: 'classic',
    renderBody,
    describe() {
        return {
            type: 'ltxDirector',
            legacyImplementation: 'canvas.js::renderLTXDirectorBody',
            claimsLegacy: true,
        };
    },
});

export default { type: 'ltxDirector', renderBody };
export { renderBody };
