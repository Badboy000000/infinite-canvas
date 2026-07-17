# 前端兼容合同冻结清单（PR-0）

## 文档定位

本文是 Infinite Canvas 前端组件化治理 M0 阶段 PR-0 的交付物：把当前所有隐式的跨页 / 跨版本合同**显式冻结**成清单，作为后续所有前端 PR（M1 → M7）的回归基线。

- 依据：[[前端组件化治理实施计划与PR清单]] PR-0、[[2026-07-16 首批 PR 开工协调纲要]] 前端 PR-0、[[前端现状架构地图]]。
- 时间：2026-07-16。
- 范围：仅前端；后端合同由后端 / 数据 / 文件 / Provider 各版块自行冻结。
- 硬约束：本 PR **不写任何业务代码**，也不建 `static/js/shared/` 目录（M1 才启动）。
- 引用格式：所有条目附 `文件相对路径:行号`，行号以当前 `main` 分支为准。

约定：
- 「未定位到」的条目已单独列在文末 §14，供后续 PR 补齐。
- 文档同名镜像位于 `E:\个人知识库\Infinite Canvas 二开与架构治理项目知识库\90 资料归档\前端兼容合同冻结清单.md`；仓内为主，知识库为镜像，任何变更以仓内为准。

## 目录

1. iframe 父/子 message 全量枚举
2. `BroadcastChannel('studio-api')` 频道消息
3. `/ws/stats` WebSocket 事件
4. localStorage / sessionStorage 旧 key 全量清单
5. URL 参数清单
6. 旧全局函数清单
7. fetch URL / method / body 表
8. HTML 内联 onclick 计数基线
9. 节点 DOM 类名 / `data-*` 属性 / SVG 连线 class
10. Canvas 409 冲突两种响应 shape
11. `base_updated_at` / `revision` / `client_id === CLIENT_ID` 自我识别语义
12. 中文错误 / 提示文案基线
13. `serializableCanvasNode()` / `canvasForStorage()` 字段清单
14. 未定位到 / 待补条目
15. 触及的源码文件清单
16. 下一 PR（前端 PR-1）如何消费本清单

---

## 1. iframe 父/子 message 全量枚举

冻结原则：所有 `window.postMessage` 与 `addEventListener('message')` 中出现的 `type` 字符串、payload 字段、发送/接收位置。后续 PR-3 建 `shared/messaging` bus 时，`types.js` 的 discriminated union 必须与本节 1:1 对齐；不新增、不改名。

### 1.1 父 → 子（`index.html` → iframe.contentWindow）

| type | payload 字段 | 发送位置 | 语义 |
|---|---|---|---|
| `canvas-focus` | `type` | `static/index.html:1906` | 切到画布 iframe 时通知子页取回焦点、刷新配置 |
| `studio-theme` | `type`, `theme` | `static/index.html:1996` | 主题联动到 iframe |
| `studio-ui-scale` | `type`, `mode`, `scale` | `static/index.html:2007` | UI 缩放联动到 iframe |
| `studio-ui-scale-pause` | `type`, `duration` | `static/index.html:2014` | 暂停自动缩放（数字，单位 ms） |
| `studio-lang` | `type`, `lang` | `static/index.html:2071`、`static/index.html:2078` | 语言联动到 iframe |
| `cloud_status` | 整包透传自 `/ws/stats` | `static/index.html:1974` | 云端任务进度转发到 iframe |
| `canvas_updated` | 整包透传自 `/ws/stats` | `static/index.html:1979` | 画布更新事件转发（含 `client_id` / `canvas_id` / `updated_at`） |
| `asset_library_updated` | 整包透传自 `/ws/stats` | `static/index.html:1983` | 素材库更新事件转发 |
| `providers-changed` / `workflows-changed` / `comfy-instances-changed` | 转发自 BroadcastChannel | `static/index.html:1915`、`static/index.html:1974-1983`（`iframe.contentWindow.postMessage(data,'*')`）；BC 桥接入口在 `static/index.html:1912`、`static/index.html:1925-1928` | Provider / 工作流 / ComfyUI 实例变更转发给全部 iframe |

其他 postMessage 补充点：
- `static/js/theme.js:195`：主入口发送 `studio-ui-scale`（触发自 `setScaleMode`）。
- `static/js/api-settings.js:334`、`static/js/api-settings.js:335`：Provider 设置页向父窗口 / 顶层广播 `providers-changed` / `workflows-changed`。
- `static/js/comfyui-settings.js:251`：向父窗口广播 `comfy-instances-changed`。

### 1.2 子 → 父 / 子接收

| 接收方 | 消费 type | 位置 | 消费字段 |
|---|---|---|---|
| `index.html` 主壳 | `providers-changed` / `workflows-changed` / `comfy-instances-changed` | `static/index.html:1912`、`static/index.html:1920-1923` | `type`；用于分发到所有 iframe |
| `index.html` 主壳 | WebSocket 消息（type = `stats` / `cloud_status` / `canvas_updated` / `asset_library_updated`） | `static/index.html:1968-1984` | `online_count` / 整包透传 |
| `canvas.js` | `studio-lang` | `static/js/canvas.js`（monitor 位于 215-227 block） | `event.data.lang` |
| `canvas.js` | `canvas_updated` | `static/js/canvas.js:218` | 转 `handleCanvasUpdatedMessage(event.data)` |
| `canvas.js` | `providers-changed` / `workflows-changed` / `comfy-instances-changed` | `static/js/canvas.js:219` | 触发 `refreshCanvasConfigFromSettings()` |
| `canvas.js` | `canvas-focus` | `static/js/canvas.js:222` | 触发配置刷新 + `syncRemoteCanvasNow()` |
| `smart-canvas.js` | `studio-theme` | `static/js/smart-canvas.js:17003` | `event.data.theme` |
| `smart-canvas.js` | `providers-changed` / `workflows-changed` / `comfy-instances-changed` | `static/js/smart-canvas.js:17004`、`static/js/smart-canvas.js:16991` | 触发 `refreshSmartConfigFromSettings()` |
| `smart-canvas.js` | `asset_library_updated` / `canvas_updated` | `static/js/smart-canvas.js:16994-16995`、`static/js/smart-canvas.js:17005-17006` | 分别派发到 `handleAssetLibraryUpdatedMessage` / `handleCanvasUpdatedMessage` |
| `smart-canvas.js` | `/ws/stats` 内的 `asset_library_updated` / `canvas_updated` | `static/js/smart-canvas.js:5254-5255` | 同上（走 WebSocket 而非 iframe 消息） |
| `asset-manager.js` | `studio-theme` | `static/js/asset-manager.js:4762` | `event.data.theme` |
| `theme.js` | `studio-theme` / `studio-ui-scale` / `studio-ui-scale-pause` | `static/js/theme.js:260-268` | 主题 / 缩放 / 暂停缩放联动 |
| `angle.html` | `cloud_status` | `static/angle.html:543-545` | 云端进度显示 |
| `enhance.html` | `studio-lang` | `static/enhance.html:456-457` | 语言联动 |
| `gpt-chat.html` | `studio-lang` | `static/gpt-chat.html:620-622` | 语言联动 |
| `angle.html` | `studio-lang` | `static/angle.html:791` | 语言联动 |
| `online.html` | `providers-changed` / `workflows-changed` | `static/online.html:248` | 触发 provider 刷新 |

### 1.3 自定义 CustomEvent（同源窗口内广播）

| 事件名 | 触发点 | 监听点 | payload |
|---|---|---|---|
| `studio-theme-change` | `static/js/theme.js:20`、`static/js/theme.js:240` | `static/index.html:2084`；`static/js/canvas.js:2311`；`static/js/smart-canvas.js:16987` | `event.detail.theme` |
| `studio-ui-scale-change` | `static/js/theme.js:188`、`static/js/theme.js:206` | `static/index.html:2088`；`static/js/canvas.js:235` | `event.detail.mode`、`event.detail.scale` |
| `studio-lang-change` | `static/js/i18n-core.js:51` | `static/angle.html:793`；`static/enhance.html:459`；`static/gpt-chat.html:623`；`static/klein.html:389`；`static/online.html:250`；`static/zimage.html:302`；`static/js/api-settings.js:3861`；`static/js/canvas.js:228`；`static/js/comfyui-settings.js:1389`；`static/js/history-bulk-manager.js:217`；`static/js/smart-canvas.js:17011` | `event.detail.lang` |

### 1.4 §1 冻结要点

- `refresh-workflows` 与 `studio:api-changed` / `storage-settings-changed` 三条在 `static/**` 全量 grep 均**未定位到**（详见 §14）。协调纲要将其列入枚举清单，实际实现是通过 `BroadcastChannel('studio-api')` 的 `workflows-changed` / `providers-changed` / `comfy-instances-changed` 三条消息承载；后续 PR 不得复活“refresh-workflows” / “studio:api-changed”名字，除非明确记录并同步治理方案。
- `canvas-focus` 目前仅经典画布 `canvas.js:222` 消费；智能画布未消费，接入 M6/M7 后需登记。
- `event.origin` 校验：现状对 iframe 消息**没有 origin 白名单**（同源 iframe，父子来源一致）。PR-3 建 bus 时需要保持“同源接受”默认，不改变现状语义。

---

## 2. `BroadcastChannel('studio-api')` 频道

### 2.1 频道 & 消息类型

- 频道名固定：`'studio-api'`。
- payload 结构：`{ type: '<providers-changed'|'workflows-changed'|'comfy-instances-changed'>', updated_at?: number }`。`updated_at` 仅 `api-settings.js` 会发（`static/js/api-settings.js:333`）；其余发送方省略。

### 2.2 发送点

| type | 位置 | 触发场景 |
|---|---|---|
| `providers-changed` | `static/js/api-settings.js:333`、`static/js/api-settings.js:1380`、`static/js/api-settings.js:3825` | Provider 增删改保存后 |
| `workflows-changed` | `static/js/api-settings.js:333`、`static/js/api-settings.js:1416`；`static/js/comfyui-settings.js:1342`、`static/js/comfyui-settings.js:1364`、`static/js/comfyui-settings.js:1381` | ComfyUI/RH 工作流上传 / 编辑 / 删除后 |
| `comfy-instances-changed` | `static/js/comfyui-settings.js:250` | ComfyUI 实例列表变更后 |

### 2.3 订阅点

| 位置 | 消费类型 | 行为 |
|---|---|---|
| `static/index.html:1925-1928` | 三种全部 | 收到后重复 postMessage 到所有 iframe（即“BC → iframe 桥”） |
| `static/js/canvas.js:1493-1499` | 三种全部 | 触发 `refreshCanvasConfigFromSettings()` |
| `static/js/smart-canvas.js:16989-16996` | 三种全部 | 触发 `refreshSmartConfigFromSettings()` |
| `static/gpt-chat.html:852-857` | `providers-changed` | 刷新 provider 列表 |
| `static/online.html:444-446` | `providers-changed` / `workflows-changed` | 触发 provider 刷新 |

### 2.4 冻结要点

- **不改频道名 `studio-api`，不改任何 type 字符串**，不新增字段（`updated_at` 属可选，读端必须允许缺省）。
- BC 与 iframe.postMessage 双通道并存是**故意为之**（跨 iframe + 跨浏览上下文兜底）；PR-3 需要把二者收敛到同一 bus，但外部字符串合同必须保留。

---

## 3. `/ws/stats` WebSocket 事件

### 3.1 连接点

| 位置 | URL 模板 | client_id 来源 |
|---|---|---|
| `static/index.html:1965` | `${protocol}://${host}/ws/stats?client_id=${CID}` | `localStorage.getItem('client_id')` 或首次随机生成 |
| `static/js/smart-canvas.js:5246` | `${protocol}://${host}/ws/stats?client_id=${clientId}` | 智能画布 `smartClientId`（模块级常量） |
| `static/angle.html:1352` | 同上 | `localStorage['client_id']` |
| `static/zimage.html:322` | `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/stats?client_id=${encodeURIComponent(CLIENT_ID)}` | 页面内 CLIENT_ID |

### 3.2 事件与 shape

| type | shape 关键字段 | 消费位置 |
|---|---|---|
| `stats` | `online_count`（number） | `static/index.html:1968-1970` |
| `cloud_status` | 整包（`type`, `task_id`, `progress`, `status`, `message` 等，透传） | `static/index.html:1971-1975`（转发给 iframe）；`static/angle.html:543-545`（消费） |
| `canvas_updated` | `type`, `client_id`, `canvas_id`, `updated_at`, `canvas`（optional） | `static/index.html:1977-1980`（转发）；`static/js/canvas.js:2169` `handleCanvasUpdatedMessage(data)`；`static/js/smart-canvas.js:5213` `handleCanvasUpdatedMessage(data)` |
| `asset_library_updated` | `type`, `client_id`（optional） | `static/index.html:1981-1984`；`static/js/smart-canvas.js:4953` `handleAssetLibraryUpdatedMessage(data)` |
| `new_image` | `type`, `data.type`, `data.timestamp` | `static/zimage.html:326-330`（当 `data.type === 'zimage'` 才插新图卡片） |
| `pong` | `type` | `static/angle.html:1355` 附近，30s 心跳保活；主入口不消费 |

### 3.3 冻结要点

- 事件 `type` 字符串锁定：`stats` / `cloud_status` / `canvas_updated` / `asset_library_updated` / `new_image` / `pong`，不加不改。
- `client_id` 自我识别语义详见 §11。
- `/ws/stats` 是**单一 WS 端点**；后续任何 PR 想拆多端点（比如 `/ws/canvas`、`/ws/asset`）都必须先冻结新端点、再迁移。

---

## 4. localStorage / sessionStorage 旧 key 全量清单

冻结原则：**任何 key 名不改，任何 shape 不改**；PR-3 的 `shared/storage/legacyKeys.js` 常量化时 1:1 引用。

### 4.1 全局 / 主壳

| Key | 类型 | 主要引用 | 备注 |
|---|---|---|---|
| `studio_theme` | localStorage | `static/index.html:17`；`static/js/theme.js:8`、`238`；`static/angle.html:12`、`asset-manager.html:11`、`api-settings.html:11`、`canvas-list.html:11`、`canvas.html:11`、`comfyui-settings.html:10`、`enhance.html:12`、`gpt-chat.html:11`、`klein.html:12`、`online.html:11`、`smart-canvas.html:11`、`zimage.html:12` | 主题（`light` / `dark`），优先于 `canvas_theme` |
| `canvas_theme` | localStorage | `static/js/theme.js:3`、`static/js/theme.js:239` | 旧主题 key，向后兼容 |
| `studio_ui_scale_mode` | localStorage | `static/js/theme.js:4`、`static/js/theme.js:81`、`static/js/theme.js:203` | UI 缩放模式（`auto` 或百分比数字） |
| `client_id` | localStorage | `static/index.html:1785-1786`；`static/angle.html:827-828`；`static/enhance.html:469-470`；`static/klein.html:401-402`；`static/zimage.html:313-314` | WebSocket 客户端标识 |
| `studio_active_page` | localStorage | `static/index.html:1660`、`static/index.html:1891`、`static/index.html:1932` | 当前激活 tab id |
| `studio_update_source` | localStorage | `static/index.html:1799`、`static/index.html:2277` | 更新源（`github` 等） |
| `studio_sidebar_pinned` | localStorage | `static/index.html:1818`、`static/index.html:1829` | 侧栏是否固定 |
| `studio_local_nav_collapsed` | localStorage | `static/index.html:1840`、`static/index.html:1849`、`static/index.html:1899` | 本地导航折叠 |
| `studio_sidebar_settings_collapsed` | localStorage | `static/index.html:1861`、`static/index.html:1870` | 设置侧栏折叠 |

### 4.2 画布列表 / 经典画布

| Key | 类型 | 引用 |
|---|---|---|
| `canvasListCurrentProjectId` | localStorage | `static/js/canvas-list.js:13`、`static/js/canvas-list.js:17`、`static/js/canvas-list.js:25`；`static/js/canvas.js:363`、`static/js/canvas.js:2425`、`static/js/canvas.js:2430`；`static/js/smart-canvas.js:4`、`static/js/smart-canvas.js:1153` |
| `canvasSortMode` | localStorage | `static/js/canvas.js:362`、`static/js/canvas.js:1588` |
| `canvas_custom_image_models` | localStorage | `static/js/canvas.js:502` |
| `canvas_image_models_ordered` | localStorage | `static/js/canvas.js:503` |
| `canvas_chat_models_ordered` | localStorage | `static/js/canvas.js:504` |
| `canvas_quick_toolbar_collapsed` | localStorage | `static/js/canvas.js:506` |
| `canvas_prompt_template_groups_v1` | localStorage | `static/js/canvas.js:420`、`static/js/canvas.js:7126`、`static/js/canvas.js:7136` |
| `canvas_prompt_template_overrides` | localStorage | `static/js/canvas.js:421`、`static/js/canvas.js:7140`、`static/js/canvas.js:7150` |
| `canvas_session_viewports_v1` | sessionStorage | `static/js/canvas.js:507`、`static/js/canvas.js:535`、`static/js/canvas.js:561` |

### 4.3 智能画布

| Key | 类型 | 引用 |
|---|---|---|
| `smart_canvas_asset_inbox` | localStorage | `static/js/asset-manager.js:2644`、`static/js/asset-manager.js:2729`；`static/js/smart-canvas.js:5992`、`static/js/smart-canvas.js:6023` |
| `smart_canvas_prompt_presets_v1` | localStorage | `static/js/smart-canvas.js:114`、`static/js/smart-canvas.js:4148`、`static/js/smart-canvas.js:4155` |
| `smart_canvas_prompt_template_groups_v1` | localStorage | `static/js/smart-canvas.js:115`、`static/js/smart-canvas.js:4169`、`static/js/smart-canvas.js:4179` |
| `smart_canvas_prompt_template_overrides_v1` | localStorage | `static/js/smart-canvas.js:116`、`static/js/smart-canvas.js:4183`、`static/js/smart-canvas.js:4193` |
| `smart_canvas_recent_run_settings_v1` | localStorage | `static/js/smart-canvas.js:919`、`static/js/smart-canvas.js:933`、`static/js/smart-canvas.js:940` |

### 4.4 素材库 / 独立工具页

| Key | 类型 | 引用 |
|---|---|---|
| `asset_manager_local_caption_settings_v1` | localStorage | `static/js/asset-manager.js:7`、`static/js/asset-manager.js:18` |
| `modelscope_api_token` | localStorage | `static/angle.html:969`、`static/angle.html:971`；`static/zimage.html:394`、`static/zimage.html:396` |
| `angle_engine_mode` | localStorage | `static/angle.html:797`、`static/angle.html:801` |
| `zimage_engine_mode` | localStorage | `static/zimage.html:338`、`static/zimage.html:345`、`static/zimage.html:366` |
| `gpt_chat_browser_user` | localStorage | `static/gpt-chat.html:637`、`static/gpt-chat.html:642`、`static/gpt-chat.html:643` |
| `gpt_chat_settings_v1` | localStorage | `static/gpt-chat.html:638`、`static/gpt-chat.html:647`、`static/gpt-chat.html:707` |
| `gpt_chat_last_conversation_v1` | localStorage | `static/gpt-chat.html:639`、`static/gpt-chat.html:695`、`static/gpt-chat.html:696`、`static/gpt-chat.html:701` |

### 4.5 冻结要点

- 共 **30 项** key（localStorage 29 + sessionStorage 1），覆盖协调纲要要求的 20+。
- 治理方案硬约束：**PR-3 不合并、不改名任何一个 key**，`namespaced.js` 只能对新增 key 用 `studio:<domain>:<subject>:v<n>` 生成器；旧 key 只常量化。
- `smart_canvas_asset_inbox` 素材 inbox 跨页通道属**已知历史遗留**，M6 / M7 页面迁移时才处理（保持双写）。

---

## 5. URL 参数清单

| 页面 | 参数 | 可选性 | 读取位置 |
|---|---|---|---|
| `canvas-list.html` | `project` | 可选，默认 fallback 到 `localStorage.canvasListCurrentProjectId` 或 `'default'` | `static/js/canvas-list.js:17`（`new URLSearchParams(location.search).get('project')`） |
| `canvas.html` | `id` | 必填；缺失时逻辑上回退到画布列表（`static/js/canvas.js:14789` 附近 URL 解析） | `static/js/canvas.js:14789` |
| `canvas.html` | `project` | 可选 | 同上（读同 URLSearchParams） |
| `smart-canvas.html` | `id` | 可选，默认 `''` | `static/js/smart-canvas.js:1-3`（`params.get('id') || ''`） |
| `smart-canvas.html` | `project` | 可选，默认 `''` | `static/js/smart-canvas.js:1-3`（`params.get('project') || ''`） |

冻结要点：**参数名 `id` / `project` 不变**；M6/M7 SPA 化后 iframe `data-src` 依然携带这两个查询串。任何 SPA 路由重构必须保留这两个字段名。

---

## 6. 旧全局函数清单

后续 PR 迁移时必须保留 wrapper（不能删定义）。位置为“定义 → 主要使用点”。

| 函数 | 定义位置 | 使用点（示例） | 备注 |
|---|---|---|---|
| `switchUI` | `static/index.html:1882` | HTML onclick：`static/index.html:1936` 附近；导航按钮均为 `switchUI('...')` | 主壳切换 iframe |
| `addImageNode` | `static/js/canvas.js:2450` | onclick：`static/canvas.html:41`；调用点 `static/js/canvas.js:3515`、`static/js/canvas.js:3531` | 添加图片节点 |
| `menuAdd` | `static/js/canvas.js:3529` | onclick：`static/canvas.html:69` ～ `static/canvas.html:79`（image/prompt/loop/llm/generator/msgen/video/rh/comfy/ltxDirector/output） | 创建菜单添加节点 |
| `broadcastStudioApiChange` | `static/js/api-settings.js:331` | `static/js/api-settings.js:1380`、`static/js/api-settings.js:1416`、`static/js/api-settings.js:3825` | Provider/工作流广播 |
| `refreshCanvasConfigFromSettings` | `static/js/canvas.js:206` | `static/js/canvas.js:220`、`static/js/canvas.js:224`、`static/js/canvas.js:1496` | 经典画布配置刷新 |
| `refreshSmartConfigFromSettings` | `static/js/smart-canvas.js:4137` | `static/js/smart-canvas.js:16992`、`static/js/smart-canvas.js:16999`、`static/js/smart-canvas.js:17004` | 智能画布配置刷新 |
| `loadConfig` | `static/js/canvas.js:1462`；`static/js/smart-canvas.js:4114`；`static/gpt-chat.html:838` | `static/js/canvas.js:207`、`static/js/canvas.js:14786`；`static/js/smart-canvas.js:4138`、`static/js/smart-canvas.js:17030`；`static/gpt-chat.html:855`、`static/gpt-chat.html:1652` | 每页独立同名函数（未合并） |
| `loadProviders` | `static/js/api-settings.js:3702` | `static/js/api-settings.js:3870` | 加载 Provider 列表 |
| `loadWorkflows` | **未定义为独立函数**；`loadConfig()` 内部 fetch `/api/workflows` | canvas.js:1475、smart-canvas.js:2914 等 | 见 §14 |
| `runGenerator` | `static/js/canvas.js:10409` | `static/js/canvas.js:11573`、`static/js/canvas.js:11851` | 运行 generator 节点 |

补充函数（同为后续 PR-2 迁移入口，需保留 wrapper）：
- `loadList`（`static/js/comfyui-settings.js:259`）
- `selectWorkflow`（`static/js/comfyui-settings.js:291`）
- `onSave` / `onDelete`（`static/js/comfyui-settings.js:1346` / `:1368`）
- `applyLanguage`（`canvas.js` / `smart-canvas.js` / `enhance.html` 等）
- `applyTheme`（`smart-canvas.js:17003`、`asset-manager.js:4762`、`theme.js`）

冻结要点：以上函数名一律保留为兼容 wrapper；不允许改名、不允许删除全局注册。

---

## 7. fetch URL / method / body 表

统计：`static/js/*.js` 内 `fetch(` 出现次数（不含 asset-manager 的 `apiJson` wrapper）：
- `canvas.js`：83
- `smart-canvas.js`：58
- `api-settings.js`：25
- `canvas-list.js`：15
- `comfyui-settings.js`：10
- `asset-manager.js`：5（另有 `apiJson()` wrapper 内部 fetch）
- `history-bulk-manager.js`：1

合计原生 `fetch(` ≥ 197 处；加上 `apiJson` 内部 / `cascadeFetch` 内部展开，总请求点 ≥ 200，符合协调纲要“200+”预期。

### 7.1 canvas.js（14795 行，83 处 fetch，节选主 URL）

| file:line | URL | method | 关键 body 字段 |
|---|---|---|---|
| `static/js/canvas.js:1411` | `/api/canvases/${canvas.id}` | PUT | `title`, `icon`, `nodes`, `connections`, `viewport`, `logs`, `client_id`, `base_updated_at` |
| `static/js/canvas.js:1465` | `/api/config` | GET | — |
| `static/js/canvas.js:1475` | `/api/workflows` | GET | — |
| `static/js/canvas.js:1512` | `/api/canvases` | GET | — |
| `static/js/canvas.js:1531` | `/api/canvases/trash` | GET | — |
| `static/js/canvas.js:1600` | `/api/canvases/${id}/meta` | POST | `pinned`, `color`, `owner` |
| `static/js/canvas.js:1643` | `/api/canvases/${id}/touch` | POST | — |
| `static/js/canvas.js:1856` | `/api/canvases` | POST | `title`, `icon`, `kind` |
| `static/js/canvas.js:1914` | `/api/canvases/${id}` | GET | — |
| `static/js/canvas.js:1920` | `/api/canvases/${id}` | PUT | `title`, `icon`, `nodes`, `connections`, `viewport` |
| `static/js/canvas.js:2005` | `/api/ai/upload` | POST | multipart formdata |
| `static/js/canvas.js:2035` | `/api/generate` | POST | `prompt`, `model`, `negative_prompt`, `seed`, `sampler`, `steps`, `cfg_scale`, `image`, `denoise_strength`, `mask`, `width`, `height`, `batch_size`, `restore_faces`, `tiling`, `control`, `provider_id` |
| `static/js/canvas.js:2143` | `/api/generate/modelscope` | POST | `prompt`, `model`, `negative_prompt`, `seed`, `sampler`, `steps`, `cfg_scale`, `image`, `denoise_strength`, `width`, `height`, `batch_size`, `control`, `control_model` |
| `static/js/canvas.js:2211` | `/api/generate/video` | POST | `prompt`, `negative_prompt`, `model`, `video_model`, `width`, `height`, `image`, `num_frames`, `fps`, `motion_bucket_id`, `augmentation_level`, `seed`, `provider_id` |
| `static/js/canvas.js:2330` | `/api/runninghub/generate` | POST | `workflow_id`, `workflow_config`, `inputs`, `assets`, `provider_id` |
| `static/js/canvas.js:2401` | `/api/comfy/upload` | POST | multipart formdata |
| `static/js/canvas.js:2466` | `/api/comfy/progress/${id}` | GET | — |
| `static/js/canvas.js:2498` | `/api/comfy/interrupt` | POST | — |
| `static/js/canvas.js:2522` | `/api/comfy/generate` | POST | `prompt`, `workflow`, `images`, `node_id_overrides`, `instance_id` |
| `static/js/canvas.js:2732` | `/api/ltx/upload` | POST | multipart formdata |
| `static/js/canvas.js:2787` | `/api/ltx/generate` | POST | `node_id`, `config`, `uploads` |
| `static/js/canvas.js:2823` | `/api/ltx/progress/${nodeId}` | GET | — |
| `static/js/canvas.js:2866` | `/api/canvases/${canvasId}/duplicate` | POST | — |
| `static/js/canvas.js:2926` | `/api/workflows/export` | POST | `nodes`, `connections`, `include_assets` |
| `static/js/canvas.js:2959` | `/api/workflows/import` | POST | multipart formdata |
| `static/js/canvas.js:3055`、`static/js/canvas.js:3187` | `/api/asset-library` | GET | — |
| `static/js/canvas.js:3056`、`static/js/canvas.js:3188`、`static/js/canvas.js:3737` | `/api/local-assets` | GET | — |
| `static/js/canvas.js:3108` / `:3385` | `/api/asset-library/items/${id}` | PATCH | `name`（3108）；`name`, `category_id`（3385） |
| `static/js/canvas.js:3119` / `:3406` | `/api/asset-library/items/${id}` | DELETE | — |
| `static/js/canvas.js:3268` | `/api/asset-library/categories` | POST | `name`, `type`, `parent_id` |
| `static/js/canvas.js:3297` | `/api/asset-library/categories/${id}` | PATCH | `name` |
| `static/js/canvas.js:3320` | `/api/asset-library/categories/${id}` | DELETE | — |
| `static/js/canvas.js:3351` | `/api/asset-library/items` | POST | multipart formdata |
| `static/js/canvas.js:3556` | `/api/chat` | POST | `model`, `messages`, `system_prompt`, `provider_id`, `stream`, `options` |
| `static/js/canvas.js:3617` | `/api/config` | GET | — |
| `static/js/canvas.js:3677` / `:3718` | `/api/local-assets/upload` | POST | multipart formdata |
| `static/js/canvas.js:3780` | `/api/asset-library/workflows` | POST | multipart formdata |
| `static/js/canvas.js:3813` | `/api/asset-library/workflows/${id}` | DELETE | — |
| `static/js/canvas.js:3842` | `/api/asset-library/workflows/${id}` | PATCH | `name`, `category_id` |
| `static/js/canvas.js:4228` / `:4255` | `/api/ai/upload` | POST | multipart formdata |
| `static/js/canvas.js:4332` | `/api/canvases/batch-history` | GET | — |
| `static/js/canvas.js:4353` | `/api/canvases/batch-history` | DELETE | — |
| `static/js/canvas.js:4372` | `/api/canvases/batch-history/tasks/${taskId}` | DELETE | — |
| `static/js/canvas.js:4394` | `/api/canvases/batch-history/tasks/${taskId}/retry` | POST | — |

其他 canvas.js fetch（≥ 30 处，覆盖 `/api/runninghub/*`、`/api/online-image`、`/api/image-task-query`、`/api/canvas-workflows/*`、`/api/canvases/*/thumbnail` 等）：见 §14 待补一览。PR-2 落地 `shared/api-client/legacy/endpoints.js` 时须以本节 + `canvas.js` 全量 grep 为直接输入。

### 7.2 smart-canvas.js（17035 行，58 处 fetch，节选主 URL）

| file:line | URL | method | 关键 body 字段 |
|---|---|---|---|
| `static/js/smart-canvas.js:248` | `/api/config` | GET | — |
| `static/js/smart-canvas.js:270` | `/api/canvases/${canvasId}` | GET | — |
| `static/js/smart-canvas.js:298` | `/api/canvases/${canvasId}` | PUT | `title`, `icon`, `nodes`, `connections`, `viewport`, `client_id`, `base_updated_at` |
| `static/js/smart-canvas.js:396` | `/api/ai/upload` | POST | multipart formdata |
| `static/js/smart-canvas.js:424` | `/api/local-assets/upload` | POST | multipart formdata |
| `static/js/smart-canvas.js:462`、`:610` | `/api/asset-library` | GET | — |
| `static/js/smart-canvas.js:463`、`:611` | `/api/local-assets` | GET | — |
| `static/js/smart-canvas.js:528` | `/api/asset-library/items/${id}` | PATCH | `name` |
| `static/js/smart-canvas.js:539` | `/api/asset-library/items/${itemId}` | DELETE | — |
| `static/js/smart-canvas.js:691` | `/api/asset-library/categories` | POST | `name`, `type`, `parent_id` |
| `static/js/smart-canvas.js:720` | `/api/asset-library/categories/${id}` | PATCH | `name` |
| `static/js/smart-canvas.js:743` | `/api/asset-library/categories/${id}` | DELETE | — |
| `static/js/smart-canvas.js:774` | `/api/asset-library/items` | POST | multipart formdata |
| `static/js/smart-canvas.js:808` | `/api/asset-library/items/${id}` | PATCH | `name`, `category_id` |
| `static/js/smart-canvas.js:829` | `/api/asset-library/items/${id}` | DELETE | — |
| `static/js/smart-canvas.js:1285` | `/api/workflows/export` | POST | `nodes`, `connections`, `include_assets` |
| `static/js/smart-canvas.js:1318` | `/api/workflows/import` | POST | multipart formdata |
| `static/js/smart-canvas.js:1573` | `/api/chat` | POST | `model`, `messages`, `system_prompt`, `provider_id`, `stream`, `options` |
| `static/js/smart-canvas.js:1639` | `/api/generate` | POST | 同 §7.1 `/api/generate` |
| `static/js/smart-canvas.js:1753` | `/api/generate/modelscope` | POST | 同 §7.1 |
| `static/js/smart-canvas.js:1821` | `/api/generate/video` | POST | 同 §7.1 |
| `static/js/smart-canvas.js:1940` | `/api/runninghub/generate` | POST | 同 §7.1 |
| `static/js/smart-canvas.js:2011` | `/api/comfy/upload` | POST | multipart formdata |
| `static/js/smart-canvas.js:2076` | `/api/comfy/progress/${id}` | GET | — |
| `static/js/smart-canvas.js:2108` | `/api/comfy/interrupt` | POST | — |
| `static/js/smart-canvas.js:2132` | `/api/comfy/generate` | POST | `prompt`, `workflow`, `images`, `node_id_overrides`, `instance_id` |
| `static/js/smart-canvas.js:2737` | `/api/runninghub/query?taskId=${taskId}` | GET | — |
| `static/js/smart-canvas.js:2914` | `/api/workflows` | GET | — |
| `static/js/smart-canvas.js:3004` | `/api/asset-library/workflows` | POST | multipart formdata |
| `static/js/smart-canvas.js:3037` | `/api/asset-library/workflows/${id}` | DELETE | — |
| `static/js/smart-canvas.js:3066` | `/api/asset-library/workflows/${id}` | PATCH | `name`, `category_id` |

其余 smart-canvas.js fetch（≈ 25 处）覆盖 `/api/canvas-image-tasks`、`/api/canvas-video`、`/api/media-preview`、`/api/download-output`、`/api/upload`、`/api/asset-library/import-from-url`、`/api/runninghub/*` 等；PR-2 需全量迁移。

### 7.3 api-settings.js（3896 行，25 处）

| file:line | URL | method | 关键 body |
|---|---|---|---|
| `static/js/api-settings.js:937` | `/api/runninghub/workflows/${entryId}` | DELETE | — |
| `static/js/api-settings.js:1056` | `/api/runninghub/workflows/${workflowId}` | GET | — |
| `static/js/api-settings.js:1191` | `/api/runninghub/app-info?webappId=${appId}` | GET | — |
| `static/js/api-settings.js:1215` | `/api/runninghub/workflows/fetch` | POST | `url` |
| `static/js/api-settings.js:1384` | `/api/runninghub/workflows/${config.workflowId}` | PATCH | `config` |
| `static/js/api-settings.js:1568` | `/api/ai/upload` | POST | multipart formdata |
| `static/js/api-settings.js:1624` | `/api/runninghub/upload-asset` | POST | multipart formdata |
| `static/js/api-settings.js:1725` | `/api/runninghub/query?taskId=${taskId}` | GET | — |
| `static/js/api-settings.js:2654` | `/api/jimeng/status` | GET | — |
| `static/js/api-settings.js:2670` | `/api/jimeng/login/start` | POST | — |
| `static/js/api-settings.js:2689` | `/api/jimeng/login/status` | GET | — |
| `static/js/api-settings.js:2708` | `/api/jimeng/credit` | GET | — |
| `static/js/api-settings.js:2723` | `/api/jimeng/logout` | POST | — |
| `static/js/api-settings.js:2749` | `/api/jimeng/help` | POST | `command` |
| `static/js/api-settings.js:2773` | `/api/codex/status` | GET | — |
| `static/js/api-settings.js:2800` | `/api/codex/help` | POST | `command` |
| `static/js/api-settings.js:2824` | `/api/gemini-cli/status` | GET | — |
| `static/js/api-settings.js:2851` | `/api/gemini-cli/help` | POST | `command` |
| `static/js/api-settings.js:2870` | `/api/providers` | GET | — |
| `static/js/api-settings.js:2922` | `/api/providers/${id}` | GET | — |
| `static/js/api-settings.js:3016` | `/api/providers` | POST | `provider` |
| `static/js/api-settings.js:3087` | `/api/providers/${id}` | PUT | `provider` |
| `static/js/api-settings.js:3111` | `/api/providers/${id}` | DELETE | — |
| `static/js/api-settings.js:3130` | `/api/providers/${id}/keys` | POST | `key_type`, `api_key` |
| `static/js/api-settings.js:3158` | `/api/providers/${id}/keys` | DELETE | `key_type` |
| `static/js/api-settings.js:3177` | `/api/providers/${id}/models/fetch` | POST | — |
| `static/js/api-settings.js:3215` | `/api/providers/${id}/models` | PUT | `models` |
| `static/js/api-settings.js:3236` | `/api/providers/${id}/comfy/instances` | PUT | `instances` |
| `static/js/api-settings.js:3260` | `/api/providers/${id}/test` | POST | — |
| `static/js/api-settings.js:3321` | `/api/providers/${id}/rh-apps/fetch` | POST | — |
| `static/js/api-settings.js:3359` | `/api/providers/${id}/rh-workflows/fetch` | POST | — |
| `static/js/api-settings.js:3459` | `/api/providers/${id}/rh-workflows` | PUT | `workflows` |
| `static/js/api-settings.js:3480` | `/api/asset-library/import-from-url` | POST | `url`, `asset_type` |
| `static/js/api-settings.js:3506` | `/api/asset-library/upload` | POST | multipart formdata |

### 7.4 canvas-list.js（1051 行，15 处）

**注**：本节 file:line 引用为前端 PR-0 首批冻结时（2026-07-16）行号，之后 canvas-list.js 已发生行号漂移与部分调用点重构；每行括号补录 **前端 PR-2**（2026-07-17）grep 复审事实 `src=file:line`。CB-01 后续义务在此节完成一次全表复审——URL/method 语义均对齐源码，但 §7.4 表格里的 `/api/canvases/trash/${id}` DELETE 与 `/api/canvases/${id}/touch` POST 需要订正（详见下方"CB-01 §7.4 全表复审订正"）。

| file:line | URL | method | 关键 body |
|---|---|---|---|
| `static/js/canvas-list.js:50`（src=`canvas-list.js:183`，前端 PR-2 已迁到 `apiClient.get(LIST_CANVASES)`） | `/api/canvases` | GET | — |
| `static/js/canvas-list.js:64`（src=`canvas-list.js:903`、`:931`，前端 PR-2 已迁到 `apiClient.get(LIST_CANVASES_TRASH)`） | `/api/canvases/trash` | GET | — |
| `static/js/canvas-list.js:103`（src=`canvas-list.js:531`） | `/api/canvases` | POST | `title`, `icon`, `kind` |
| `static/js/canvas-list.js:152`（src=`canvas-list.js:855`） | `/api/canvases/${id}/meta` | POST | `pinned`, `color`, `owner` |
| `static/js/canvas-list.js:221`（src=`canvas-list.js:595`、`:750`；`:595` 前端 PR-2 已迁到 `apiClient.get(CANVAS_BY_ID(id))`） | `/api/canvases/${id}` | GET | — |
| ~~`static/js/canvas-list.js:232`~~（**订正**：源码未发现 `PUT /api/canvases/${id}`；canvas-list.js 只做元数据 POST 不做整包 PUT。整包 PUT 在 `canvas.js`；参见 §7.1） | ~~`/api/canvases/${id}`~~ | ~~PUT~~ | ~~`title`, `icon`, `nodes`, `connections`, `viewport`~~ |
| `static/js/canvas-list.js:273`（src=`canvas-list.js:890`） | `/api/canvases/${id}` | DELETE | — |
| ~~`static/js/canvas-list.js:310`~~（**订正**：源码未发现 `DELETE /api/canvases/trash/${id}`；实际为 `DELETE /api/canvases/${id}/purge` at `canvas-list.js:1002`） | ~~`/api/canvases/trash/${id}`~~ | ~~DELETE~~ | ~~—~~ |
| `static/js/canvas-list.js:1002`（前端 PR-2 grep 事实；§7.4 首批表格未收录） | `/api/canvases/${id}/purge` | DELETE | — |
| `static/js/canvas-list.js:341`（src=`canvas-list.js:992`） | `/api/canvases/${id}/restore` | POST | — |
| ~~`static/js/canvas-list.js:383`~~（**订正**：源码未发现 `POST /api/canvases/${id}/touch` in canvas-list.js；`touch` 端点在 `canvas.js:1643` 附近，属 §7.1 范围而非 §7.4） | ~~`/api/canvases/${id}/touch`~~ | ~~POST~~ | ~~—~~ |
| 其余（projects 相关） | `/api/projects` 及子路径 | GET/POST/PUT/DELETE | 见文件（前端 PR-2 grep：`canvas-list.js:182`、`:307`、`:331`、`:349`） |

**CB-01 §7.4 全表复审订正**（前端 PR-2，2026-07-17）：

- 三处笔误（划线部分）已在本 PR 内订正：`PUT /api/canvases/${id}`、`DELETE /api/canvases/trash/${id}`、`POST /api/canvases/${id}/touch` 均**在 canvas-list.js 中不存在**，源码 grep 命中数=0。
- 补录 `DELETE /api/canvases/${id}/purge`（源码 `canvas-list.js:1002`，§7.4 首批表格漏收）。
- 其余 URL / method 语义与源码一致，仅 file:line 行号漂移。行号漂移由后续 PR 触发的迁移点渐进订正——不属"URL 契约漂移"，不违反 §7.8 冻结。
- **本 §7.4 订正范围仅限 canvas-list.js**；§7 全表还有其他大规模行号漂移与部分 URL 已不存在于源码（如 §7.1 中 `/api/generate`、`/api/comfy/generate`、`/api/ltx/*`、`/api/canvases/batch-history*`、`/api/canvases/${id}/duplicate`、`/api/generate/modelscope`、`/api/generate/video`、`/api/runninghub/generate`——canvas.js 源码 grep 命中数=0），详见"CB-01 §7 全表复审报告"章节。

### 7.5 comfyui-settings.js（1397 行，10 处）

| file:line | URL | method | 关键 body |
|---|---|---|---|
| `static/js/comfyui-settings.js:40` | `/api/workflows` | GET | — |
| `static/js/comfyui-settings.js:107` | `/api/workflows` | POST | multipart formdata |
| `static/js/comfyui-settings.js:152` | `/api/workflows/${id}` | PUT | `title`, `workflow`, `ui` |
| `static/js/comfyui-settings.js:182` | `/api/workflows/${id}` | DELETE | — |
| `static/js/comfyui-settings.js:206` | `/api/comfy/object_info/${id}` | GET | — |
| `static/js/comfyui-settings.js:240` | `/api/comfy/history/${id}` | GET | — |
| `static/js/comfyui-settings.js:269` | `/api/comfy/queue/${id}` | GET | — |
| `static/js/comfyui-settings.js:208` | `/api/comfyui/instances` | GET | — |
| `static/js/comfyui-settings.js:241` | `/api/comfyui/instances` | PUT | `instances` |
| `static/js/comfyui-settings.js:1181` | `/api/upload` | POST | multipart formdata |

### 7.6 asset-manager.js（4764 行，走 `apiJson` wrapper；关键 5 处直接 fetch）

| file:line | URL | method | 关键 body |
|---|---|---|---|
| `static/js/asset-manager.js:48` | `/api/asset-library` | GET | — |
| `static/js/asset-manager.js:124` | `/api/asset-library/categories` | POST | `name`, `type`, `parent_id` |
| `static/js/asset-manager.js:153` | `/api/asset-library/categories/${id}` | PATCH | `name` |
| `static/js/asset-manager.js:176` | `/api/asset-library/categories/${id}` | DELETE | — |
| `static/js/asset-manager.js:204` | `/api/asset-library/items` | POST | multipart formdata |
| `static/js/asset-manager.js:206` | `/api/storage-settings` | PATCH（`apiJson`） | dirs payload |
| `static/js/asset-manager.js:233` | `/api/asset-library/items/${id}` | PATCH | `name`, `category_id` |
| `static/js/asset-manager.js:253` | `/api/asset-library/items/${id}` | DELETE | — |
| `static/js/asset-manager.js:274` | `/api/asset-library/workflows` | POST | multipart formdata |
| `static/js/asset-manager.js:302` | `/api/asset-library/workflows/${id}` | DELETE | — |
| `static/js/asset-manager.js:327` | `/api/asset-library/workflows/${id}` | PATCH | `name`, `category_id` |
| `static/js/asset-manager.js:2583`、`:2612`、`:2674`、`:2706` | `/api/canvas-assets/download` 相关 | GET/POST | — |

### 7.7 history-bulk-manager.js（1 处直接 fetch + 3 处 `apiJson`）

| file:line | URL | method |
|---|---|---|
| `static/js/history-bulk-manager.js:12` | `/api/canvases/batch-history` | GET |
| `static/js/history-bulk-manager.js:33` | `/api/canvases/batch-history` | DELETE |
| `static/js/history-bulk-manager.js:52` | `/api/canvases/batch-history/tasks/${taskId}` | DELETE |
| `static/js/history-bulk-manager.js:74` | `/api/canvases/batch-history/tasks/${taskId}/retry` | POST |

### 7.8 冻结要点

- **URL 字符串一律锁定**；PR-2 建 `shared/api-client/legacy/endpoints.js` 只做常量提取，禁止改路径、禁止改 method。
- 后端 PR-BE-01 生成 `tools/openapi_baseline.json` 时必须覆盖以上所有 URL；PR-2 迁移前需先跑 `tools/openapi_diff.py` 确认为空 diff。
- 所有 form-data 上传点（`/api/*/upload`、`/api/workflows`、`/api/workflows/import`、`/api/asset-library/items`、`/api/asset-library/workflows`）保留 multipart 语义，禁止改为 JSON。

### 7.9 CB-01 §7 全表复审报告（前端 PR-2，2026-07-17）

依据 [[CB-01]] 后续义务：前端 PR-2 落地 `endpoints.js` 常量化时对 §7 全表做一次 grep 对齐。本节记录本轮 grep 事实。

**已订正**（在本 PR 内直接修订仓内主 `docs/frontend-freeze/compat-contract.md`）：

| 章节 | 原（错） | 修（对） | 事实依据 |
|---|---|---|---|
| §7.4 | `canvas-list.js:232 PUT /api/canvases/${id}` | 划线（源码 grep 命中 0；整包 PUT 在 canvas.js §7.1） | `canvas-list.js` 无 PUT，源码 grep=0 |
| §7.4 | `canvas-list.js:310 DELETE /api/canvases/trash/${id}` | 划线并补录 `DELETE /api/canvases/${id}/purge` at `canvas-list.js:1002` | `main.py: @app.delete("/api/canvases/{canvas_id}/purge")` |
| §7.4 | `canvas-list.js:383 POST /api/canvases/${id}/touch` | 划线（`touch` 在 canvas.js，属 §7.1 而非 §7.4） | `canvas-list.js` 无 `touch`，源码 grep=0 |

**未订正 / 登记为 CB 候选**（超出本 PR 单次可承接的范围，追加到 [[70 开发过程跟踪/缺陷追踪]]，供 Lead 决定是否新建 CB-03 承接）：

1. **§7.1 canvas.js 大面积 URL 语义漂移**：以下端点在 §7.1 明确列出，但当前 `canvas.js` 源码 grep 命中数为 **0**——业务代码已迁到新端点：
   - `/api/generate`、`/api/generate/modelscope`、`/api/generate/video`（现由 `/api/canvas-image-tasks`、`/api/canvas-video`、`/api/canvas-comfy-tasks`、`/api/canvas-llm` 承担）。
   - `/api/comfy/upload`、`/api/comfy/progress/${id}`、`/api/comfy/interrupt`、`/api/comfy/generate`（现由 `/api/canvas-comfy-tasks` 承担；实例配置沿用 `/api/comfyui/instances`）。
   - `/api/ltx/upload`、`/api/ltx/generate`、`/api/ltx/progress/${nodeId}`（LTX Director 相关；canvas.js 已无 `/api/ltx/*` 调用）。
   - `/api/runninghub/generate`（现走 `/api/runninghub/submit` 与 `/api/runninghub/workflow-submit`）。
   - `/api/canvases/${canvasId}/duplicate`（源码 grep=0；`duplicate` 只在客户端函数名如 `duplicateNodesForAltDrag`）。
   - `/api/workflows/export`、`/api/workflows/import`（现由 `/api/canvas-workflows/export` / `-to-library` / `import` 承担）。
   - `/api/chat`（canvas.js 无直接调用；聊天走 `/api/canvas-llm`）。
   - `/api/local-assets/upload`（canvas.js 无直接调用，仅 `smart-canvas.js` 有）。
   - `/api/canvases/batch-history`、`/api/canvases/batch-history/tasks/${taskId}`、`/api/canvases/batch-history/tasks/${taskId}/retry`（canvas.js 无相关 fetch；`history-bulk-manager.js` 走 `/api/history/delete`，见 §7.7）。

2. **§7.1 canvas.js 新增未收录端点**（前端 PR-2 grep 事实源码存在，§7.1 未收录）：
   - `/api/canvas-image-tasks`、`/api/canvas-image-tasks/${taskId}`
   - `/api/canvas-comfy-tasks`、`/api/canvas-comfy-tasks/${taskId}`
   - `/api/canvas-video`、`/api/canvas-llm`
   - `/api/canvas-workflows/export`、`/api/canvas-workflows/export-to-library`、`/api/canvas-workflows/import`
   - `/api/canvas-assets/check`、`/api/canvas-assets/download`
   - `/api/prompt-libraries`、`/api/prompt-libraries/items`、`/api/prompt-libraries/items/delete`、`/api/prompt-libraries/categories`、`/api/prompt-libraries/categories/${id}`、`/api/prompt-libraries/${id}`、`/api/prompt-libraries/items/${id}`
   - `/api/asset-library/libraries`、`/api/asset-library/libraries/${id}`、`/api/asset-library/items/batch`、`/api/asset-library/items/delete`、`/api/asset-library/workflows/upload`
   - `/api/ai/import-local-image`、`/api/angle/generate`、`/api/ms/generate`、`/api/online-image`、`/api/upload`、`/api/cloud-video/upload`、`/api/download-output`、`/api/media-preview`、`/api/image-task-query`
   - `/api/canvases/${id}/purge`（DELETE）、`/api/canvases/${id}/restore`（POST）

3. **§7.2 smart-canvas.js**、**§7.3 api-settings.js**、**§7.6 asset-manager.js**：同类漂移。§7.3 表格中 `/api/providers/${id}` GET/PUT/DELETE、`/api/providers/${id}/keys`、`/api/providers/${id}/models`、`/api/providers/${id}/comfy/instances`、`/api/providers/${id}/test`、`/api/providers/${id}/rh-apps/fetch`、`/api/providers/${id}/rh-workflows/fetch`、`/api/providers/${id}/rh-workflows`、`/api/asset-library/import-from-url`、`/api/asset-library/upload` 在 `api-settings.js` 中均 grep=0（现由 `PUT /api/providers` 整包写、`POST /api/providers/test-connection`、`POST /api/providers/probe-async`、`POST /api/providers/fetch-models`、`POST /api/runninghub/workflows/fetch` 等承担）。§7.6 中 `asset-manager.js:48 /api/asset-library GET` 行号错（第 48 行是 `let selectedWorkflowIds = new Set();`）；asset-manager.js 大量调用点通过 `apiJson()` wrapper 走 `/api/*`，未列入 §7.6。

4. **§7.5 comfyui-settings.js**：URL / method **完全对齐**，仅 file:line 行号漂移（本 PR 已在 §7.5 部分保留原表；前端 PR-2 通过 `endpoints.js` `COMFYUI_INSTANCES` 常量迁移了 GET `:208` 一处）。CB-01 首批已订正过 `/api/comfy/instances → /api/comfyui/instances`，本轮无新增笔误。

**处置建议**：

- 上述 §7.1 / §7.2 / §7.3 / §7.6 全面 URL 漂移已超出单一 PR 承接边界；本 PR 不做 §7.1/§7.2/§7.3/§7.6 全表重写，只订正与本 PR 迁移点直接相关的 §7.4 三条硬笔误 + §7.5 交叉验证。
- 追加 **CB-03（候选）**：§7 全表与源码事实全面重建（前端组件化 M0 -> M1 交叠期集中订正），Lead 决定是否单开或由后续前端 PR-3/4/5 分批承接。
- 前端 PR-2 交付以 `endpoints.js` 常量表 + §7.4 三条订正 + 本 §7.9 复审报告为 CB-01 后续义务的完成证据。

---

## 8. HTML 内联 onclick 计数基线

| 页面 | onclick 计数 | 唯一 handler 数量 |
|---|---|---|
| `static/canvas.html` | 73 | 37 |
| `static/smart-canvas.html` | 59 | 30 |
| `static/api-settings.html` | 52 | 41 |
| `static/gpt-chat.html` | 38 | 14 |
| `static/comfyui-settings.html` | 14 | 12 |
| `static/index.html` | 24 | 13 |

（`event` / `document` 在 unique 集合内出现是 `onclick="event.stopPropagation()"` / `onclick="document.getElementById(...).focus()"` 的伪 handler，占位不计入迁移目标。）

### 8.1 唯一 handler 名单

- `canvas.html`：`addComfyNode` / `addGeneratorNode` / `addImageNode` / `addLLMNode` / `addLoopNode` / `addLTXDirectorNode` / `addMsGenNode` / `addOutputNode` / `addPromptNode` / `addRhNode` / `addVideoNode` / `applyGridPreset` / `applyImageEdit` / `clearEditDrawing` / `clearGridCustomLines` / `closeAssetManager` / `closeCanvasLog` / `closeErrorModal` / `closeImageEditor` / `closeOutputLightbox` / `closePromptTemplateModal` / `closeWorkflowTransferModal` / `copyErrorMessage` / `exportSelectedWorkflow` / `exportSelectedWorkflowToLibrary` / `groupSelectedImages` / `menuAdd` / `openCanvasLog` / `redoEditDrawing` / `resetCropBox` / `setBrushTool` / `setGridCustomOrientation` / `toggleGridCustomMode` / `toggleQuickToolbar` / `undoEditDrawing` / `undoGridCustomLine`。
- `smart-canvas.html`：`applyGridJoinPreset` / `applyGridPreset` / `applyImageEdit` / `backToCanvasList` / `clearEditDrawing` / `clearGridCustomLines` / `closeImageEditor` / `closeSmartCanvasLog` / `closeSmartCanvasShortcuts` / `closeSmartWorkflowTransferModal` / `downloadPreviewGroup` / `downloadPreviewImage` / `exportPanoramaFrame` / `exportSelectedSmartWorkflow` / `exportVideoFrame` / `navigatePreviewImage` / `openSmartCanvasLog` / `openSmartCanvasShortcuts` / `redoEditDrawing` / `resetGridJoinLayout` / `setBrushTool` / `setGridCustomOrientation` / `setGridJoinOutputSize` / `setGridOperationMode` / `toggleGridCustomMode` / `togglePanoramaPreview` / `togglePreviewCompare` / `undoEditDrawing` / `undoGridCustomLine`。
- `api-settings.html`：`addCliProvider` / `addModel` / `addMsLora` / `addProvider` / `applyModelPicker` / `clearKeyOnly` / `clearRhKeyOnly` / `clearVolcengineAssetKeys` / `closeCodexHelp` / `closeGeminiCliHelp` / `closeJimengHelp` / `closeModelPicker` / `closeRecommendApi` / `closeRhWorkflowEditor` / `createRhEntryFromPaste` / `deleteProvider` / `fetchModels` / `fetchRhWorkflowEditor` / `loadCodexHelp` / `loadGeminiCliHelp` / `loadJimengHelp` / `logoutJimeng` / `openCodexHelp` / `openGeminiCliHelp` / `openJimengHelp` / `openModelPicker` / `openRecommendApi` / `probeAsync` / `refreshCodexStatus` / `refreshGeminiCliStatus` / `refreshJimengCredit` / `rhEditorGraphFit` / `rhEditorGraphZoom` / `saveKeyOnly` / `saveProviders` / `saveRhKeyOnly` / `saveRhWorkflowEditor` / `saveVolcengineAssetKeys` / `selectPickerCat` / `startJimengLogin` / `testConnection`。
- `gpt-chat.html`：`applyCustomResolution` / `clearSystemPrompt` / `closeImagePreview` / `removeRef` / `saveSystemPromptFromUI` / `selectBuiltInRatio` / `selectResolutionPreset` / `sendMessage` / `setActiveModel` / `setModelPickerScope` / `setProvider` / `setResolutionPickerScope`（+ 伪 `document` / `event`）。
- `comfyui-settings.html`：`addComfyInstance` / `closeImagePreview` / `closeNodePopup` / `graphFit` / `graphZoom` / `onDelete` / `onSave` / `saveComfyInstances` / `setWorkspaceMode` / `toggleNodeList`。
- `index.html`：`checkForUpdates` / `closeProjectUpdateModal` / `confirmProjectUpdate` / `openProjectPage` / `runProjectUpdate` / `runUpdateConnectivityTest` / `setUpdateSource` / `switchUI` / `toggleLanguage` / `toggleLocalNav` / `toggleSidebarPinned` / `toggleSidebarSettings` / `toggleTheme`。

### 8.2 冻结要点

- 上述计数与 handler 名单作为**基线**：后续任何一版 PR 引入新 onclick 需在本文追加，删除 onclick 需先迁移到 `data-action` + `shared/interaction/action-bus.js`（PR-7 动作）。
- HTML 内联 `onclick="switchUI(...)"` / `menuAdd(...)` / `addImageNode(...)` 在 M7 之前**必须继续可用**（治理方案硬约束 §7）。

---

## 9. 节点 DOM 类名 / `data-*` 属性 / SVG 连线 class

### 9.1 节点根元素 class（`static/js/canvas.js:6031` renderNode 附近）

- 基础：`.node`（`canvas.js:6037` 起）。
- 类型类：`.image-node` / `.prompt-node` / `.loop-node` / `.promptGroup-node` / `.group-node` / `.output-node` / `.llm-node` / `.generator-node` / `.msgen-node` / `.video-node` / `.rh-node` / `.comfy-node` / `.ltxDirector-node`。
- 状态类：`.selected` / `.has-image` / `.sized`。
- 结构类：`.node-head` / `.node-title` / `.node-body` / `.node-run-status` / `.image-preview-wrap` / `.image-caption` / `.blank-image` / `.prompt-editor` / `.prompt-toolbar` / `.prompt-template-btn` / `.resize-handle` / `.port` / `.port.in` / `.port.out`。
- 运行状态：`.queued` / `.running` / `.done` / `.failed`（`canvas.js:6063-6064`）。

### 9.2 data-* 属性

- 节点根：`data-id`（`canvas.js:6042`）。
- 图像/预览：`data-preview-src`、`data-original-src`、`data-url`、`data-preview-kind`（`canvas.js:6069-6156`）。
- 提示词：`data-prompt-template-open`、`data-prompt-template-node-id`（`canvas.js:6158-6176`）。
- 输出：`data-pending-id`、`data-output-url`、`data-output-key`、`data-output-html`、`data-media-kind`、`data-media-url`（`canvas.js:6217-6236` 与 `:6362-6400`）。

### 9.3 SVG 连线 class（`renderConnections`；智能画布 `smart-canvas.js:6079` 附近；经典画布 `canvas.js` 内相邻函数）

- 图层：`.connection-layer`。
- 线段：`.conn-line` / `.conn-hit`（透明命中）/ `.conn-end` / `.conn-cut`。
- 状态：`.conn-pending` / `.conn-cascade` / `.conn-cascade-done` / `.conn-cascade-wait` / `.conn-cascade-active` / `.conn-history` / `.conn-selected` / `.conn-reduce-motion`。
- data 属性：`data-conn-index`（合并连线索引）。
- 视觉属性（属基线）：`stroke`（级联 `#16a34a`、历史 `rgba(100,116,139,0.46)`、输入 `rgba(100,116,139,0.62)`、其他 `rgba(148,163,184,0.62)`）；`stroke-width`（输入 1.9，其他 1.6）；`opacity`（pending 0.82，其他 1）。
- 路径：`d`（贝塞尔），历史用下垂曲线，其他用侧连曲线（`smart-canvas.js:6131-6133`）。

### 9.4 智能画布特有节点分类

`smart-canvas.js` 的 `renderNode` 引入 smart-container / smart-image legacy alias（详见 [[节点系统治理方案]] `smart-container → smart-image`）。M7 facet 化不动 alias。

### 9.5 冻结要点

- 上述所有 class 名 / data-* 属性名一律**锁定**；PR-7 引入 `NodeRenderRegistry` 与 `renderShell` 时必须复用原名。
- `.conn-*` 系列不改；连线合并规则（`smart-canvas.js:6094-6105`）作为契约保留。

---

## 10. Canvas 409 冲突两种响应 shape

后端在 Canvas 保存冲突时可能返回两种 shape，前端消费点必须兼容读。

### 10.1 经典画布（`static/js/canvas.js:1425-1434`）

- 优先读 `data.detail.canvas`；其次读 `data.canvas`。
- 时间戳字段：`data.detail.updated_at` → `data.updated_at` → `remote?.updated_at` 兜底。
- 若 `localCanvasDirty || saveCanvasAgain`：只更新 `lastCanvasUpdatedAt`，设置 `saveCanvasAgain = true`，重试保存；否则 `applyRemoteCanvasData(remote)`。

### 10.2 智能画布（`static/js/smart-canvas.js:5833-5849`）

- 只读 `data.detail.canvas`（**没有 `data.canvas` 分支**）。
- `data.detail.canvas` 缺失时至少同步 `data.detail.updated_at` 到 `canvas.updated_at`。
- 走 `applyMergedServerCanvas(serverCanvas)`：节点 id 合并，图片取并集，然后 300 ms 后重存（`setTimeout(saveCanvas, 300)`）。

### 10.3 冻结要点

- **两种 shape 必须双兼容读**：后端可只返回其中一路，前端必须无论哪路都能正确恢复；PR-2 的 `CanvasConflictError` 需要保留 `remote` / `updated_at` 双入口。
- 智能画布的 “合并写” 策略是**已冻结行为**；PR-6 抽 `canvasEditStore` 时必须保留 300 ms 重存与合并语义。

---

## 11. `base_updated_at` / `revision` / `client_id === CLIENT_ID` 自我识别语义

### 11.1 `CLIENT_ID` 常量定义

- `canvas.js:473`：`const CLIENT_ID = 'canvas_' + Math.random().toString(36).slice(2);`
- `smart-canvas.js`（对应位置）使用同族常量 `smartClientId`（详见 `smart-canvas.js:5216` 附近）。
- 语义：每次页面刷新生成新的 `CLIENT_ID`；同一浏览器 Tab 内寿命一次。**跨 Tab 不共享**。

### 11.2 保存时上行（`base_updated_at` / `client_id`）

- `canvas.js:1421-1422`：PUT `/api/canvases/${id}` body 含 `client_id: CLIENT_ID`、`base_updated_at: Number(lastCanvasUpdatedAt || canvas.updated_at || 0)`。
- `smart-canvas.js:5826`：PUT `/api/canvases/${id}` body 含 `base_updated_at: storageCanvas.updated_at || canvas.updated_at || 0`。

后端使用 `base_updated_at` 判定“基于哪一版编辑”，如与库中 `updated_at` 不一致返回 409。

### 11.3 下行自我识别（跳过自己发的更新）

- 经典画布 `handleCanvasUpdatedMessage`（`canvas.js:2169-2174`）：
  - `data.client_id === CLIENT_ID` → return；
  - `remoteUpdatedAt <= lastCanvasUpdatedAt` → return；
- 智能画布 `handleCanvasUpdatedMessage`（`smart-canvas.js:5213-5219`）：
  - `data.client_id === smartClientId` → return；
  - `canvasSyncInFlight` 期间 → return（保存中不重复合并）；
  - `remoteUpdatedAt <= canvas?.updated_at` → return。

### 11.4 `applyingRemoteCanvas` 屏蔽保存

- `canvas.js:372`：`let applyingRemoteCanvas = false;`
- `canvas.js:1350`（`scheduleSave`）与 `canvas.js:1402`（`saveCanvas`）：`if(!canvas || applyingRemoteCanvas) return;`
- `canvas.js:1454`：`if(saveCanvasAgain && canvas && !applyingRemoteCanvas)` 才重试保存。
- `canvas.js:2050`：`applyRemoteCanvasData` 内 try/finally 严格清标志。

### 11.5 `revision` 字段

- **未定位到** `revision` 语义（详见 §14）。当前保存冲突识别完全依赖 `base_updated_at` + `updated_at` 大小比较 + `client_id` 自我识别；后端亦未在响应中返回 `revision`。若后端后续引入 `revision`，需按“合规扩展”路径同步治理方案与本文。

### 11.6 冻结要点

- `client_id === CLIENT_ID` 自我过滤语义**必须保留**；PR-3 的 bus 在同一 Tab 内不能因结构重整而收到自己发的消息回环。
- `base_updated_at` 字段名冻结；`0` 作为初次保存 sentinel 值保留。
- `applyingRemoteCanvas` 标志由 PR-6 迁到 `canvasEditStore` 时须继续屏蔽保存路径。

---

## 12. 中文错误 / 提示文案基线

治理方案硬约束：中文 `detail` pass-through 不允许换文案，`friendlyMessage` 仅在 `err.message` 为空时兜底。以下 30+ 条覆盖协调纲要要求的 20 条最小面，重点是保存 / 上传 / Provider / 冲突 / 未登录 类场景。

| 文案 | 就近函数 / 触发点 | file:line |
|---|---|---|
| `保存失败` | `saveCanvasMeta` catch | `static/js/canvas.js:1609` |
| `图标保存失败` | `saveCanvasIcon` catch | `static/js/canvas.js:1931`、`static/js/canvas.js:1935` |
| `重命名失败` | `renameCanvas` catch | `static/js/canvas.js:1995`、`static/js/canvas.js:1999` |
| `图片加载失败` | `loadImage` onerror | `static/js/canvas.js:2636` |
| `图片读取失败` | `loadImage` fetch 失败 | `static/js/canvas.js:2642` |
| `没有可上传的媒体` | `uploadNodeImageToCloud` | `static/js/canvas.js:3669` |
| `云端上传失败` | `uploadNodeImageToCloud` fetch 失败 | `static/js/canvas.js:3676` |
| `云端没有返回链接` | `uploadNodeImageToCloud` | `static/js/canvas.js:3679` |
| `已上传 {n} 个媒体文件到云端，首个链接已复制。链接约 3 天有效。` | 成功提示 | `static/js/canvas.js:3708` |
| `请输入 http/https 媒体网址或 asset:// 火山素材 URI` | 输入校验 | `static/js/canvas.js:3740` |
| `已清除手动网址。` | 提示 | `static/js/canvas.js:3736` |
| `已设置视频网址。` | 提示 | `static/js/canvas.js:3746` |
| `导入本地图片失败` | `importImagesFromLocalZip` 错误 | `static/js/canvas.js:3879` |
| `导入图片...` / `导入图片失败` | 状态 / errorModal | `static/js/canvas.js:3965`、`static/js/canvas.js:4053` |
| `双击编辑` | 文本节点 placeholder | `static/js/canvas.js:4147` |
| `暂无 API 平台` / `暂无 API 平台，请到 API 设置添加` | select placeholder | `static/js/canvas.js:667`、`static/js/canvas.js:1015` |
| `暂无模型，请到 API 设置添加` | select placeholder | `static/js/canvas.js:710`、`static/js/canvas.js:1019`、`static/js/canvas.js:1029`、`static/js/canvas.js:1505` |
| `暂无生图模型，请到 API 设置添加` | select placeholder | `static/js/canvas.js:1015` |
| `请求失败` | `apiErrorMessage` fallback | `static/js/canvas.js:794`、`static/js/canvas.js:817`；`static/js/smart-canvas.js:710`、`static/js/smart-canvas.js:731` |
| `缩放失败：当前图片无法写入画布，请换成本地图片或重新上传后再试。` | `alert` | `static/js/canvas.js:5726` |
| `Synced` / `Syncing...` / `Saved` / `Saving...` / `Save failed` | `setStatus`（英文状态） | `static/js/canvas.js` 多处 |
| `请先打开画布` | `showSmartWorkflowTransfer` | `static/js/smart-canvas.js:809` |
| `未选择节点，请先选中要导出的组件` | 智能画布导出 | `static/js/smart-canvas.js:826`、`static/js/smart-canvas.js:834` |
| `请先选中节点再导出；导入会追加到当前画布` | 子标题 | `static/js/smart-canvas.js:827` |
| `已导出智能画布工作流 JSON` | 成功提示 | `static/js/smart-canvas.js:840` |
| `导出工作流失败` | 错误提示 | `static/js/smart-canvas.js:853`、`static/js/smart-canvas.js:866` |
| `已导出 {n} 个节点，包含可找到的本地资源` | 成功提示 | `static/js/smart-canvas.js:858` |
| `工作流中没有可导入的节点` | 导入检查 | `static/js/smart-canvas.js:872` |
| `已导入 {n} 个节点` | 成功提示 | `static/js/smart-canvas.js:901` |
| `导入工作流失败` | 错误提示 | `static/js/smart-canvas.js:910`、`static/js/smart-canvas.js:916` |
| `已整理选中节点` | 成功提示 | `static/js/smart-canvas.js:2043` |
| （409 冲突注释）`冲突：别人先保存了。合并对方的状态（节点 id 合并、图片取并集，谁都不丢），然后用对方最新的 updated_at 作为基底重存，把合并结果落盘——而不是直接覆盖对方。` | 注释 | `static/js/smart-canvas.js:5834-5835` |

（"未登录" / "已保存" / "删除失败" 3 条**未定位到**精确字面量，详见 §14。M1/M2 PR 收敛登录/删除文案后再补齐。）

### 12.1 冻结要点

- 每个 PR 中文文案改动必须先登记到本节；`friendlyMessage` 兜底只允许在 `err.message` 为空时使用。
- 后端 `detail` 中文直接透传，前端不重写；`apiErrorMessage` fallback 仅 `请求失败`。

---

## 13. `serializableCanvasNode()` / `canvasForStorage()` 字段清单

### 13.1 `serializableCanvasNode`（`static/js/canvas.js:1387-1396`）

剥离的临时字段（不落盘）：

| 字段 | 用途 |
|---|---|
| `_ltxEditor` | LTX Director 编辑器状态 |
| `running` | 运行中标志 |
| `runStatus` | 运行状态字符串 |
| `runError` | 运行错误对象 |
| `_cascadeIdx` | 级联索引 |
| `_cascadeFailed` | 级联失败标志 |
| `_activeLoopCtx` | 活动循环上下文 |

调用点：`saveCanvas`（`canvas.js:1417`）、`serializableCanvasNodes`（`canvas.js:1398`）、`pushUndo`（`canvas.js:13455`）、`cloneNode`（`canvas.js:13468`）、`copySelectedNodes`（`canvas.js:13524`）、`selectedWorkflowPayload`（`canvas.js:13570`）、`importNodesFromWorkflow`（`canvas.js:13750`）。

### 13.2 `canvasForStorage`（`static/js/smart-canvas.js:699-708`）

流程：
1. `JSON.parse(JSON.stringify(canvas || {}))` 深克隆；
2. `clean.settings = settingsForStorage(...)`（settings 序列化）；
3. 过滤 `SMART_LOG_PREVIEW_NODE_ID` 临时节点；
4. 每个 node 的 `images` 走 `mediaItemForStorage`；`runSettings` 走 `settingsForStorage`。

### 13.3 `mediaItemForStorage`（`static/js/smart-canvas.js:689-698`）

剥离的临时字段：

| 字段 | 用途 |
|---|---|
| `cloudUrl` | 云端 URL 缓存 |
| `uploadedUrl` | 已上传 URL 缓存 |
| `originalRemoteUrl` | 原始远程 URL 缓存 |
| `tempCloudUrl` | 临时云端 URL |
| `_inlineVideoActive` | 内联视频激活标志 |

### 13.4 其他渲染层临时字段（应清理但可能在别处出现）

| 字段 | 出现位置 | 备注 |
|---|---|---|
| `_videoMultimodalUserSet` | `smart-canvas.js:328` | 用户是否手动设置多模态 |
| `_runMetaTargetId` | `smart-canvas.js:767` | 运行元数据目标 id |
| `_dom` | `smart-canvas.js:782` | DOM 引用（严禁落盘） |
| `_inlineVideoActive` | `smart-canvas.js:521`、`:529`、`:696` | 内联视频状态 |
| `_pending` | **未在源码中直接命中该字面量**（协调纲要点名） | 详见 §14 |
| `_renderPatchToken` | **未在源码中直接命中该字面量**（协调纲要点名） | 详见 §14 |

### 13.5 冻结要点

- **落盘字段：不新增、不改名**（治理方案 §保存冲突）。
- 临时字段清单是**清理必选项**：PR-6 迁 `canvasEditStore` 与 `updatePatch` 时，任何新增 `_` 前缀字段必须同步进入 `serializableCanvasNode` / `mediaItemForStorage` 清理链。
- `SMART_LOG_PREVIEW_NODE_ID` 临时节点过滤规则（`canvasForStorage` 内）不动。

---

## 14. 未定位到 / 待补条目

以下条目在本轮 grep 中**未在源码中定位到明确字面量**，登记为待补，供后续 PR 补齐或明确删除。

| # | 条目 | 期望位置 | 现状 | 处理建议 |
|---|---|---|---|---|
| U1 | iframe message type `refresh-workflows` | `index.html` / `canvas.js` | 未命中；实际由 BC `workflows-changed` 承载 | 从治理方案枚举清单中移除，或明确“别名”注解 |
| U2 | iframe message type `studio:api-changed` | 全域 | 未命中 | 从枚举清单中移除；或若后端预留了广播路径，待 Provider 版块回填 |
| U3 | iframe message type `storage-settings-changed` | `asset-manager.js` 附近 | 未命中；`/api/storage-settings` PATCH 存在（`asset-manager.js:206`）但无广播 | 若需要多 tab 同步存储设置，待文件 PR-0 落地后追加广播；本 PR 先记录“未广播” |
| U4 | `loadWorkflows` 独立全局函数 | 各 JS 顶层 | 只有 `loadList` (`comfyui-settings.js:259`) 与 `loadConfig` 内部 fetch `/api/workflows` | 定义补：在 PR-2 `shared/api-client/domains/workflowApi.js` 内提供命名函数；旧代码保留原调用 |
| U5 | `revision` 字段（画布相关） | Canvas save/response | 后端与前端均未使用 `revision`；只用 `base_updated_at` + `updated_at` | 后端不新增前，本合同不列 `revision`；数据 PR 若引入需同步治理方案 |
| U6 | 临时字段 `_pending` | `serializableCanvasNode` 附近 | 源码中未见字面量 `_pending`（有 `pending` / `pendingTasks` 等其他语义） | 若指的是渲染层 pending，请后续 PR-6 定义命名；本 PR 先登记不存在 |
| U7 | 临时字段 `_renderPatchToken` | 渲染层 | 源码中未见字面量 | 同 U6，PR-6 引入 `updatePatch` 时正式定义 |
| U8 | 文案 `未登录` | Provider / Chat / Session 相关 | 未 grep 到字面量 | PR-9 sessionStore 落地时补齐 |
| U9 | 文案 `已保存` / `删除失败` | 通用 toast | 未 grep 到字面量（现状用英文 `Saved` / `Save failed` 或不同措辞） | PR-2 / PR-8 Toast 组件收敛时统一 |
| U10 | `event.origin` 白名单 | iframe message 处理 | 现状**无 origin 白名单**（同源 iframe） | PR-3 建 bus 时保留同源接受策略；不加入新校验前不视为漏洞 |

---

## 15. 触及的源码文件清单

以下文件是本 PR 全部 grep 触及的清单，作为 PR-1 保活烟测清单交叉核对时的“基线源码集合”。

- HTML（16）：`static/index.html`、`static/canvas.html`、`static/smart-canvas.html`、`static/canvas-list.html`、`static/api-settings.html`、`static/comfyui-settings.html`、`static/asset-manager.html`、`static/gpt-chat.html`、`static/enhance.html`、`static/klein.html`、`static/angle.html`、`static/zimage.html`、`static/online.html`。
- JS（14）：`static/js/canvas.js`、`static/js/smart-canvas.js`、`static/js/api-settings.js`、`static/js/asset-manager.js`、`static/js/canvas-list.js`、`static/js/comfyui-settings.js`、`static/js/history-bulk-manager.js`、`static/js/theme.js`、`static/js/i18n.js`、`static/js/i18n-core.js`、`static/js/image-preview.js`、`static/js/ltx-director-timeline.js`、`static/js/touch-mouse.js`、`static/js/i18n/*.js`。

---

## 16. 下一 PR（前端 PR-1）如何消费本清单

PR-1（保活烟测清单 22 项 + 人工烟测模板）应按下列方式引用本文档：

1. **烟测项直接引用本文段落**：
   - 第 7 项（保存冲突 shape）→ §10；
   - 第 10 项（两标签同步）→ §11 与 §3；
   - 第 12 项（WebSocket 事件）→ §3；
   - 第 14 项（Provider 广播）→ §2；
   - 第 17 项（素材 inbox）→ §4；
   - 第 19 项（旧 URL 探测）→ §7；
   - 第 20 项（旧 localStorage 兼容）→ §4；
   - 第 21 项（两标签改 Provider）→ §2 + §5；
2. **人工烟测模板每项附**：期望文案 / 期望 URL / 期望 WebSocket type / 期望 fetch URL / 期望 localStorage key。所有期望值必须从本文 §1 ～ §13 复制，禁止在烟测模板中另写“新字符串”。
3. **执行记录**：Windows + macOS 双端执行；截图落 `docs/frontend-smoke/screenshots/`（PR-1 产出）；未通过项回填到 §14 的对应条目。
4. **CI 守护种子**：PR-7 落地 CI “禁字段名”正则时，应把本文 §13.4 中标注 `未在源码中直接命中` 的字段名（`_pending` / `_renderPatchToken`）加入“预留字段名”名单，PR-6 引入后再从守护清单剔除。
5. **后续变更登记**：任何 PR 若新增 iframe message type / BC 消息 / WS 事件 / localStorage key / URL 参数 / 全局函数 / fetch URL / node class / 中文文案，必须在同 PR 内追加到本文对应段落；否则 review 拒绝合入。

---

## 相关文档

- [[前端组件化治理方案]]
- [[前端组件化治理实施计划与PR清单]]
- [[前端现状架构地图]]
- [[画布节点系统现状地图]]
- [[节点系统治理方案]]
- [[文件对象与 MinIO 治理方案]]
- [[2026-07-16 首批 PR 开工协调纲要]]

## 变更记录

- 2026-07-16：初版落地（前端 PR-0）。
