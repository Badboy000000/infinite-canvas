// static/js/shared/stores/providersStore.js
//
// 前端 PR-5：Provider store（[[前端组件化治理实施计划与PR清单]] PR-5）。
//
// 语义：
//   - `state.providers`：公开视图 provider 列表；来源 `apiClient.get(LIST_PROVIDERS)` → `{ providers: [...] }`。
//   - 后端 `public_provider(main.py:1595)` 返回的字段中，`has_key` / `key_env` / `key_preview` 等
//     属于**元数据**（存在标记 / 环境变量名 / 前 8 位掩码），不是原始凭据；
//     真实 `api_key` / `wallet_key` / `volcengine_access_key` / `volcengine_secret_key`
//     **永不出现在 `/api/providers` 响应中**（P0 硬约束）。
//   - 本 store 直接透传后端响应；同时提供 `credentialSafe()` 抗回归自检（用于测试）。
//
// 硬约束：Provider 凭据不落 store（seam 期 P0）。测试 `test_providers_store_credential_never_persisted`
// 用 `credentialSafe()` 断言 state 内不含裸凭据字段。

import { createStore } from './_createStore.js';
import { apiClient } from '../api-client/client.js';
import { LIST_PROVIDERS } from '../api-client/endpoints.js';

// 明确禁止落 store 的字段（原始凭据），若后端接口回归带上则视为违约。
export const FORBIDDEN_CREDENTIAL_FIELDS = Object.freeze([
  'api_key',
  'wallet_key',
  'volcengine_access_key',
  'volcengine_secret_key',
]);

/**
 * 递归检查 obj 中是否含有 FORBIDDEN_CREDENTIAL_FIELDS 的字段（值非空字符串）。
 * @returns {string[]} 命中字段路径列表（空数组表示安全）。
 */
export function findCredentialLeaks(obj, path = '$') {
  const hits = [];
  function visit(node, p) {
    if (!node || typeof node !== 'object') return;
    if (Array.isArray(node)) {
      node.forEach((item, i) => visit(item, `${p}[${i}]`));
      return;
    }
    Object.keys(node).forEach(key => {
      if (FORBIDDEN_CREDENTIAL_FIELDS.includes(key)) {
        const value = node[key];
        // 允许字段存在但值为空 / null / undefined；非空字符串 / 非空对象视为泄漏
        if (value != null && value !== '' && !(typeof value === 'object' && Object.keys(value).length === 0)) {
          hits.push(`${p}.${key}`);
        }
      }
      visit(node[key], `${p}.${key}`);
    });
  }
  visit(obj, path);
  return hits;
}

async function fetchProviders() {
  const data = await apiClient.get(LIST_PROVIDERS);
  const providers = Array.isArray(data?.providers) ? data.providers : [];
  // 抗回归：后端不应返回原始凭据字段；命中则打印 error 并**过滤剔除**这些字段（安全兜底）。
  const cleaned = providers.map(sanitizeProvider);
  return { providers: cleaned };
}

/**
 * 剔除 FORBIDDEN_CREDENTIAL_FIELDS 字段（防守性）；仅保留 has_key / key_env / key_preview 等元数据。
 */
export function sanitizeProvider(provider) {
  if (!provider || typeof provider !== 'object') return provider;
  const cleaned = { ...provider };
  FORBIDDEN_CREDENTIAL_FIELDS.forEach(key => { if (key in cleaned) delete cleaned[key]; });
  return cleaned;
}

/**
 * 只读 credential safety self-check；测试 `test_providers_store_credential_never_persisted` 使用。
 */
export function credentialSafe(store) {
  return findCredentialLeaks(store.state, '$state').length === 0;
}

export const providersStore = createStore({
  name: 'providers',
  initialState: { providers: [] },
  fetcher: fetchProviders,
});
