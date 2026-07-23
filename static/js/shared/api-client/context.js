// static/js/shared/api-client/context.js
//
// Wave 3-N.6 Batch 3 主线 B · 前端 PR-9 · FrontRequestContext.
//
// 前端等价物,对齐后端 `app/identity/request_context.RequestContext`(9 字段) —— 但
// 前端只承载**发送侧 6 字段**:clientId / legacyUserKey / workspaceId / projectId /
// requestId / authMode。后端字段 `ip` / `user_agent` / `x_user_id` 不由前端承载。
//
// **发送 headers 契约**(硬约束 · [[前端组件化治理实施计划与PR清单]] §PR-9):
//
//   toHeaders() 序列化到 headers dict:
//     - `X-Client-Id`:clientId(非空)
//     - `X-Workspace-Id`:workspaceId(非空)
//     - `X-Project-Id`:projectId(非空)
//
//   **不写**:
//     - `X-User-Id`:legacy 兼容层保留,不由本 PR 注入(硬约束 · 保留 cookie / query 通道)
//     - `X-Request-Id`:响应侧回读(PR-BE-02 middleware 语义 · main.py::RequestContextMiddleware)
//
//   null / undefined / 空字符串字段不产生空 header(避免下游误判)。

/**
 * FrontRequestContext:前端只读 identity 快照。
 *
 * 与后端 `RequestContext` 字段命名对齐(camelCase 版),但字段范围窄:
 * 后端负责 `ip` / `user_agent` / `x_user_id` 派生(自 middleware 解析请求),
 * 前端只承担 identity 发送。
 */
export class FrontRequestContext {
  /**
   * @param {object} fields
   * @param {string|null} [fields.clientId]
   * @param {string|null} [fields.legacyUserKey]
   * @param {string|null} [fields.workspaceId]
   * @param {string|null} [fields.projectId]
   * @param {string|null} [fields.requestId]
   * @param {string}      [fields.authMode]  'anonymous_or_legacy' | 'legacy_alias' | 'authenticated_user'
   */
  constructor(fields = {}) {
    this.clientId = fields.clientId != null ? String(fields.clientId) : null;
    this.legacyUserKey = fields.legacyUserKey != null ? String(fields.legacyUserKey) : null;
    this.workspaceId = fields.workspaceId != null ? String(fields.workspaceId) : null;
    this.projectId = fields.projectId != null ? String(fields.projectId) : null;
    this.requestId = fields.requestId != null ? String(fields.requestId) : null;
    this.authMode = String(fields.authMode || 'anonymous_or_legacy');
    Object.freeze(this);
  }

  /**
   * 从 sessionStore 的 state snapshot 构造 FrontRequestContext。
   *
   * @param {object} snapshot sessionStore.state(见 sessionStore.js)
   * @returns {FrontRequestContext}
   */
  static from(snapshot) {
    if (!snapshot || typeof snapshot !== 'object') return new FrontRequestContext();
    return new FrontRequestContext({
      clientId: snapshot.clientId,
      legacyUserKey: snapshot.legacyUserKey,
      workspaceId: snapshot.workspaceId,
      projectId: snapshot.projectId,
      requestId: snapshot.requestId,
      authMode: snapshot.authMode,
    });
  }

  /**
   * 序列化到 HTTP headers dict。**只发送非空**字段,null / 空字符串不产生空 header。
   * X-Request-Id 由响应侧回读,不作为发送 header(PR-BE-02 middleware 语义)。
   *
   * @returns {object} 例如 `{ 'X-Client-Id': 'c1', 'X-Workspace-Id': 'w1' }`
   */
  toHeaders() {
    const headers = {};
    if (this.clientId) headers['X-Client-Id'] = this.clientId;
    if (this.workspaceId) headers['X-Workspace-Id'] = this.workspaceId;
    if (this.projectId) headers['X-Project-Id'] = this.projectId;
    return headers;
  }
}

export default FrontRequestContext;
