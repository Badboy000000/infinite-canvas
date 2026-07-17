# shared/api-client（seam 期）

Infinite Canvas 前端 seam 期统一 API 客户端。**零构建零依赖**——原生 ES module，直接 `import`。

## 定位

- 治理里程碑：M1（seam）。
- 落地 PR：前端 PR-2（本目录首次建立）。
- 后续 PR：PR-3 补 messaging bus、PR-4 承接 fileApi、PR-5 承接 Provider Store、PR-6+ 陆续把 `canvas.js` / `smart-canvas.js` / `api-settings.js` 剩余裸 `fetch()` 迁到本 client。
- 相关文档：
  - `docs/frontend-freeze/compat-contract.md`（前端兼容合同冻结清单，§7 fetch URL 表 = 本目录 `endpoints.js` 的直接输入）
  - `docs/frontend-smoke/checklist.md`（22 项前端保活烟测）
  - [[前端组件化治理实施计划与PR清单]] PR-2
  - [[技术开发规则与工程实施规范]] §API 与错误契约规则

## 用法

### 读取（GET）

```js
import { apiClient, LIST_CANVASES } from '/static/js/shared/api-client/index.js';

const data = await apiClient.get(LIST_CANVASES);
// data.canvases: [...]
```

### 参数化路径

```js
import { apiClient, CANVAS_BY_ID } from '/static/js/shared/api-client/index.js';

const canvas = await apiClient.get(CANVAS_BY_ID(id));
```

### JSON body

```js
await apiClient.put(CANVAS_BY_ID(id), {
  body: { title, icon, nodes, connections, viewport, client_id, base_updated_at },
});
```

普通对象 body 会自动 `JSON.stringify` 并加 `Content-Type: application/json`；FormData / Blob / string / URLSearchParams 直接透传（保留 multipart 语义，兼容合同 §7.8）。

### 错误处理

```js
import {
  apiClient,
  ApiClientError,
  isConflictError,
  CANVAS_BY_ID,
} from '/static/js/shared/api-client/index.js';

try {
  await apiClient.put(CANVAS_BY_ID(id), { body: payload });
} catch (err) {
  if (isConflictError(err)) {
    // 409 冲突：按兼容合同 §10 消费 err.detail?.canvas / err.detail?.updated_at
    return handleConflict(err.detail);
  }
  if (err instanceof ApiClientError) {
    // err.status / err.errorCode / err.detail / err.requestId
    setStatus(err.friendlyMessage('保存失败'));
    return;
  }
  throw err;
}
```

## 迁移守则

从 `fetch()` 迁到 `apiClient` 时**必须**保证：

1. URL / method / body / 关键 header **逐字节等价**。
2. `credentials: 'same-origin'` 是默认；如原调用点显式声明了其他值必须复现。
3. FormData 上传保留 multipart 语义（**禁止改为 JSON**，兼容合同 §7.8）。
4. 中文错误 detail pass-through（兼容合同 §12.1）；`friendlyMessage` 仅在 `err.message` 为空时兜底。
5. 已迁移调用点在 devtools Network 面板对比时**请求逐字节一致**。

## 命名规范（`endpoints.js`）

- 常量全大写下划线：`LIST_CANVASES` / `JIMENG_STATUS` / `COMFYUI_INSTANCES`。
- 动词_对象_限定：`LIST_*` 集合读，`GET_*` 单个读，`PUT_*` / `POST_*` / `DELETE_*` / `PATCH_*` 写侧。
- 参数化路径以函数导出（`CANVAS_BY_ID(id)`）。
- 每个常量注释必须指回 `docs/frontend-freeze/compat-contract.md` §7 引用行；行号漂移标注 `src=file:line` 事实。
- 不改 URL / method / body 字段名——`endpoints.js` 只做常量提取（PR-2 铁律）。

## 当前不做

- 不引入 axios / ky / fetch-retry。
- 不做自动重试 / 拦截器编排（PR-3+ 视需要增补 `interceptors.js`）。
- 不封装 `X-Client-Id` / `X-Request-Id` 注入（PR-BE-02 落地后配套追加）。
- 不承接域级 API 模块（`canvasApi.js` / `providerApi.js` 等在 PR-3+ 追加到 `domains/`）。
