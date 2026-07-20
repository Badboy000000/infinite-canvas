// modules/node/components/rh.js
//
// Registry entry for the `rh` (RunningHub) node type. Wave 3-I / 前端 PR-7
// 决策 2 requires 认领而非重写: this file only registers a wrapper that
// directly invokes the legacy body renderer `window.renderRhBody` from
// canvas.js (Line 9360 at baseline `c3f2d83`).
//
// Zero build / zero dependency.

import NodeRenderRegistry from '../registry/NodeRenderRegistry.js';
import NodeConfigRegistry from '../registry/NodeConfigRegistry.js';

NodeConfigRegistry.register('rh', {
    defaultSize: { w: 430, h: 0 },
    canInput: true,
    canOutput: true,
    hasStatus: true,    // runStatus 徽标显示
    canvasKind: 'classic',
});

function renderBody(node, opts) {
    const options = opts || {};
    const win = options.window || (typeof window !== 'undefined' ? window : null);
    if (!win || typeof win.renderRhBody !== 'function') {
        return '<div class="rh-body" data-registry-body="rh"></div>';
    }
    // 直接调用 canvas.js:9360 renderRhBody —— 认领模式
    return win.renderRhBody(node);
}

NodeRenderRegistry.register({
    type: 'rh',
    canvasKind: 'classic',
    renderBody,
    describe() {
        return {
            type: 'rh',
            legacyImplementation: 'canvas.js::renderRhBody',
            claimsLegacy: true,
        };
    },
});

export default { type: 'rh', renderBody };
export { renderBody };
