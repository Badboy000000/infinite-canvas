// static/js/shared/stores/assetLibraryStore.js
//
// 前端 PR-5：Asset library store（[[前端组件化治理实施计划与PR清单]] PR-5）。
//
// 语义：承接 `/api/asset-library` 返回的 `library` 快照 + `smart_canvas_asset_inbox` 通道（compat-contract §4.3）。
// 消费方：canvas.js / smart-canvas.js / asset-manager.js 顶层 `assetLibrary` 变量的 store 化投影。
//
// 冻结：
//   - `library.libraries` / `library.categories` 字段名不改（compat-contract §7.7 / §13）。
//   - `smart_canvas_asset_inbox` key 名不改（compat-contract §4.5）。

import { createStore } from './_createStore.js';
import { apiClient } from '../api-client/client.js';

async function fetchAssetLibrary() {
  try {
    const data = await apiClient.get('/api/asset-library');
    return data && typeof data === 'object' ? data : {};
  } catch (_) {
    return {};
  }
}

export const assetLibraryStore = createStore({
  name: 'assetLibrary',
  initialState: {
    library: { libraries: [], categories: [] },
    active_library_id: '',
    updated_at: 0,
  },
  fetcher: async () => {
    const data = await fetchAssetLibrary();
    return {
      library: data.library && typeof data.library === 'object' ? data.library : { libraries: [], categories: [] },
      active_library_id: data.asset_library?.id || '',
      updated_at: Number(data.updated_at || 0),
    };
  },
});

/**
 * 页面侧同步一次 asset library（用于消费 `/api/asset-library/items` POST 等响应携带的 `library` 快照）。
 * 与 refetch 不同：不打网络，只 patch state。
 */
export function applyAssetLibrarySnapshot(data, reason = 'apply-snapshot') {
  if (!data || typeof data !== 'object') return;
  const patch = {};
  if (data.library && typeof data.library === 'object') patch.library = data.library;
  if (data.asset_library && typeof data.asset_library === 'object' && data.asset_library.id) {
    patch.active_library_id = data.asset_library.id;
  }
  if (data.updated_at != null) patch.updated_at = Number(data.updated_at) || 0;
  if (Object.keys(patch).length) assetLibraryStore.setState(patch, reason);
}
