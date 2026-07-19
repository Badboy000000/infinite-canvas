// static/js/shared/stores/workflowsStore.js
//
// 前端 PR-5：Workflows store（[[前端组件化治理实施计划与PR清单]] PR-5）。
//
// 语义：内部区分三类 workflow 面：
//   - `comfy`：从 `/api/workflows` 拉取的 ComfyUI 工作流列表（`state.comfy`）。
//   - `runninghub`：runninghub provider 下挂的 `rh_workflows` + 单个 workflowId 明细缓存
//     （`state.runninghub.list` / `state.runninghub.cache`）。
//   - `canvasSubgraph`：Canvas 子图/子画布工作流（M3 才承接结构，本 PR 只留空 slot）。
//
// 每类子面独立 refetch / invalidate；一个 kind 的 revision 变化不污染其他 kind。
// `refresh-workflows` bus 事件（前端 PR-3 已建）由 bootstrap 绑定到 `workflowsStore.invalidate('workflows-changed')`。

import { createStore } from './_createStore.js';
import { apiClient } from '../api-client/client.js';

export const WORKFLOW_KINDS = Object.freeze(['comfy', 'runninghub', 'canvasSubgraph']);

async function fetchComfy() {
  try {
    const data = await apiClient.get('/api/workflows');
    return Array.isArray(data?.workflows) ? data.workflows : [];
  } catch (_) {
    return [];
  }
}

function createComfyStore() {
  return createStore({
    name: 'workflows.comfy',
    initialState: { workflows: [] },
    fetcher: async () => ({ workflows: await fetchComfy() }),
  });
}

function createRunningHubStore() {
  return createStore({
    name: 'workflows.runninghub',
    initialState: { list: [], cache: {} },
    // fetcher 由业务侧调用：需要挂到某个 provider 的 rh_workflows 上；本 store 只做投影 + 幂等 cache。
    fetcher: null,
  });
}

function createCanvasSubgraphStore() {
  return createStore({
    name: 'workflows.canvasSubgraph',
    initialState: { entries: [] },
    fetcher: null,
  });
}

const comfy = createComfyStore();
const runninghub = createRunningHubStore();
const canvasSubgraph = createCanvasSubgraphStore();

/**
 * 组合 store：暴露 3 个子 store + 顶层 subscribe/invalidate/refetch 聚合。
 * 顶层 `revision` 是三子 store revision 之和，保证任一子面变化会推动顶层 revision 单调递增。
 */
export const workflowsStore = Object.freeze({
  name: 'workflows',
  kinds: WORKFLOW_KINDS,
  comfy,
  runninghub,
  canvasSubgraph,
  get state() {
    return {
      comfy: comfy.state,
      runninghub: runninghub.state,
      canvasSubgraph: canvasSubgraph.state,
    };
  },
  get revision() {
    return comfy.revision + runninghub.revision + canvasSubgraph.revision;
  },
  subscribe(handler) {
    // 每个 kind 独立触发（保证 comfy 变化不 phantom-fire runninghub 订阅方）
    const un1 = comfy.subscribe((s, r, reason) => handler({ kind: 'comfy', state: s, revision: r, reason }));
    const un2 = runninghub.subscribe((s, r, reason) => handler({ kind: 'runninghub', state: s, revision: r, reason }));
    const un3 = canvasSubgraph.subscribe((s, r, reason) => handler({ kind: 'canvasSubgraph', state: s, revision: r, reason }));
    return function unsubscribe() { un1(); un2(); un3(); };
  },
  invalidate(reason = 'workflows-changed') {
    comfy.invalidate(reason);
    runninghub.invalidate(reason);
    canvasSubgraph.invalidate(reason);
  },
  refetch(reason = 'refetch') {
    // 只对有 fetcher 的子面触发；runninghub / canvasSubgraph 由业务侧显式管理。
    return comfy.refetch(reason).then(state => ({ comfy: state }));
  },
});
