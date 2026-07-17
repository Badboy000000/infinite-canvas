// static/js/shared/api-client/endpoints.js
//
// Seam-period 前端 API 端点常量表（[[前端兼容合同冻结清单]] §7 逐条对齐）。
//
// 收敛原则（[[前端组件化治理实施计划与PR清单]] PR-2、[[技术开发规则与工程实施规范]]）：
//   1. 只做 URL 常量提取，禁止改路径、禁止改 method、禁止改 body 字段名（§7.8）。
//   2. 每个常量注释指回 `docs/frontend-freeze/compat-contract.md` §7 行号；行号漂移在
//      本 PR §7 复审报告中登记，不重新自造。
//   3. 若 §7 行号已因源码演进过期（首批冻结在 2026-07-16，之后 canvas / smart-canvas
//      业务代码有较大重写），在常量注释里附源码 grep 事实 `src=file:line`。
//   4. 常量命名规范：全大写下划线，动词_对象_限定语（`LIST_CANVASES` / `GET_CANVAS`
//      / `PUT_CANVAS` / `POST_CANVAS_META` 等）；参数化路径以函数形式暴露。
//
// 本文件当前只覆盖 seam 期首批迁移点（前端 PR-2）。后续 PR-3/4/5 承接剩余
// endpoints；每次追加必须同步 §7 引用。CB-01 后续义务：全表复审见 §7 复审报告。

// ---------------------------------------------------------------------------
// Canvas / 画布列表
// ---------------------------------------------------------------------------

/**
 * 画布清单读取。
 * compat-contract §7.4 `canvas-list.js:50`（源码事实：`canvas-list.js:183`；GET）。
 * 后端路由：`main.py` `@app.get("/api/canvases")`。
 */
export const LIST_CANVASES = '/api/canvases';

/**
 * 回收站清单读取。
 * compat-contract §7.4 `canvas-list.js:64`（源码事实：`canvas-list.js:887`、`:908`；GET）。
 * 后端路由：`main.py` `@app.get("/api/canvases/trash")`。
 */
export const LIST_CANVASES_TRASH = '/api/canvases/trash';

/**
 * 单个画布读取 / 更新（参数化）。
 * compat-contract §7.4 `canvas-list.js:221`（GET）/ `canvas-list.js:232`（PUT）/
 * `canvas-list.js:273`（DELETE）；源码事实：`canvas-list.js:595`、`:874`、`:750`。
 * 后端路由：`main.py` `@app.get/put/delete("/api/canvases/{canvas_id}")`。
 *
 * @param {string} canvasId
 * @returns {string}
 */
export function CANVAS_BY_ID(canvasId) {
  return `/api/canvases/${encodeURIComponent(canvasId)}`;
}

// ---------------------------------------------------------------------------
// Provider 设置
// ---------------------------------------------------------------------------

/**
 * Provider 清单读取。
 * compat-contract §7.3 `api-settings.js:2870`（源码事实：`api-settings.js:3705`；GET）。
 * 后端路由：`main.py` `@app.get("/api/providers")`。
 */
export const LIST_PROVIDERS = '/api/providers';

// ---------------------------------------------------------------------------
// CLI 状态（Jimeng / Codex / Gemini-CLI）
// ---------------------------------------------------------------------------

/**
 * Jimeng CLI 状态。
 * compat-contract §7.3 `api-settings.js:2654`（GET；源码事实一致）。
 * 后端路由：`main.py` `@app.get("/api/jimeng/status")`。
 */
export const JIMENG_STATUS = '/api/jimeng/status';

/**
 * Codex CLI 状态。
 * compat-contract §7.3 `api-settings.js:2773`（GET；源码事实一致）。
 * 后端路由：`main.py` `@app.get("/api/codex/status")`。
 */
export const CODEX_STATUS = '/api/codex/status';

/**
 * Gemini CLI 状态。
 * compat-contract §7.3 `api-settings.js:2824`（GET；源码事实一致，CB-01 已订正）。
 * 后端路由：`main.py` `@app.get("/api/gemini-cli/status")`。
 */
export const GEMINI_CLI_STATUS = '/api/gemini-cli/status';

// ---------------------------------------------------------------------------
// ComfyUI 实例
// ---------------------------------------------------------------------------

/**
 * ComfyUI 实例读写。
 * compat-contract §7.5 `comfyui-settings.js:208`（GET）/ `:241`（PUT）——CB-01 已订正。
 * 后端路由：`main.py` `@app.get/put("/api/comfyui/instances")`。
 */
export const COMFYUI_INSTANCES = '/api/comfyui/instances';
