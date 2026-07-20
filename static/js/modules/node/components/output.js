// modules/node/components/output.js
//
// Registry entry for the `output` node type. Wave 3-I / 前端 PR-7 decision 2
// requires we **认领而非重写**: the body renderer here MUST directly invoke
// the existing legacy function `window.renderOutputGrid` living inside
// `static/js/canvas.js` (not rewrite it).
//
// This file is a native ES module — the registration side-effect happens on
// first import. `canvas.html` loads legacy canvas.js first (classic script),
// then the seam bootstrap imports this module which registers into the
// NodeRenderRegistry. Because canvas.js exposes `renderOutputGrid` on the
// global scope (`window.renderOutputGrid`), the ordering is safe.
//
// Zero build / zero dependency.

import NodeRenderRegistry from '../registry/NodeRenderRegistry.js';
import NodeConfigRegistry from '../registry/NodeConfigRegistry.js';

// Config: default size, port eligibility, status badge visibility.
// Values must match `defaultNodeSize` / `canInput` / `canOutput` /
// `showStatus` branches inside `canvas.js` `renderNode` byte-equivalent.
NodeConfigRegistry.register('output', {
    defaultSize: { w: 460, h: 0 },
    canInput: true,
    canOutput: true,
    hasStatus: false,   // output nodes do not carry runStatus badges
    canvasKind: 'classic',
});

function renderBody(node, opts) {
    const options = opts || {};
    const win = options.window || (typeof window !== 'undefined' ? window : null);
    if (!win || typeof win.renderOutputGrid !== 'function') {
        // In a non-browser test environment we return a minimal skeleton so
        // the seam remains observable. The two-canvas legacy path is not
        // exercised here (this branch triggers only under unit tests).
        return '<div class="output-grid" data-registry-body="output"></div>';
    }
    // 直接调用 canvas.js 中的 renderOutputGrid —— 认领模式（Wave 3-I 决策 2）
    const pendingHtml = ((node && node._pending) || []).map((p) => (
        typeof win.renderPendingOutput === 'function' ? win.renderPendingOutput(p) : ''
    )).join('');
    return win.renderOutputGrid(node, pendingHtml);
}

NodeRenderRegistry.register({
    type: 'output',
    canvasKind: 'classic',
    renderBody,
    describe() {
        return {
            type: 'output',
            legacyImplementation: 'canvas.js::renderOutputGrid',
            claimsLegacy: true,
        };
    },
});

export default { type: 'output', renderBody };
export { renderBody };
