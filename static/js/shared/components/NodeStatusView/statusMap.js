// static/js/shared/components/NodeStatusView/statusMap.js
//
// Wave 3-J 前端 PR-8（收敛版）: 6 canonical status → CSS class + i18n label 映射。
//
// **Canonical 状态值来源（硬约束）**：
//   `app/task/view/provider_view.py::KNOWN_VIEW_STATUSES` frozenset
//     = {"queued", "running", "succeeded", "failed", "cancelled", "waiting_upstream", "rate_limited"}
//
//   **CB-P5-35 承接**(2026-07-24):Provider PR-A(a3565f7 · Wave 3-N.5 Batch 4
//   主线 B)引入 rate_limit 通道时,后端 mapper 加了 `rate_limited` 第 7 项,
//   但前端 seam `CANONICAL_STATUSES` 未同步 → 3 层契约漂移(mapper ↔ 前端
//   canonical 表 ↔ fixture 语料)。本次补齐。
//
// **Legacy alias（视觉契约兼容）**：
//   canvas.js 长期使用 4 值口径 `{queued, running, done, failed}`；`done` 对应
//   canonical `succeeded`。为了让 status badge 迁移前后**视觉字节等价**（含
//   `.node-run-status.done { display:none }` CSS 规则），本表同时导出：
//     - `CANONICAL_STATUSES`：7 canonical（对齐后端 view 层)
//     - `LEGACY_STATUS_ALIASES`：`done` → `succeeded`
//     - `resolveStatus(input)`：先走 alias，再匹配 canonical
//
// 契约：
//   - 零构建 / 零依赖 / 原生 ES module
//   - **只做映射，不做 DOM**（DOM 组装在 index.js）
//   - 未知状态返回 `null`（由调用方决定 fallback 分支）

// Canonical 7 值（严格对齐 KNOWN_VIEW_STATUSES；不允许漂移）。
export const CANONICAL_STATUSES = Object.freeze([
    'queued',
    'running',
    'succeeded',
    'failed',
    'cancelled',
    'waiting_upstream',
    'rate_limited',
]);

// legacy → canonical 别名。仅一条 alias：canvas.js legacy `done` 词面。
// 视觉契约：CSS `.node-run-status.done { display:none }` 依赖 legacy class 名，
// 迁移后仍需保留 `done` class（见 index.js 输出策略）。
export const LEGACY_STATUS_ALIASES = Object.freeze({
    done: 'succeeded',
});

// canonical → { cssClass, labelZh, iconChar } 映射表。
//   - cssClass：写入 `.node-run-status <cssClass>` 的第二个 class 名。
//     * 视觉契约：queued/running/failed 与 canvas.css:220-230 保持一致。
//     * succeeded：canvas.css 中原 `.done` 规则是 `display:none`；我们输出
//       的 class 同时含 `done`（legacy） + `succeeded`（canonical），保证
//       视觉字节等价 —— 见 `index.js::render()`。
//     * cancelled / waiting_upstream：canvas.css 无对应 rule，走灰色兜底
//       （统一为 queued-like 视觉，遵循 view 层"未终态"语义）。
//   - labelZh：中文文案。queued/running/failed 与 canvas.js:6111 map byte-equivalent。
//   - iconChar：icon 字符占位（当前 canvas.js 用 `<span class="dot"></span>`；
//     iconChar 字段为 seam 层预留、当前 index.js 不消费；PR-9/10 若接 lucide
//     icon 再启用）。
export const STATUS_MAP = Object.freeze({
    queued: Object.freeze({
        cssClass: 'queued',
        labelZh: '排队中',
        iconChar: 'clock',
    }),
    running: Object.freeze({
        cssClass: 'running',
        labelZh: '运行中',
        iconChar: 'loader-2',
    }),
    succeeded: Object.freeze({
        cssClass: 'succeeded',
        labelZh: '完成',
        iconChar: 'check',
    }),
    failed: Object.freeze({
        cssClass: 'failed',
        labelZh: '失败',
        iconChar: 'x',
    }),
    cancelled: Object.freeze({
        cssClass: 'cancelled',
        labelZh: '已取消',
        iconChar: 'ban',
    }),
    waiting_upstream: Object.freeze({
        cssClass: 'waiting-upstream',
        labelZh: '等待上游',
        iconChar: 'link',
    }),
    rate_limited: Object.freeze({
        cssClass: 'rate-limited',
        labelZh: '限流中',
        iconChar: 'clock-alert',
    }),
});

/**
 * 把任意输入（canonical 或 legacy 词面）解析为 canonical status。
 * 未知输入返回 `null`（由调用方决定 fallback 分支）。
 */
export function resolveStatus(input) {
    if (input == null) return null;
    const key = String(input);
    if (Object.prototype.hasOwnProperty.call(LEGACY_STATUS_ALIASES, key)) {
        return LEGACY_STATUS_ALIASES[key];
    }
    if (CANONICAL_STATUSES.includes(key)) return key;
    return null;
}

/**
 * 返回 canonical status 对应的映射条目；未知返回 `null`。
 */
export function statusEntry(input) {
    const canonical = resolveStatus(input);
    if (!canonical) return null;
    return STATUS_MAP[canonical] || null;
}

const defaultExport = {
    CANONICAL_STATUSES,
    LEGACY_STATUS_ALIASES,
    STATUS_MAP,
    resolveStatus,
    statusEntry,
};

export default defaultExport;
