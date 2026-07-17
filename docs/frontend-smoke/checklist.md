# 前端保活烟测清单（PR-1 落地版 · 22 项）

## 文档定位

本文是 Infinite Canvas 前端组件化治理 M0 阶段 PR-1 的交付物：把 [[前端组件化治理方案#烟测清单]] 的 22 项落地为**可人工执行**的最小复现步骤 + 期望结果 + 记录模板，作为后续所有前端 PR（M1 → M7）的保活合同。

- 依据：`docs/frontend-freeze/compat-contract.md`（前端 PR-0 冻结清单，本文所有期望值 1:1 引用其中的字符串 / URL / message type / localStorage key / 中文文案）；`docs/backend-smoke/checklist.md`（后端 PR-BE-01 14 项）；[[前端组件化治理实施计划与PR清单]] PR-1；[[前端组件化治理方案]]"烟测清单"章节。
- 时间：2026-07-16。
- 范围：仅前端交互层与跨页保活；不入 CI，仅人工验收（治理方案已决议"先人工，PR-10 后再入 Playwright"）。
- 硬约束：
  - 本 PR **不写任何业务代码**、不建 `static/js/shared/` 目录（M1 才启动）。
  - 所有期望文案 / URL / message type / localStorage key **必须**从 `docs/frontend-freeze/compat-contract.md` 复制，禁止自造。
  - **不合并、不改写 22 项编号**——后续 PR 描述通过编号引用（"覆盖第 X 项 / 不涉及第 Y 项"）。
- 引用格式：`compat-contract §X` 均指 `docs/frontend-freeze/compat-contract.md` 对应章节；`backend-smoke item N` 指 `docs/backend-smoke/checklist.md` 对应编号。

同名镜像：`E:\个人知识库\Infinite Canvas 二开与架构治理项目知识库\90 资料归档\前端保活烟测清单模板.md`；仓内为主，知识库为镜像，任何变更以仓内为准（字节 1:1）。

## 使用方式

1. 每个前端 PR（PR-2 起）在 PR 描述中粘贴本清单执行结果表格；不涉及项写"不涉及 / 编号 N"，通过写 `[x] 通过`，失败写 `[ ] 失败 备注：…`。
2. 双端执行：Windows + macOS 各跑一遍（第 1、2、3 项决定入口，其余项在打开首页后共用）。
3. 若某条烟测发现未通过，**先停手**：把失败点回写到 `docs/frontend-freeze/compat-contract.md` §14"未定位到 / 待补条目"表格，或走"合规扩展"路径。
4. U1–U10 未定位项：本清单在期望值处标注"未定位到，暂不作为断言依据"，只作为观察项，不作为通过 / 失败判据。

## 22 项目录

1. Windows `run.bat` 启动 → 首页 200
2. macOS `mac-启动服务.command` 启动 → 首页 200
3. 断网后 `run.bat` / `python main.py` 直启（离线启动）
4. 首页导航：iframe 切换到 12 个目标全部可打开
5. iframe `data-src` 懒加载语义生效（首次点击才加载）
6. 主题切换：`studio-theme` 消息父发子收，各页样式同步
7. i18n 切换：`studio-lang` / `studio-lang-change` 消息生效
8. UI 缩放：`studio-ui-scale` / `studio-ui-scale-pause` 语义
9. 画布打开保存：`canvas.html?id=&project=` 打开、编辑、`base_updated_at` 上行、`Saved` 状态回显
10. 保存冲突：两标签同时编辑同一画布 → 409 → `data.detail?.canvas || data.canvas` 双 shape 消费 → 合并回滚
11. 多标签同步：`canvas_updated` 推送 → 另一 tab 更新；`client_id === CLIENT_ID` 自我识别跳过
12. 素材上传：本地图 → `/api/upload*` → 素材库预览可见；旁车 `.txt` 保留
13. 素材 inbox：智能画布"发送到素材库" → `smart_canvas_asset_inbox` localStorage 通道
14. Provider 保存广播：`BroadcastChannel('studio-api').providers-changed` → 五页面订阅 refetch
15. 任务提交：`POST /api/canvas-image-tasks` → 查询链路可用（`pendingTasks` 前端 shape）
16. CLI status：Jimeng / Codex / Gemini `/api/*/status` 面板可见
17. ComfyUI 工作流：`/api/comfyui/instances` 列出、执行、`prompt_id` 恢复
18. RunningHub：查询类接口可用
19. History：`/api/history` 分页、5000 条上限、`/api/history/delete`
20. 旧 URL 探测：`/assets/output/xxx.png` / `/assets/input/xxx` / `/output/xxx` 直接访问可读
21. 旧 localStorage 兼容：29 项 legacy key 读写不破
22. 离线安装：`pip install --no-index --find-links=packages -r requirements.txt` 全绿

---

## 1. Windows `run.bat` 启动 → 首页 200

**关联 compat-contract 章节**：§3（`/ws/stats` 连接点）、§7（fetch URL 基线）
**关联后端烟测**：backend-smoke item 1（单进程启动）、item 3（首页）

**最小复现步骤**：
1. Windows 客户机上打开 `E:/projects/Infinite-Canvas/` 根目录。
2. 双击 `run.bat`（或 CMD 内执行 `run.bat`）。
3. 浏览器打开 `http://127.0.0.1:3000/`。
4. F12 → Network → Preserve log 勾选，刷新一次。

**期望结果**：
- 控制台无 traceback；uvicorn 打印 `Uvicorn running on http://0.0.0.0:3000`（引用 backend-smoke item 1）。
- 浏览器 `GET /` 返回 `200`（引用 backend-smoke item 3）。
- Network 面板中 `GET /ws/stats?client_id=…` WebSocket 连接建立成功；`client_id` 参数来源为 `localStorage.getItem('client_id')`（引用 compat-contract §3.1）。
- 无 500 / 404 关键请求（`/api/config`、`/static/index.html` 均为 200）。

**失败降级**：任一条不通过 → 回滚到 PR-0（`main` 未合入 PR-1 前状态）；本 PR 无代码改动，回滚等价于 `git revert`。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 2. macOS `mac-启动服务.command` 启动 → 首页 200

**关联 compat-contract 章节**：§3、§7
**关联后端烟测**：backend-smoke item 1、item 3

**最小复现步骤**：
1. macOS 客户机上打开 Finder，进入项目根目录。
2. 双击 `mac-启动服务.command`（首次运行需在"系统设置 → 隐私与安全性"允许执行）。
3. 浏览器打开 `http://127.0.0.1:3000/`。
4. F12 → Network → Preserve log 勾选，刷新一次。

**期望结果**：
- 终端无 traceback；uvicorn 打印 `Uvicorn running on http://0.0.0.0:3000`。
- `GET /` 返回 `200`。
- `GET /ws/stats?client_id=…` WebSocket 建立成功（引用 compat-contract §3.1）。

**失败降级**：回滚到 PR-0。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 3. 断网后 `run.bat` / `python main.py` 直启（离线启动）

**关联 compat-contract 章节**：§7（fetch URL 基线）
**关联后端烟测**：backend-smoke item 1、item 13（离线安装）

**最小复现步骤**：
1. 客户机断网（关闭 Wi-Fi / 拔网线）。
2. 执行 `run.bat`（Windows）或 `python main.py`（跨平台）。
3. 浏览器打开 `http://127.0.0.1:3000/`。
4. 手动点击左侧导航切换到 `canvas-list` / `api-settings` / `asset-manager` 三个 iframe。

**期望结果**：
- 后端进程正常启动，不因外网不通报错。
- `GET /` 返回 `200`。
- 三个 iframe 页面均可加载；`/api/config`、`/api/providers`、`/api/canvases` 均 `200`（引用 compat-contract §7.1、§7.3、§7.4）。
- 前端不请求任何外网 CDN（Network 面板中无红色 DNS 失败项）。

**失败降级**：若因外网依赖失败 → 回滚到 PR-0；同时把外网依赖点回填到 compat-contract §14。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 4. 首页导航：iframe 切换到 12 个目标全部可打开

**关联 compat-contract 章节**：§1.1（iframe 消息发送位置在 `static/index.html:1906` 等）、§5（URL 参数 `id` / `project`）、§6（`switchUI` 全局函数）、§8.1（`index.html` 唯一 handler 含 `switchUI`）

**最小复现步骤**：
1. 打开 `http://127.0.0.1:3000/`。
2. 依次点击左侧导航项，切换 iframe 到以下 12 个目标（顺序引用任务书原文）：
   `canvas` / `smart-canvas` / `canvas-list` / `api-settings` / `comfyui-settings` / `asset-manager` / `gpt-chat` / `enhance` / `klein` / `angle` / `zimage` / `online`。
3. F12 → Elements → 查看 `<iframe>` 的 `src` 属性变更；Network 面板确认对应 HTML 加载。

**期望结果**：
- 12 个目标全部可切换，`.active` 高亮切换正常（引用 [[前端组件化治理方案#烟测清单]] 第 5 项）。
- 切换到 `canvas` 时 iframe 收到 `canvas-focus` 消息（type = `canvas-focus`，见 compat-contract §1.1 `static/index.html:1906`；消费点 `static/js/canvas.js:222`）。
- 全局函数 `switchUI` 生效（compat-contract §6 定义位置 `static/index.html:1882`；unique handler 集合位于 §8.1 `index.html`）。
- 切换后 URL hash / iframe.src 保留 `id`、`project` 两个可选查询字段（compat-contract §5 冻结要点：**参数名 `id` / `project` 不变**）。

**失败降级**：若某个 iframe 无法打开或 `switchUI` 报错 → 回滚到 PR-0；把该 iframe target id 回填到 compat-contract §1 / §5 / §6。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 5. iframe `data-src` 懒加载语义生效（首次点击才加载）

**关联 compat-contract 章节**：§5（URL 参数）、§8.1（`index.html` `switchUI` handler）

**最小复现步骤**：
1. 打开 `http://127.0.0.1:3000/`，**不点击任何导航**。
2. F12 → Elements 面板检查所有 `<iframe>` 标签：确认它们只有 `data-src` 属性，`src` 为空 / `about:blank`（仅默认激活项例外）。
3. Network 面板清空。
4. 点击 `smart-canvas` 导航项。
5. 观察 Network：`smart-canvas.html` 首次请求应发生**在点击之后**，而不是首页加载时。

**期望结果**：
- 初始态未点击的 iframe 无网络请求（`data-src` 保留、`src` 未激活）。
- 首次点击时才发起 iframe HTML 请求；请求路径与 `data-src` 一致，携带 `id` / `project` 查询串（引用 compat-contract §5：`smart-canvas.html` 的 `id` / `project` 可选，默认 `''`）。
- 已激活的 iframe 再次点击不再重复请求（浏览器缓存或 `src` 保留）。

**失败降级**：若懒加载失效导致首屏并发拉起 10+ iframe → 回滚到 PR-0；把 iframe 属性劣化点登记 compat-contract §14。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 6. 主题切换：`studio-theme` 消息父发子收，各页样式同步

**关联 compat-contract 章节**：§1.1（父→子 `studio-theme`，发送位置 `static/index.html:1996`）、§1.2（消费点 `smart-canvas.js:17003`、`asset-manager.js:4762`、`theme.js:260-268`）、§1.3（`studio-theme-change` CustomEvent）、§4.1（`studio_theme` / `canvas_theme` localStorage key）

**最小复现步骤**：
1. 打开 `http://127.0.0.1:3000/`，切到 `canvas` iframe。
2. F12 → Console 挂监听：`window.addEventListener('message', e => console.log('[msg]', e.data));`
3. 点击顶栏"切换主题"按钮（`toggleTheme` handler，compat-contract §8.1 `index.html`）。
4. 依次切到 `smart-canvas` / `asset-manager` / `api-settings` / `gpt-chat` iframe，检查样式跟随。

**期望结果**：
- Console 日志出现 `{ type: 'studio-theme', theme: 'dark' | 'light' }`（compat-contract §1.1 payload 字段为 `type`, `theme`）。
- `localStorage.getItem('studio_theme')` 值为 `light` 或 `dark`（compat-contract §4.1：优先于 `canvas_theme`）。
- 主壳同源派发 `studio-theme-change` CustomEvent，`event.detail.theme` 与新主题一致（compat-contract §1.3 触发点 `static/js/theme.js:20`、`:240`）。
- 至少下列 4 个页面同步样式：`canvas` / `smart-canvas`（`smart-canvas.js:17003`）/ `asset-manager`（`asset-manager.js:4762`）/ `theme.js` 挂载页（`theme.js:260-268`）。

**失败降级**：若 `type` 字符串被改名 / payload 字段被增删 → 违反 compat-contract §1.4 冻结要点，立即回滚到 PR-0，并把违规点登记 §14。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 7. i18n 切换：`studio-lang` / `studio-lang-change` 消息生效

**关联 compat-contract 章节**：§1.1（父→子 `studio-lang`，发送位置 `static/index.html:2071`、`:2078`，payload 字段 `type`, `lang`）、§1.2（消费点 `canvas.js`、`enhance.html:456-457`、`gpt-chat.html:620-622`、`angle.html:791`）、§1.3（`studio-lang-change` CustomEvent，触发点 `static/js/i18n-core.js:51`，11 个监听点）

**最小复现步骤**：
1. 打开 `http://127.0.0.1:3000/`。
2. F12 → Console 挂监听：`window.addEventListener('message', e => e.data?.type?.startsWith('studio-lang') && console.log('[lang]', e.data));`
3. 点击顶栏"切换语言"按钮（`toggleLanguage` handler，compat-contract §8.1 `index.html`）。
4. 切换到 `enhance` / `gpt-chat` / `angle` / `klein` / `online` / `zimage` 六个页面，检查文案。

**期望结果**：
- Console 日志出现 `{ type: 'studio-lang', lang: 'zh' | 'en' }`（compat-contract §1.1）。
- 同源派发 `studio-lang-change` CustomEvent，`event.detail.lang` 与新语言一致（compat-contract §1.3）。
- 中文提示文案字面**不变**（U8 `未登录` / U9 `已保存` / `删除失败` **未定位到，暂不作为断言依据**；引用 compat-contract §14）。
- 已定位的中文文案示例（compat-contract §12）：`保存失败`（`canvas.js:1609`）、`重命名失败`（`canvas.js:1995`）、`请求失败`（`canvas.js:794`）、`请先打开画布`（`smart-canvas.js:809`）；切换语言前后**这批字面不能被"顺手规范化"**。

**失败降级**：若消息 type 被改名或中文 detail 被替换 → 违反 compat-contract §1.4、§12.1；回滚到 PR-0，登记 §14。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 8. UI 缩放：`studio-ui-scale` / `studio-ui-scale-pause` 语义

**关联 compat-contract 章节**：§1.1（父→子 `studio-ui-scale` payload `type`, `mode`, `scale`，位置 `static/index.html:2007`；`studio-ui-scale-pause` payload `type`, `duration`，位置 `static/index.html:2014`）、§1.3（`studio-ui-scale-change` CustomEvent，触发点 `theme.js:188`、`:206`；监听点 `index.html:2088`、`canvas.js:235`）、§4.1（`studio_ui_scale_mode` localStorage key）

**最小复现步骤**：
1. 打开 `http://127.0.0.1:3000/`，切到 `canvas` iframe。
2. F12 → Console 挂监听：`window.addEventListener('message', e => e.data?.type?.startsWith('studio-ui-scale') && console.log('[scale]', e.data));`
3. 触发缩放：`setScaleMode` / 页面缩放按钮 → 观察消息。
4. 触发暂停：某个"暂停自动缩放"按钮或代码路径（`static/js/theme.js:195` 附近）。

**期望结果**：
- Console 收到 `{ type: 'studio-ui-scale', mode: 'auto' | '<数字>', scale: <number> }`（compat-contract §1.1）。
- Console 收到 `{ type: 'studio-ui-scale-pause', duration: <number ms> }`（compat-contract §1.1）。
- 同源 CustomEvent `studio-ui-scale-change`：`event.detail.mode` / `event.detail.scale` 字段名不变（compat-contract §1.3）。
- `localStorage.getItem('studio_ui_scale_mode')` 值为 `auto` 或百分比数字（compat-contract §4.1 备注）。

**失败降级**：字段名或 payload 结构被改 → 违反 §1.4；回滚到 PR-0。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 9. 画布打开保存：`canvas.html?id=&project=` 打开、编辑、`base_updated_at` 上行、`Saved` 状态回显

**关联 compat-contract 章节**：§5（`canvas.html` `id` 必填 / `project` 可选，`static/js/canvas.js:14789`）、§7.1（PUT `/api/canvases/${canvas.id}` body 含 `title`, `icon`, `nodes`, `connections`, `viewport`, `logs`, `client_id`, `base_updated_at`，位置 `static/js/canvas.js:1411`）、§11.2（`base_updated_at: Number(lastCanvasUpdatedAt || canvas.updated_at || 0)`，位置 `canvas.js:1421-1422`；智能画布 `smart-canvas.js:5826`）、§12（状态字面量 `Synced` / `Syncing...` / `Saved` / `Saving...` / `Save failed`，`static/js/canvas.js` 多处）、§13.1（`serializableCanvasNode` 剥离字段清单）
**关联后端烟测**：backend-smoke item 7（画布冲突 shape 双兼容）

**最小复现步骤**：
1. 打开 `http://127.0.0.1:3000/`，切到 `canvas-list` iframe。
2. 新建或选择一个画布，进入 `canvas.html?id=<CID>&project=<PID>`（引用 compat-contract §5：参数名 `id` / `project` 不变）。
3. 添加一个节点（点击"添加图片节点"，`addImageNode` handler，compat-contract §6、§8.1 `canvas.html`）。
4. 拖动节点位置；等待自动保存或点击手动保存。
5. F12 → Network → 找 `PUT /api/canvases/<CID>` 请求。
6. 刷新页面，重新打开同一画布。

**期望结果**：
- URL 携带 `id` / `project` 两个查询字段（compat-contract §5）。
- `PUT /api/canvases/${canvas.id}` 请求 body 包含全部 8 个字段：`title`, `icon`, `nodes`, `connections`, `viewport`, `logs`, `client_id`, `base_updated_at`（compat-contract §7.1 `canvas.js:1411`）。
- `client_id` 值来自 `CLIENT_ID` 常量（compat-contract §11.1：`canvas.js:473`：`const CLIENT_ID = 'canvas_' + Math.random().toString(36).slice(2);`）。
- `base_updated_at` 值为 `Number(lastCanvasUpdatedAt || canvas.updated_at || 0)`（compat-contract §11.2）。
- 保存成功后 UI 状态徽标字面量出现 `Saved`（compat-contract §12 中的 `setStatus` 英文状态）。
- 落盘 payload 中**不含**临时字段 `_ltxEditor` / `running` / `runStatus` / `runError` / `_cascadeIdx` / `_cascadeFailed` / `_activeLoopCtx`（compat-contract §13.1 剥离清单）。
- 刷新后画布内容与保存前一致（引用 [[前端组件化治理方案#烟测清单]] 第 9 项）。

**失败降级**：body 字段缺失 / 增名 / `base_updated_at` 字段被改名 → 违反 compat-contract §7.8、§11.6；回滚到 PR-0。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 10. 保存冲突：两标签同时编辑同一画布 → 409 → `data.detail?.canvas || data.canvas` 双 shape 消费 → 合并回滚

**关联 compat-contract 章节**：§10.1（经典画布 `canvas.js:1425-1434`：优先读 `data.detail.canvas`；其次 `data.canvas`；时间戳 `data.detail.updated_at` → `data.updated_at` → `remote?.updated_at`）、§10.2（智能画布 `smart-canvas.js:5833-5849`：只读 `data.detail.canvas`；缺失时同步 `data.detail.updated_at`；走 `applyMergedServerCanvas` + 300ms `setTimeout(saveCanvas, 300)`）、§10.3（双兼容读冻结要点）、§11.2、§12（409 注释）
**关联后端烟测**：backend-smoke item 7（画布冲突 shape 双兼容）

**最小复现步骤**：
1. 打开两个浏览器 tab，均定位到同一画布 `canvas.html?id=<CID>&project=<PID>`。
2. Tab A 编辑节点，等自动保存或手动保存；等 `Saved` 出现。
3. Tab B **不刷新**，直接编辑另一个节点，触发保存。
4. F12 → Network → 找 Tab B 的 `PUT /api/canvases/<CID>` 响应。

**期望结果**：
- Tab A 保存成功（HTTP `200`）。
- Tab B 保存返回 HTTP `409`；响应 JSON 具备下列任一 shape（前端必须双兼容读，compat-contract §10.3）：
  - `data.detail.canvas`（完整 canvas 快照）
  - `data.canvas`（顶层快照）
- 时间戳字段读取顺序：`data.detail.updated_at` → `data.updated_at` → `remote?.updated_at` 兜底（compat-contract §10.1）。
- Tab B 前端行为（经典画布）：若 `localCanvasDirty || saveCanvasAgain` 为真 → 只更新 `lastCanvasUpdatedAt` 并设 `saveCanvasAgain = true` 重试；否则 `applyRemoteCanvasData(remote)`（compat-contract §10.1）。
- 智能画布对应场景：走 `applyMergedServerCanvas(serverCanvas)` → 节点 id 合并、图片取并集 → `setTimeout(saveCanvas, 300)`（compat-contract §10.2）。
- 中文 detail 注释文案：`冲突：别人先保存了。合并对方的状态（节点 id 合并、图片取并集，谁都不丢），然后用对方最新的 updated_at 作为基底重存，把合并结果落盘——而不是直接覆盖对方。`（compat-contract §12 智能画布 `:5834-5835`）**字面不变**。

**失败降级**：`data.detail.canvas` / `data.canvas` 双兼容读被拆单路 → 违反 compat-contract §10.3；回滚到 PR-0。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 11. 多标签同步：`canvas_updated` 推送 → 另一 tab 更新；`client_id === CLIENT_ID` 自我识别跳过

**关联 compat-contract 章节**：§3.1（`/ws/stats` 连接点 `static/index.html:1965`、`smart-canvas.js:5246`）、§3.2（`canvas_updated` shape：`type`, `client_id`, `canvas_id`, `updated_at`, `canvas`(optional)；消费 `canvas.js:2169`、`smart-canvas.js:5213`）、§11.1（`CLIENT_ID` 定义 `canvas.js:473`；智能画布 `smartClientId`）、§11.3（下行自我识别：经典 `data.client_id === CLIENT_ID` → return；智能 `data.client_id === smartClientId` → return + `canvasSyncInFlight` → return + `remoteUpdatedAt <= canvas?.updated_at` → return）
**关联后端烟测**：backend-smoke item 12（WebSocket 消息类型）

**最小复现步骤**：
1. 打开两个 tab，均定位到同一画布。
2. F12 → Console 挂监听（**两个 tab 都要**）：
   ```
   const CID = (window.CLIENT_ID || window.smartClientId);
   console.log('CID', CID);
   ```
3. Tab A 编辑节点，保存。
4. 观察 Tab B 的 WebSocket `/ws/stats` 收到消息 & 画布是否更新。
5. 观察 Tab A 的 WebSocket 也会收到自己发的消息 → 应被自我识别跳过。

**期望结果**：
- Tab A 的 `/ws/stats?client_id=…` WebSocket 收到 `{ type: 'canvas_updated', client_id: <A's CLIENT_ID>, canvas_id: '<CID>', updated_at: <ts>, canvas?: {...} }`（compat-contract §3.2）。
- Tab A 内 `handleCanvasUpdatedMessage(data)` 因 `data.client_id === CLIENT_ID` **直接 return**（compat-contract §11.3 经典画布 `canvas.js:2169-2174`）。
- Tab B 的 `/ws/stats` 收到相同消息；因 `data.client_id !== CLIENT_ID` **继续处理**，画布状态更新，`lastCanvasUpdatedAt` 前进（compat-contract §11.3）。
- 智能画布额外条件：`canvasSyncInFlight` 期间 return（保存中不重复合并）；`remoteUpdatedAt <= canvas?.updated_at` → return（compat-contract §11.3 `smart-canvas.js:5213-5219`）。
- `CLIENT_ID` 每次刷新都会新生成（compat-contract §11.1：`'canvas_' + Math.random().toString(36).slice(2)`；跨 Tab 不共享）。

**失败降级**：`client_id === CLIENT_ID` 自我过滤被破坏（消息回环） → 违反 compat-contract §11.6；回滚到 PR-0。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 12. 素材上传：本地图 → `/api/upload*` → 素材库预览可见；旁车 `.txt` 保留

**关联 compat-contract 章节**：§7.1（`/api/ai/upload` POST multipart，`canvas.js:2005`、`:4228`、`:4255`；`/api/local-assets/upload` POST multipart，`canvas.js:3677`、`:3718`）、§7.2（`/api/ai/upload` POST，`smart-canvas.js:396`；`/api/local-assets/upload` POST，`smart-canvas.js:424`；`/api/upload` POST，`smart-canvas.js:14938`）、§7.5（`/api/upload` POST，`comfyui-settings.js:1181`）、§7.6（`/api/asset-library/items` POST multipart，`asset-manager.js:204`）、§7.8（所有 form-data 上传点保留 multipart 语义）、§4.4（`asset_manager_local_caption_settings_v1` localStorage key）
**关联后端烟测**：backend-smoke item 4（静态与产物挂载）

**最小复现步骤**：
1. 打开 `asset-manager` iframe。
2. 选择一张本地 PNG / JPG 图片上传（走"添加素材"入口）。
3. F12 → Network → 找 `POST /api/asset-library/items` 请求（Content-Type: `multipart/form-data`）。
4. 上传成功后在素材库列表中查看预览。
5. 如启用了本地 caption（`asset_manager_local_caption_settings_v1`），检查旁车 `.txt` 是否随图同步保存。

**期望结果**：
- 请求 URL：`/api/asset-library/items`（compat-contract §7.6 `asset-manager.js:204`）；method `POST`；Content-Type `multipart/form-data`。
- 响应 200，素材库列表出现该图；预览可打开。
- multipart 语义保留：**禁止改为 JSON**（compat-contract §7.8 冻结要点）。
- 若走 canvas 页上传路径：`/api/ai/upload`（`canvas.js:2005`）或 `/api/local-assets/upload`（`canvas.js:3677`）均为 POST multipart。
- 旁车 `.txt` 若启用，读取 `asset_manager_local_caption_settings_v1` 决定行为（compat-contract §4.4）；本项若 caption 未启用，旁车检查记为 N/A。

**失败降级**：URL 被改 / multipart 被 JSON 化 → 违反 §7.8；回滚到 PR-0。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 13. 素材 inbox：智能画布"发送到素材库" → `smart_canvas_asset_inbox` localStorage 通道

**关联 compat-contract 章节**：§4.3（`smart_canvas_asset_inbox` localStorage，`smart-canvas.js:5992`、`:6023`）、§4.4（asset-manager 消费点 `asset-manager.js:2644`、`:2729`）、§4.5（"素材 inbox 跨页通道属**已知历史遗留**，M6/M7 页面迁移时才处理（保持双写）"）

**最小复现步骤**：
1. 打开 `smart-canvas` iframe，编辑一个画布并生成 / 添加图片节点。
2. 在节点上点击"发送到素材库"（或对应右键菜单）。
3. F12 → Application → Local Storage → 找 key `smart_canvas_asset_inbox`。
4. 切换到 `asset-manager` iframe，观察是否自动 pick up。

**期望结果**：
- `localStorage.getItem('smart_canvas_asset_inbox')` 存在，且为 JSON 字符串（compat-contract §4.3）。
- 写入方为 `smart-canvas.js:5992` / `:6023`；读取方为 `asset-manager.js:2644` / `:2729`（compat-contract §4.3 + §4.4 引用行号）。
- 素材库能拾取到最新入队素材（成功即通过；若 UI 上无明显提示，则以 localStorage 存在为准）。
- **key 名不改、shape 不改**（compat-contract §4.5：M6/M7 前保持双写）。

**失败降级**：key 被改名或结构变更 → 违反 §4.5；回滚到 PR-0。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 14. Provider 保存广播：`BroadcastChannel('studio-api').providers-changed` → 五页面订阅 refetch

**关联 compat-contract 章节**：§2.1（频道名 `'studio-api'`；payload `{ type: 'providers-changed'|'workflows-changed'|'comfy-instances-changed', updated_at?: number }`）、§2.2（发送点：`api-settings.js:333`、`:1380`、`:3825`）、§2.3（订阅点：`index.html:1925-1928`、`canvas.js:1493-1499`、`smart-canvas.js:16989-16996`、`gpt-chat.html:852-857`、`online.html:444-446`）、§2.4（不改频道名 `studio-api`、不改任何 type 字符串、`updated_at` 可选）、§6（`broadcastStudioApiChange` 全局函数，`api-settings.js:331`）、§7.3（`PUT /api/providers/${id}`，`api-settings.js:3087`）

**最小复现步骤**：
1. 打开 `http://127.0.0.1:3000/`，切到 `canvas` iframe（订阅点 `canvas.js:1493-1499`）。
2. F12 → Console 挂监听：
   ```
   const bc = new BroadcastChannel('studio-api');
   bc.onmessage = e => console.log('[BC]', e.data);
   ```
3. 切到 `api-settings` iframe，修改一个 Provider，点击"保存"。
4. 观察 Console 消息与各 iframe 是否刷新。

**期望结果**：
- BC 消息 `{ type: 'providers-changed', updated_at?: <number> }`（compat-contract §2.1；`updated_at` 仅 `api-settings.js:333` 会发，读端必须允许缺省，§2.4）。
- 至少下列 5 个订阅点触发刷新（compat-contract §2.3）：
  1. `index.html:1925-1928`（BC → iframe 桥）
  2. `canvas.js:1493-1499`（触发 `refreshCanvasConfigFromSettings()`）
  3. `smart-canvas.js:16989-16996`（触发 `refreshSmartConfigFromSettings()`）
  4. `gpt-chat.html:852-857`（刷新 provider 列表）
  5. `online.html:444-446`（触发 provider 刷新）
- 全局函数 `broadcastStudioApiChange` 由 `api-settings.js:331` 定义，`api-settings.js:1380`、`:1416`、`:3825` 使用（compat-contract §6）。
- **不改频道名 `studio-api`**、**不改任何 type 字符串**（compat-contract §2.4）。

**失败降级**：频道名 / type 被改 → 违反 §2.4；回滚到 PR-0。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 15. 任务提交：`POST /api/canvas-image-tasks` → 查询链路可用（`pendingTasks` 前端 shape）

**关联 compat-contract 章节**：§7.1（`/api/canvas-image-tasks` 相关请求出现在 canvas.js 其余 fetch 段，`static/js/canvas.js:12257` 附近；见 §7.1 段末说明"其他 canvas.js fetch（≥ 30 处，覆盖 …）"）、§7.2（smart-canvas.js 其余 fetch"覆盖 `/api/canvas-image-tasks` …"）、§11（`client_id`、`base_updated_at` 自我识别）、§13.2（`canvasForStorage` 深克隆 + 过滤 `SMART_LOG_PREVIEW_NODE_ID`）
**关联后端烟测**：backend-smoke item 8（Canvas 图片任务链路）

**最小复现步骤**：
1. 打开 `smart-canvas` iframe，选中一个 generator / image 类节点。
2. 提交一次生成（点击"运行"）。
3. F12 → Network → 找 `POST /api/canvas-image-tasks` 请求。
4. 观察响应 `task_id`；随后前端会轮询 `/api/canvas-image-tasks/<task_id>`。
5. Console 检查节点 `pendingTasks` 字段：`node.pendingTasks` 应为数组，每项含 `taskId`, `kind`, `providerId`, `model`。

**期望结果**：
- `POST /api/canvas-image-tasks` 响应包含 `task_id`（引用 backend-smoke item 8：第一步 202/200 与 `task_id`；第二步 `state` ∈ `queued|running|succeeded|failed|cancelled`）。
- 前端节点 `pendingTasks` shape 保留：`[{taskId, kind:'image', providerId, model}]`（**前端源码事实**，非 compat-contract 冻结项；本条以后端 `state` 状态机为准，前端字段名保留观察，登记为"补齐"候选）。
- 轮询请求走 `cascadeFetch(/api/canvas-image-tasks/${encodeURIComponent(taskId)})`（**前端源码事实**）。
- **说明**：compat-contract §14 未把 `pendingTasks` 字段名列为冻结项；本条以 backend-smoke item 8 状态机为断言主线，`pendingTasks` shape 仅作观察记录。

**失败降级**：URL / method 变化或后端状态机断裂 → 违反 compat-contract §7.8；回滚到 PR-0。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 16. CLI status：Jimeng / Codex / Gemini-CLI `/api/*/status` 面板可见

**关联 compat-contract 章节**：§7.3（前端 fetch URL 冻结表；见下方"compat-contract 待补齐"说明）
**关联后端烟测**：backend-smoke item 11（CLI Provider status）
**源码事实（grep 结果，PR-1 补齐）**：
- `static/js/api-settings.js:2654` → `fetch('/api/jimeng/status')`
- `static/js/api-settings.js:2773` → `fetch('/api/codex/status')`
- `static/js/api-settings.js:2824` → `fetch('/api/gemini-cli/status')`
- `main.py:12219` → `@app.get("/api/codex/status")`
- `main.py:12288` → `@app.get("/api/gemini-cli/status")`
- `main.py:12355` → `@app.get("/api/jimeng/status")`

**说明**：compat-contract §7.3 表格当前记录第三条路径 at `:2822` 与源码 grep（`/api/gemini-cli/status` at `:2824`）不一致，路径名与行号均有偏差——**属于前端 PR-0 冻结清单的一处笔误**（错记的路径名不存在于源码），已通知 Lead 待 compat-contract 修订。本条以源码 grep 为断言依据。任务书原文 "Jimeng / Codex / Gemini `/api/*/status`" 属示意，具体路径以三条源码事实为准。

**最小复现步骤**：
1. 打开 `api-settings` iframe。
2. 打开 Jimeng / Codex / Gemini-CLI 面板（对应按钮 handler：`refreshJimengCredit` / `refreshCodexStatus` / `refreshGeminiCliStatus`，compat-contract §8.1 `api-settings.html`）。
3. F12 → Network → 找三条 `GET /api/*/status` 请求。

**期望结果**：
- 前端发起的 URL（源码 grep 事实）：
  - `GET /api/jimeng/status`（`api-settings.js:2654`）
  - `GET /api/codex/status`（`api-settings.js:2773`）
  - `GET /api/gemini-cli/status`（`api-settings.js:2824`）
- 后端路由（源码 grep 事实）：`main.py:12219` `@app.get("/api/codex/status")`；`main.py:12288` `@app.get("/api/gemini-cli/status")`；`main.py:12355` `@app.get("/api/jimeng/status")`——**前后端路径 1:1 对齐**（gemini 用 `-cli` 后缀，jimeng / codex 不用）。
- 三个面板均可见；响应含 `installed` / `logged_in` 布尔字段（backend-smoke item 11 期望；注 backend-smoke item 11 文档字面用了 `/api/{jimeng,codex,gemini}-cli/status`，与源码 grep 的 `/api/jimeng/status`、`/api/codex/status`、`/api/gemini-cli/status` 不完全一致——**属于 backend-smoke 文档字面示意与源码事实的差异**，以源码 grep 为准）。

**失败降级**：URL 被改名 → 违反 compat-contract §7.8；回滚到 PR-0。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 17. ComfyUI 工作流：`/api/comfyui/instances` 列出、执行、`prompt_id` 恢复

**关联 compat-contract 章节**：§7.5（工作流增删改查表；见下方"compat-contract 待补齐"说明）、§7.1（`/api/comfy/generate` POST body `prompt`, `workflow`, `images`, `node_id_overrides`, `instance_id`，`canvas.js:2522`）、§7.2（`/api/comfy/generate` 同 shape，`smart-canvas.js:2132`）
**关联后端烟测**：backend-smoke item 10（ComfyUI / RunningHub 查询类接口）
**源码事实（grep 结果，PR-1 补齐）**：
- `static/js/comfyui-settings.js:208` → `fetch('/api/comfyui/instances')`（GET）
- `static/js/comfyui-settings.js:241` → `fetch('/api/comfyui/instances', { method:'PUT', ... })`
- `main.py:17456` → `@app.get("/api/comfyui/instances")`
- `main.py:17460` → `@app.put("/api/comfyui/instances")`

**说明**：compat-contract §7.5 表格当前记录的 comfyui instances URL at `:305` / `:349` 与源码 grep（`/api/comfyui/instances` at `:208` / `:241`）不一致，路径少了 `ui` 且行号偏移——**属于前端 PR-0 冻结清单的一处笔误**（错记的字面量在源码中不存在），已通知 Lead 待 compat-contract 修订。本条以源码 grep 为断言依据；任务书原文 `/api/comfyui/instances` 与源码事实一致。

**最小复现步骤**：
1. 打开 `comfyui-settings` iframe。
2. 观察 `GET /api/comfyui/instances`（源码 `comfyui-settings.js:208`）— 列出实例。
3. 选择一个工作流：`selectWorkflow`（compat-contract §6 `comfyui-settings.js:291`）。
4. 保存工作流：触发 `onSave`（`comfyui-settings.js:1346`）→ `PUT /api/workflows/${id}` body `title`, `workflow`, `ui`（compat-contract §7.5 `:152`）。
5. 切到 `canvas` 或 `smart-canvas`，执行一个 comfy 节点。
6. 观察 `POST /api/comfy/generate` 请求 body 与响应 `prompt_id` 字段。

**期望结果**：
- `GET /api/comfyui/instances` 返回 200（源码事实 `comfyui-settings.js:208`）；实例保存走 `PUT /api/comfyui/instances`（源码事实 `comfyui-settings.js:241`）；前后端 1:1 对齐（`main.py:17456` / `:17460`）。
- 工作流列表 `GET /api/workflows`、保存 `PUT /api/workflows/${id}`、删除 `DELETE /api/workflows/${id}` 全部与 compat-contract §7.5 一致。
- 执行请求 `POST /api/comfy/generate` body 含 `prompt`, `workflow`, `images`, `node_id_overrides`, `instance_id`（compat-contract §7.1 `canvas.js:2522`、§7.2 `smart-canvas.js:2132`）。
- 进度 `/api/comfy/progress/${id}` 可查（§7.1 `canvas.js:2466`）；中断 `/api/comfy/interrupt` 可用（§7.1 `canvas.js:2498`）。
- `prompt_id` 恢复：从 `/api/comfy/history/${id}` GET 恢复（§7.5 `:240`）——**前端源码事实**，具体 field 名与 backend-smoke item 10 baseline 对齐。

**失败降级**：URL / body 字段被改 → 违反 §7.8；回滚到 PR-0。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 18. RunningHub：查询类接口可用

**关联 compat-contract 章节**：§7.3（`/api/runninghub/workflows/${entryId}` DELETE / GET / POST fetch，`api-settings.js:937`、`:1056`、`:1215`；`/api/runninghub/query?taskId=${taskId}` GET `:1725`；`/api/providers/${id}/rh-apps/fetch` POST `:3321`；`/api/providers/${id}/rh-workflows/fetch` POST `:3359`；`/api/providers/${id}/rh-workflows` PUT `:3459`）、§7.1（`/api/runninghub/generate` POST body `workflow_id`, `workflow_config`, `inputs`, `assets`, `provider_id`，`canvas.js:2330`）、§7.2（`/api/runninghub/generate` 同 shape，`smart-canvas.js:1940`；`/api/runninghub/query?taskId=${taskId}` GET `smart-canvas.js:2737`）
**关联后端烟测**：backend-smoke item 10

**最小复现步骤**：
1. 打开 `api-settings` iframe，进入 RunningHub 面板。
2. 拉取工作流：触发 `fetchRhWorkflowEditor` handler（compat-contract §8.1 `api-settings.html`）→ `POST /api/providers/${id}/rh-workflows/fetch`（§7.3 `:3359`）。
3. 保存工作流：`saveRhWorkflowEditor` → `PUT /api/providers/${id}/rh-workflows`（§7.3 `:3459`）。
4. 切到 canvas，运行一个 rh-node：`POST /api/runninghub/generate`（§7.1 `canvas.js:2330`）。
5. 查询：`GET /api/runninghub/query?taskId=<T>`（§7.3 `:1725`）。

**期望结果**：
- 拉取 / 保存 / 生成 / 查询 全部与 compat-contract §7.3 / §7.1 URL 一致。
- 请求 body 字段名保持不变：`workflow_id`, `workflow_config`, `inputs`, `assets`, `provider_id`（§7.1）；`config`（§7.3 `:1384` PATCH）；`workflows`（§7.3 `:3459` PUT）。
- 查询接口返回 200；未配置账号可返回空 / 401 / 403，但**不得 500**（backend-smoke item 10 期望）。

**失败降级**：URL / body 字段被改 → 违反 §7.8；回滚到 PR-0。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 19. History：`/api/history` 分页、5000 条上限、`/api/history/delete`

**关联 compat-contract 章节**：§7 前置说明（"合计原生 `fetch(` ≥ 197 处"）；`/api/history` / `/api/history/delete` 实际由 `history-bulk-manager.js` 使用（§7.7 覆盖 `/api/canvases/batch-history` GET / DELETE / `/api/canvases/batch-history/tasks/${taskId}` DELETE / `/api/canvases/batch-history/tasks/${taskId}/retry` POST）。**说明**：任务书要求的 `/api/history` / `/api/history/delete` 在 compat-contract §7 中未直接冻结；源码 `history-bulk-manager.js:197` 使用 `POST /api/history/delete`（可交叉验证：本 PR 引用 compat-contract §14 U9 附近登记为"待补"）。
**关联后端烟测**：backend-smoke item 9（历史分页 5000 上限，`/api/history?limit=6000` → `items.length <= 5000`）

**最小复现步骤**：
1. 打开 `canvas-list` 或 canvas 页历史面板（触发 `history-bulk-manager` 加载）。
2. F12 → Network 观察 `GET /api/history?limit=…`（后端 baseline，backend-smoke item 9）；或 `/api/canvases/batch-history` GET（前端源码事实，compat-contract §7.7 `history-bulk-manager.js:12`）。
3. 选择若干条 → 批量删除，观察 `POST /api/history/delete`（`history-bulk-manager.js:197`）或 `DELETE /api/canvases/batch-history`（§7.7 `:33`）。

**期望结果**：
- `GET /api/history?limit=6000` 返回 `items.length <= 5000`（引用 backend-smoke item 9）。
- 前端删除路径 URL：`POST /api/history/delete` body `{timestamp}`（`history-bulk-manager.js:197`，源码事实；compat-contract 未冻结，登记为"待补"到"清单差异登记"）。
- 单条重试 / 删除：`POST /api/canvases/batch-history/tasks/${taskId}/retry`、`DELETE /api/canvases/batch-history/tasks/${taskId}`（compat-contract §7.7 `:52`、`:74`）。
- 无 500。

**失败降级**：5000 上限失效 → 违反 backend-smoke item 9；回滚到 PR-BE-01 前状态或修复。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 20. 旧 URL 探测：`/assets/output/xxx.png` / `/assets/input/xxx` / `/output/xxx` 直接访问可读

**关联 compat-contract 章节**：§7 前置（所有 fetch URL 冻结要点：§7.8 "URL 字符串一律锁定"）；旧 URL `/assets/…` / `/output/…` 属**历史记录内嵌 URL 场景**——compat-contract 未把这三条根路径列在 §7 表格中，但 [[前端组件化治理方案#烟测清单]] 第 20 项与 [[前端组件化治理实施计划与PR清单]] PR-1 已明确"旧 URL 探测 curl 返回 200"是保活项。若源清单缺失（相当于 U 系列未定位状态），本清单**同样标注"未定位到，暂不作为断言依据"**，仅以 backend-smoke item 4"静态与产物挂载"为期望值。
**关联后端烟测**：backend-smoke item 4（`/static/index.html` / `/assets/` / `/output/` 三条路径不为 500）

**最小复现步骤**：
1. 找一张历史生成图，拿到其 URL 或从历史记录中随机复制一条 `/assets/output/*.png` / `/assets/input/*` / `/output/*` 路径。
2. 执行 curl：
   ```
   curl -s -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:3000/assets/output/<file>.png'
   curl -s -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:3000/assets/input/<file>'
   curl -s -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:3000/output/<file>'
   ```
3. 打开 canvas 历史面板，点击一张历史图，观察 iframe / lightbox 加载。

**期望结果**：
- 三条 curl 均返回 `200`（引用 backend-smoke item 4：`assets:%{http_code}` / `output:%{http_code}` 均为 200，或与 baseline 相同的 403/404 目录列表禁止；**重点是不为 500**）。
- 历史记录内嵌 URL 可打开、缩略图可显示。
- 说明：前端 fetch URL 表（§7）未直接列出这三条根路径；本条以 backend-smoke item 4 为主断言，前端只做"能打开"的观察。

**失败降级**：任一根路径 500 或 404（当 baseline 为 200） → 违反 backend-smoke item 4；回滚到 PR-BE-01。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 21. 旧 localStorage 兼容：29 项 legacy key 读写不破

**关联 compat-contract 章节**：§4.1–§4.4（29 项 key 全表：`studio_theme` / `canvas_theme` / `studio_ui_scale_mode` / `client_id` / `studio_active_page` / `studio_update_source` / `studio_sidebar_pinned` / `studio_local_nav_collapsed` / `studio_sidebar_settings_collapsed` / `canvasListCurrentProjectId` / `canvasSortMode` / `canvas_custom_image_models` / `canvas_image_models_ordered` / `canvas_chat_models_ordered` / `canvas_quick_toolbar_collapsed` / `canvas_prompt_template_groups_v1` / `canvas_prompt_template_overrides` / `canvas_session_viewports_v1` (sessionStorage) / `smart_canvas_asset_inbox` / `smart_canvas_prompt_presets_v1` / `smart_canvas_prompt_template_groups_v1` / `smart_canvas_prompt_template_overrides_v1` / `smart_canvas_recent_run_settings_v1` / `asset_manager_local_caption_settings_v1` / `modelscope_api_token` / `angle_engine_mode` / `zimage_engine_mode` / `gpt_chat_browser_user` / `gpt_chat_settings_v1` / `gpt_chat_last_conversation_v1`）、§4.5（29 项：localStorage 28 + sessionStorage 1；"PR-3 不合并、不改名任何一个 key"）

**最小复现步骤**：
1. 使用一个"已有历史数据"的浏览器 profile 打开 `http://127.0.0.1:3000/`。
2. F12 → Application → Local Storage / Session Storage → 逐项对照 compat-contract §4.1–§4.4 检查 29 项 key 是否存在（存在即读；不存在的 key 由业务触发点写入，如首次切主题写 `studio_theme`）。
3. 触发一次覆盖：
   - 切换主题 → 观察 `studio_theme` 写入。
   - 打开 canvas-list → 观察 `canvasListCurrentProjectId` 写入 / 读出。
   - 智能画布提交生成 → 观察 `smart_canvas_recent_run_settings_v1` 写入。
   - 在智能画布触发"发送到素材库" → `smart_canvas_asset_inbox` 写入（并见第 13 项）。
4. 刷新页面，验证读侧回填。

**期望结果**：
- 29 项 key **key 名不改**、**shape 不改**（compat-contract §4.5 冻结要点）。
- sessionStorage `canvas_session_viewports_v1` 单独作为 session-scoped 视口缓存（compat-contract §4.2 `canvas.js:507`、`:535`、`:561`）——刷新后可清空，切页面内不丢。
- 主题双 key 优先级：`studio_theme` > `canvas_theme`（compat-contract §4.1 备注）。
- `client_id` key 首次访问自动生成随机 id 并落盘（compat-contract §3.1 描述）。

**失败降级**：任一 key 被改名 / shape 变更 → 违反 §4.5；回滚到 PR-0。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 22. 离线安装：`pip install --no-index --find-links=packages -r requirements.txt` 全绿

**关联 compat-contract 章节**：§7 前置（所有 URL / method 冻结，间接要求依赖不引入新外网源）
**关联后端烟测**：backend-smoke item 13（离线安装）

**最小复现步骤**：
1. 在客户机上创建一个干净的 Python venv（`python -m venv .venv`）。
2. 激活 venv。
3. 断网。
4. 在项目根目录执行：
   ```
   pip install --no-index --find-links=packages -r requirements.txt
   ```
5. 观察 exit code。

**期望结果**：
- exit code `0`（引用 backend-smoke item 13）。
- 输出中**无** `Could not find a version that satisfies the requirement`。
- `packages/` 目录已提供 requirements.txt 中全部依赖的 wheel（backend-smoke item 13）。

**失败降级**：任一包缺失 → 违反 backend-smoke item 13；回滚到 PR-BE-01 前状态并补齐 `packages/`。

**执行记录模板**：`[ ] 通过 / [ ] 失败 备注：____`

---

## 清单差异登记

### A. 与 backend-smoke 14 项的交集与前端专属项

| 前端项 | 前端标题 | 后端交集（backend-smoke item）| 交集内容 | 前端专属点 |
|---|---|---|---|---|
| 1 | Windows `run.bat` 启动 | item 1（单进程启动）、item 3（首页 200） | `python main.py` 侧启动 & `GET /` 200 | Windows 入口脚本 `run.bat` 双击行为；WebSocket `/ws/stats?client_id=…` 连接（compat-contract §3.1） |
| 2 | macOS `mac-启动服务.command` | item 1、item 3 | 同上 | macOS 入口 `.command` 双击 + Gatekeeper 授权 |
| 3 | 离线启动 | item 1、item 13（离线安装间接相关） | 后端能起 | 前端 iframe 不请求外网 CDN；`/api/config` / `/api/providers` 均本机 200 |
| 4 | 首页导航 iframe 切换 12 项 | — | — | `switchUI` handler、`canvas-focus` iframe 消息、URL 参数 `id`/`project`（compat-contract §1.1、§5、§6、§8.1） |
| 5 | iframe `data-src` 懒加载 | — | — | 首屏不并发拉 iframe；点击后才请求 |
| 6 | 主题切换 `studio-theme` | — | — | iframe message + CustomEvent + `studio_theme` key（§1.1、§1.3、§4.1） |
| 7 | i18n 切换 `studio-lang` | — | — | iframe message + `studio-lang-change` CustomEvent（§1.1、§1.3） |
| 8 | UI 缩放 | — | — | `studio-ui-scale` / `studio-ui-scale-pause` payload；`studio_ui_scale_mode` key |
| 9 | 画布打开保存 | item 7（画布冲突 shape 双兼容，间接） | `PUT /api/canvases/${id}` body 与 `base_updated_at` | `Saved` UI 状态字面、`serializableCanvasNode` 剥离字段清单（§13.1） |
| 10 | 保存冲突 409 双 shape | item 7 | 409 响应必须双 shape | 前端消费路径 `data.detail?.canvas || data.canvas`；智能画布 `applyMergedServerCanvas` + 300ms 重存（§10） |
| 11 | 多标签同步 `canvas_updated` | item 12（WebSocket 消息类型） | WS `stats` / `canvas_updated` / `asset_library_updated` / `new_image` / `pong` 五类 shape | `client_id === CLIENT_ID` 自我识别；`CLIENT_ID` 每次刷新生成（§11） |
| 12 | 素材上传 | item 4（静态与产物挂载） | `/assets/` / `/output/` 挂载 | multipart 上传路径 `/api/asset-library/items` / `/api/ai/upload` / `/api/local-assets/upload` / `/api/upload`（§7.1、§7.2、§7.5、§7.6） |
| 13 | 素材 inbox | — | — | localStorage `smart_canvas_asset_inbox`（§4.3、§4.5） |
| 14 | Provider 广播 | — | — | `BroadcastChannel('studio-api')` 频道名 / type / 5 订阅点（§2） |
| 15 | 任务提交 | item 8（Canvas 图片任务链路） | `POST /api/canvas-image-tasks` + 状态机 `queued\|running\|succeeded\|failed\|cancelled` | 前端 `pendingTasks` 数组 shape、`cascadeFetch` 轮询路径 |
| 16 | CLI status | item 11（CLI Provider status） | 三条 CLI status URL 200 + `installed` / `logged_in` 字段 | 源码事实：`/api/jimeng/status`（`api-settings.js:2654` / `main.py:12355`）、`/api/codex/status`（`api-settings.js:2773` / `main.py:12219`）、`/api/gemini-cli/status`（`api-settings.js:2824` / `main.py:12288`）；前后端 1:1 对齐；compat-contract §7.3 第三条路径名与行号有笔误（错记的字面量在源码中不存在），已登记待补 |
| 17 | ComfyUI 工作流 | item 10（ComfyUI / RunningHub 查询类接口） | `/api/comfyui/instances` 200 | 源码事实：`comfyui-settings.js:208` / `:241` → `/api/comfyui/instances`；后端 `main.py:17456` / `:17460` → `/api/comfyui/instances`；任务书与源码事实一致；compat-contract §7.5 `:305` / `:349` 处 URL 字面量与行号有笔误（错记的字面量在源码中不存在），已登记待补 |
| 18 | RunningHub | item 10 | `/api/runninghub/workflows` 200 | `/api/runninghub/generate` body 全字段、`/api/runninghub/query?taskId=` |
| 19 | History 分页 5000 | item 9（历史分页 5000 上限） | `GET /api/history?limit=6000` items <= 5000 | 前端删除 URL `POST /api/history/delete` body `{timestamp}`（源码事实，compat-contract 未冻结）；`/api/canvases/batch-history/*`（§7.7） |
| 20 | 旧 URL 探测 | item 4 | `/assets/` / `/output/` 不为 500 | 历史记录内嵌 URL 从画布 lightbox / 缩略图打开 |
| 21 | 旧 localStorage | — | — | 29 项 key 全表；sessionStorage 1 项（§4） |
| 22 | 离线安装 | item 13 | `pip install --no-index --find-links=packages` exit 0 | — |

### B. backend-smoke 未被 22 项覆盖的后端专属项

| 后端 item | 内容 | 前端为何不覆盖 |
|---|---|---|
| 2 | 双 worker 启动一致性 `uvicorn --workers 2` | 文件对象 PR-0 强验收项；前端 UI 不感知 worker 数 |
| 5 | Provider 配置读端脱敏 `has_key` / `key_preview` / `key_env` | 属安全域，前端只读展示；由后端 baseline 保证 |
| 6 | Provider 配置写端不落明文日志 | 同 item 5，属日志与安全域 |
| 12 | WebSocket 主动 ping/pong shape | 前端第 11 项已消费 `canvas_updated`；`pong` 由 backend 兜底心跳 |
| 14 | `storage-settings` 多 worker 生效 | 文件对象 PR-0 关键验收；前端 asset-manager 只走 PATCH（`asset-manager.js:206`），不测多 worker 一致性 |

### C. 待协调差异（进入 [[2026-07-16 首批 PR 开工协调纲要#清单差异登记]]）

1. **CLI status URL — 未发现前后端差异**：前后端源码 grep 均为 `/api/jimeng/status`（`api-settings.js:2654` / `main.py:12355`）、`/api/codex/status`（`api-settings.js:2773` / `main.py:12219`）、`/api/gemini-cli/status`（`api-settings.js:2824` / `main.py:12288`）；任务书原文 "Jimeng / Codex / Gemini `/api/*/status`" 属示意，与源码事实一致。**compat-contract §7.3 待补齐**：表格第三条错记了一个源码不存在的路径名（行号 `:2822` 也偏差），需修订为 `/api/gemini-cli/status` at `:2824`（已通知 Lead）。backend-smoke item 11 字面用 `/api/{jimeng,codex,gemini}-cli/status`，与源码 grep 有出入（jimeng / codex 无 `-cli` 后缀），亦属文档字面示意。
2. **ComfyUI instances URL — 未发现前后端差异**：前后端源码 grep 均为 `/api/comfyui/instances`（`comfyui-settings.js:208` / `:241`；`main.py:17456` / `:17460`）；任务书与源码事实一致。**compat-contract §7.5 待补齐**：表格记录的 URL 字面量与行号 `:305` / `:349` 均与源码不符，需修订为 `/api/comfyui/instances` at `:208` / `:241`（已通知 Lead）。
3. **History URL**：任务书 `/api/history` / `/api/history/delete`；前端源码 `history-bulk-manager.js:11` 注释与 `:197` 使用 `POST /api/history/delete` body `{timestamp}`；同时源码存在 `/api/canvases/batch-history/*`（compat-contract §7.7）；compat-contract §7 未冻结 `/api/history*` 命名，需在下一个 PR 补齐冻结。

---

## 遗留风险与 U1–U10 覆盖影响

（U1–U10 见 compat-contract §14。）

| U 编号 | 项 | 影响的烟测项 | 处理 |
|---|---|---|---|
| U1 | `refresh-workflows` iframe type 未命中，由 BC `workflows-changed` 承载 | 第 14 项（Provider 广播） | 第 14 项以 §2 BC `workflows-changed` 为准；`refresh-workflows` 观察项，本清单不断言 |
| U2 | `studio:api-changed` iframe type 未命中 | 第 14 项 | 同上，观察项 |
| U3 | `storage-settings-changed` iframe type 未命中；`/api/storage-settings` PATCH 存在但无广播 | 第 12 项、第 14 项 | 第 12 项以 `POST /api/asset-library/items` 为主；PATCH `/api/storage-settings` 观察但不断言 |
| U4 | `loadWorkflows` 无独立全局函数 | 第 17 项 | 第 17 项以 `/api/workflows` GET / `comfyui-settings.js:40` 为准；`loadList`（`comfyui-settings.js:259`）为实际入口 |
| U5 | `revision` 字段前后端均未使用 | 第 9、10、11 项 | 三项以 `base_updated_at` + `updated_at` + `client_id` 为断言（§11） |
| U6 | `_pending` 临时字段无字面量 | 第 15 项 | 观察项，`pendingTasks` shape 源码存在但 compat-contract 未冻结 |
| U7 | `_renderPatchToken` 临时字段无字面量 | 无（本清单未直接触及）| 由 PR-6 引入时补 |
| U8 | 文案"未登录"未 grep 到 | 第 7 项 | 观察项，不作为 i18n 断言依据 |
| U9 | 文案"已保存" / "删除失败"未 grep 到（现状 `Saved` / `Save failed`） | 第 9 项 | 第 9 项以英文 `Saved` 为准（§12） |
| U10 | `event.origin` 白名单不存在 | 第 6、7、8 项 | 保留"同源接受"默认；不加白名单不视为回归 |

---

## 下一 PR（前端 PR-2 api-client seam）如何消费本清单

PR-2（`shared/api-client/legacy/endpoints.js` 骨架）应按下列方式引用本文与 compat-contract：

1. **保存冲突 shape（第 10 项）**：`shared/api-client/canvas.js` 抽 `CanvasConflictError` 时，必须保留双入口 `err.remote` / `err.updated_at`，读侧优先 `data.detail?.canvas`、次读 `data.canvas`（compat-contract §10.3 冻结要点）。**测试点**：第 10 项通过是 PR-2 合入的硬前提。
2. **多标签同步 `client_id` 自我识别（第 11 项）**：`shared/messaging` 的 bus（PR-3）在同一 Tab 内不能因结构重整而收到自己发的消息回环（compat-contract §11.6）。**测试点**：PR-2 内不动 bus，但 apiClient 保存路径中 `client_id: CLIENT_ID` 上行字段名不改（§7.1、§11.2）。
3. **Provider 广播（第 14 项）**：`shared/api-client/legacy/providers.js` 保存 Provider 后必须继续调用 `broadcastStudioApiChange`（compat-contract §6），BC 频道名 `'studio-api'` 与 type `'providers-changed'` / `'workflows-changed'` / `'comfy-instances-changed'` 三个字符串**必须硬编码为常量并 1:1 复用**（§2.4）。
4. **URL 常量化（覆盖第 9、12、14、15、16、17、18、19 项所有 fetch 点）**：`endpoints.js` 只做**常量提取**，禁止改路径、禁止改 method、禁止改 body 字段名（compat-contract §7.8）。
5. **CI 守护种子**：PR-7 落地"禁字段名"正则时，`_pending` / `_renderPatchToken`（compat-contract §13.4）加入预留名单；PR-6 引入后再剔除。
6. **每个 PR 的描述模板**：粘贴本清单执行结果表格，通过写 `[x] 通过 · 编号 N`，不涉及写 `编号 N 不涉及（原因：…）`，失败写 `[ ] 失败 · 编号 N · 备注：…`。

---

## 相关文档

- `docs/frontend-freeze/compat-contract.md`（前端 PR-0）
- `docs/backend-smoke/checklist.md`（后端 PR-BE-01）
- [[前端组件化治理方案]]
- [[前端组件化治理实施计划与PR清单]]
- [[前端现状架构地图]]
- [[2026-07-16 首批 PR 开工协调纲要]]

## 变更记录

- 2026-07-16：初版落地（前端 PR-1）。22 项全覆盖，每项至少一处 `compat-contract §X` 引用；镜像同步至 `E:\个人知识库\Infinite Canvas 二开与架构治理项目知识库\90 资料归档\前端保活烟测清单模板.md`。
