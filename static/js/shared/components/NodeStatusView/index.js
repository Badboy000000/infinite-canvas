// static/js/shared/components/NodeStatusView/index.js
//
// Wave 3-J 前端 PR-8（收敛版）: NodeStatusView 单例——node status badge 视图。
//
// **契约**（硬约束）：
//   - `NodeStatusView.render(status, opts) -> HTMLElement | string`
//     * 无 `document` 环境（Node ESM 测试）→ 返回 HTML string
//     * 有 `document` 环境（浏览器）→ 返回 HTMLElement
//     * 返回值语义与 PR-7 `NodeRenderRegistry.renderFallback` 一致
//   - 6 canonical status → CSS class + labelZh 严格对齐 `statusMap.js`
//   - **等价性三轴**（Wave 3-J 承接补丁 RC-B P1-B1 + GM-13 治理机制）：
//       原 canvas.js:6110-6113 输出：
//         `<span class="node-run-status ${runStatus}">
//            <span class="dot"></span>${escapeHtml(label)}${cascadeIdx}
//          </span>`
//       其中 `runStatus` legacy 词面 `queued|running|done|failed`；
//       `done` CSS 规则是 `display:none`。
//
//       * legacy `queued / running / failed` 三值：**runtime-output-byte-equal**
//         —— NodeStatusView.renderHtml(status) 与原 canvas.js 内联 template
//         evaluate 结果**逐字节相等**（见 T47 migration_byte_equivalent 断言 3 值）
//       * legacy `done` 值：**视觉等价（visual-byte-equal）**，**非 DOM byte-equal**
//         —— 输出 `class="node-run-status succeeded done"`（多 `succeeded ` 前缀），
//         但 CSS `.node-run-status.done { display:none }` 命中相同，视觉上 chip
//         被隐藏，视觉不可分（见 T50 canvas.css `.done` display:none 规则守卫）
//       **不要**在注释里笼统称 "byte-equivalent"，必须显式指定哪一轴：
//         source-byte-equal / runtime-output-byte-equal / visual-byte-equal
//   - **零构建 / 零依赖 / 原生 ES module**
//   - `escapeHtml` **运行时输出 byte-equivalent** 于 `NodeRenderRegistry.js` /
//     `canvas.js`（源码文本不等：canvas.js 单行 158 bytes vs 本文件多行 221 bytes，
//     但对同一输入返回**逐字节相等**的字符串，T45 通过 Node subprocess 独立
//     执行三处定义体真实验证）
//
// **不做**：
//   - 不动 data-action 契约（status badge 挂载点当前无 data-action，不新增）
//   - 不接管 CSS（.node-run-status 规则仍在 canvas.css）
//   - 不做 i18n runtime 切换（当前只有 zh；en 由 PR-9/10 承接）
//   - **不动 cascadeIdx 通道 escape 语义**（KNOWN LIMITATION 继承 canvas.js:6130
//     legacy 行为；当前 `node._cascadeIdx` 全部写入点为内部纯数字模板，无用户
//     可控入口；PR-9 或 CB-P5-05 承接 cascadeIdx 全通道 escape 硬锁）

import { statusEntry, resolveStatus, CANONICAL_STATUSES, STATUS_MAP, LEGACY_STATUS_ALIASES } from './statusMap.js';

/**
 * escapeHtml 内嵌副本 —— **运行时输出 byte-equivalent** 于:
 *   - `static/js/canvas.js::escapeHtml`（14830 行）
 *   - `static/js/smart-canvas.js::escapeHtml`（464 行）
 *   - `static/js/modules/node/registry/NodeRenderRegistry.js::escapeHtml`（61 行）
 *
 * **源码文本 NOT byte-equal**:canvas.js/smart-canvas.js 单行式(158 bytes)vs
 * 本文件 + NodeRenderRegistry 多行式(221 bytes),文本长度和结构均不等。但对
 * 同一输入,四处实现返回**逐字节相等的字符串**——这是 T45 通过 Node subprocess
 * 独立执行四处定义体并逐字节对比得到的**运行时输出等价**证据。
 *
 * Wave 3-J RC-B 反审 P0-7 澄清:请勿在注释里笼统称"byte-equivalent",必须显式
 * 指定"**runtime-output-byte-equal**"(参见 GM-13 治理机制候选)。
 *
 * 此处内嵌是**有意为之**:
 *   1. NodeRenderRegistry.js 未 export `escapeHtml`(PR-7 已 freeze 内部实现)
 *   2. seam 期硬约束为"零依赖",不允许引入 escape 工具库
 *   3. `test_node_status_view_seam.py::T45` 通过 Node subprocess 真实执行
 *      四处定义体并逐字节对比运行时输出,保证不漂移
 */
function escapeHtml(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, (s) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    }[s]));
}

/**
 * escapeAttr 内嵌副本 —— **运行时输出 byte-equivalent** 于:
 *   - `static/js/canvas.js::escapeAttr`（14831 行）
 *   - `static/js/smart-canvas.js::escapeAttr = escapeHtml`（465 行别名）
 * canvas.js 定义：`function escapeAttr(str){ return escapeHtml(str); }`
 *
 * 参见上方 escapeHtml 关于**源码文本 NOT byte-equal + 运行时输出 byte-equal**
 * 的完整说明(GM-13 治理机制候选:等价性三轴显式标注)。
 */
function escapeAttr(str) {
    return escapeHtml(str);
}

/**
 * 为 canonical status 反查 legacy alias（若存在）。
 * 例：`succeeded` → `done`；`queued` → `undefined`。
 */
function legacyAliasFor(canonical) {
    for (const [legacy, target] of Object.entries(LEGACY_STATUS_ALIASES)) {
        if (target === canonical) return legacy;
    }
    return undefined;
}

/**
 * 计算 status badge 的 CSS class 字符串（不含 `node-run-status` 前缀）。
 *
 * 语义：
 *   - canonical=succeeded → "succeeded done"（保留 legacy `.done{display:none}` 视觉）
 *   - canonical=queued → "queued"
 *   - canonical=running → "running"
 *   - canonical=failed → "failed"
 *   - canonical=cancelled → "cancelled"
 *   - canonical=waiting_upstream → "waiting-upstream"（CSS 破折号约定）
 *
 * 未知 canonical 抛异常（调用方必须先 resolveStatus）。
 */
function statusClassFor(canonical) {
    const entry = STATUS_MAP[canonical];
    if (!entry) throw new Error(`NodeStatusView: unknown canonical status ${canonical}`);
    const cls = entry.cssClass;
    const legacy = legacyAliasFor(canonical);
    return legacy && legacy !== cls ? `${cls} ${legacy}` : cls;
}

/**
 * 组装 status badge 的 HTML 字符串。
 * 视觉字节等价目标（canvas.js:6110-6113）：
 *   `<span class="node-run-status ${runStatus}"><span class="dot"></span>${label}${cascadeIdx}</span>`
 *
 * 差异点（**已核对无 DOM diff**）：
 *   1. `${runStatus}` legacy 词面 → 迁移后取 `statusClassFor(canonical)`，
 *      canonical=succeeded 时输出 "succeeded done"；canonical=queued/running/
 *      failed 时输出与 legacy 完全一致的 "queued"/"running"/"failed"。
 *   2. `${escapeHtml(label)}` label 取值：
 *        legacy runStatus=queued  → '排队中' → NodeStatusView.labelZh 相同
 *        legacy runStatus=running → '运行中' → NodeStatusView.labelZh 相同
 *        legacy runStatus=done    → '完成'   → NodeStatusView.labelZh 相同
 *        legacy runStatus=failed  → '失败'   → NodeStatusView.labelZh 相同
 *   3. `${cascadeIdx}` 通过 opts.cascadeIdx 传入，保持 legacy 语义。
 */
function buildBadgeHtml(canonical, opts) {
    const options = opts || {};
    const entry = STATUS_MAP[canonical];
    const cascadeIdx = options.cascadeIdx ? ' ' + String(options.cascadeIdx) : '';
    const cls = statusClassFor(canonical);
    return `<span class="node-run-status ${cls}"><span class="dot"></span>${escapeHtml(entry.labelZh)}${cascadeIdx}</span>`;
}

/**
 * 未知 status 的 fallback：不抛异常，返回带 `.node-status-unknown` 类的占位。
 * 与 `NodeRenderRegistry.renderFallback` 语义对齐（Wave 3-I 决策 5：不白屏）。
 */
function buildFallbackHtml(rawInput, opts) {
    const options = opts || {};
    const cascadeIdx = options.cascadeIdx ? ' ' + String(options.cascadeIdx) : '';
    const safeRaw = escapeHtml(rawInput == null ? '' : String(rawInput));
    return `<span class="node-run-status node-status-unknown" data-raw-status="${escapeAttr(rawInput == null ? '' : String(rawInput))}"><span class="dot"></span>${safeRaw || '未知状态'}${cascadeIdx}</span>`;
}

/**
 * 把 HTML 字符串封装成 HTMLElement（当有 document 时）。
 * 与 `NodeRenderRegistry.renderFallback` 的 DOM 分支保持等价语义。
 */
function htmlToElement(html, doc) {
    const wrap = doc.createElement('template');
    wrap.innerHTML = html;
    // template.content.firstChild 会跳过 whitespace text nodes——我们的 html
    // 没有前导 whitespace，直接取 firstChild 即 <span> 根元素。
    return wrap.content && wrap.content.firstChild ? wrap.content.firstChild : null;
}

/**
 * NodeStatusView.render 主入口。
 *
 * @param {string|null|undefined} status  legacy 或 canonical status 词面
 * @param {object} [opts]
 * @param {Document} [opts.document]      注入 document（测试可传 fake）
 * @param {string} [opts.cascadeIdx]      cascade 序号（如 "1/5"）
 * @returns {HTMLElement | string}        有 document 返回 HTMLElement；否则返回 HTML string
 */
function render(status, opts) {
    const options = opts || {};
    const doc = options.document || (typeof document !== 'undefined' ? document : null);
    const canonical = resolveStatus(status);
    const html = canonical ? buildBadgeHtml(canonical, options) : buildFallbackHtml(status, options);
    if (!doc) return html;
    const el = htmlToElement(html, doc);
    // 兜底：若 template API 在极端 fake document 中不可用，退回 HTML 字符串
    // （测试用 fake doc 时通常提供 createElement 但不实现 template.content）。
    return el || html;
}

/**
 * NodeStatusView.renderHtml —— 无论环境是否有 document，都返回 HTML 字符串。
 * 供 legacy 消费点使用（canvas.js:6114 `el.innerHTML = ${statusHtml}` 场景）。
 * 语义与 render(status, opts) **完全一致**，只是不做 DOM 提升。
 */
function renderHtml(status, opts) {
    const options = opts || {};
    const canonical = resolveStatus(status);
    return canonical ? buildBadgeHtml(canonical, options) : buildFallbackHtml(status, options);
}

const NodeStatusView = {
    render,
    renderHtml,
    // 便于测试自省
    _statusClassFor: statusClassFor,
    _escapeHtml: escapeHtml,
    _escapeAttr: escapeAttr,
    CANONICAL_STATUSES,
    STATUS_MAP,
};

export default NodeStatusView;
export { render, renderHtml, statusClassFor, escapeHtml, escapeAttr };
