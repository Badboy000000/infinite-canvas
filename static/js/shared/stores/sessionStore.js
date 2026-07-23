// static/js/shared/stores/sessionStore.js
//
// Wave 3-N.6 Batch 3 主线 B · 前端 PR-9 · sessionStore.
//
// 契约([[40 实施计划/前端组件化治理实施计划与PR清单]] §PR-9 · [[40 实施计划/用户团队权限治理实施计划与PR清单]] PR-3 承接):
//
//   - state 6 字段:clientId / legacyUserKey / workspaceId / projectId / authMode
//     + capabilities(默认全 true 透明放行 · 权限 PR-3 上线后填服务端权威)
//     + requestId(响应侧回填 · 便于错误追踪)
//   - refresh():GET `/api/whoami`(权限 PR-1 已在位) · 成功则填 FrontRequestContext
//     6 字段;404 / 网络失败 / 500 / abort 均降级到硬编码全 true(不阻断 UI · 契约测试
//     T412 / T413 / T414 关键)
//   - 不引入登录流程 / CSRF 注入 / role 分支(硬约束)
//   - 不写 legacy `x_user_id` header 语义(硬约束 · 保留兼容层)
//   - 前端不作为安全事实源(服务端强制)· <Can> 全 true 时透明放行是安全语义:
//     后端 401/403 才是权威 · 前端隐藏按钮不作为安全边界
//
// 消费 `_createStore.js` 六件套 pattern(subscribe / snapshot / setState / revision)。

import { createStore } from './_createStore.js';
import { apiClient } from '../api-client/client.js';
import { ApiClientError } from '../api-client/errors.js';

// 权限未上线全 true 透明放行(硬约束 · 前端组件化治理方案 §PR-9)
export const DEFAULT_CAPABILITIES = Object.freeze({
  'canvas.edit': true,
  'canvas.delete': true,
  'canvas.share': true,
  'provider.edit': true,
  'provider.delete': true,
  'workflow.edit': true,
  'workflow.overwrite': true,
  'workflow.delete': true,
  'asset.delete': true,
});

/** capabilities 未登记的动作默认 true(透明放行) */
export function hasCapability(capabilities, action) {
  if (!capabilities || typeof capabilities !== 'object') return true;
  if (!action || typeof action !== 'string') return true;
  const v = capabilities[action];
  if (v === undefined || v === null) return true; // 未登记 → 透明放行
  return v !== false;
}

// `/api/whoami` fetcher · 幂等 · 网络失败 / 404 / 500 均降级到硬编码全 true
// (T412 / T413 / T414 契约测试关键 —— 权限未上线不阻断 UI)。
async function fetchSessionIdentity(currentState) {
  const fallback = {
    clientId: currentState.clientId,
    legacyUserKey: currentState.legacyUserKey,
    workspaceId: currentState.workspaceId,
    projectId: currentState.projectId,
    authMode: currentState.authMode,
    // 权限未上线 → 全 true 透明放行(硬约束)
    capabilities: { ...DEFAULT_CAPABILITIES },
    // requestId 保留(响应拦截器可能已回填)
    requestId: currentState.requestId,
  };
  try {
    const body = await apiClient.get('/api/whoami');
    // whoami schema(权限 PR-1 · main.py::WhoamiResponse):
    //   { principal_kind, user_id, workspace_id, project_id, request_id }
    // sessionStore 字段命名与 FrontRequestContext 对齐;user_id 映射 legacyUserKey。
    return {
      clientId: currentState.clientId, // whoami 不返回 client_id(仅接受入参)
      legacyUserKey: body && body.user_id != null ? String(body.user_id) : null,
      workspaceId: body && body.workspace_id != null ? String(body.workspace_id) : null,
      projectId: body && body.project_id != null ? String(body.project_id) : null,
      authMode:
        body && body.principal_kind === 'user' ? 'legacy_alias'
        : body && body.principal_kind === 'session' ? 'legacy_alias'
        : 'anonymous_or_legacy',
      // whoami 骨架层不返回 capabilities(权限 PR-3 承接) · 前端全 true
      capabilities: { ...DEFAULT_CAPABILITIES },
      requestId: body && body.request_id ? String(body.request_id) : currentState.requestId,
    };
  } catch (err) {
    // T412 404 / T413 网络 / T414 500 均降级 · 不抛错
    if (err instanceof ApiClientError) {
      if (globalThis.console && (err.status === 500 || err.isNetworkError)) {
        // 仅 5xx / 网络异常留 warn 便于观测;404 属预期(权限 PR-3 未上线)
        console.warn('[sessionStore] whoami degraded:', err.status || 'network', err.message);
      }
    } else if (globalThis.console) {
      console.warn('[sessionStore] whoami degraded (unexpected):', err);
    }
    return fallback;
  }
}

export const sessionStore = createStore({
  name: 'session',
  initialState: {
    clientId: null,
    legacyUserKey: null,
    workspaceId: null,
    projectId: null,
    authMode: 'anonymous_or_legacy',
    capabilities: { ...DEFAULT_CAPABILITIES },
    requestId: null,
  },
  fetcher: fetchSessionIdentity,
});

/** 便捷 alias:sessionStore.refresh() = refetch() */
export function refresh(reason = 'refresh') {
  return sessionStore.refetch(reason);
}
