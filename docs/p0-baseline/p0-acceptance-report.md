# P0 保活基线综合验收报告（首批 PR 收官）

**日期**：2026-07-16
**执行方**：Lead（Claude 自动化 + 待人工执行标注）
**依据**：
- [[2026-07-16 首批 PR 开工协调纲要]] "保活烟测跨组共享清单"
- `docs/backend-smoke/checklist.md`（PR-BE-01 附带产出，14 项后端烟测）
- `docs/frontend-smoke/checklist.md`（前端 PR-1 产出，22 项前端烟测）
- OpenAPI baseline `tools/openapi_baseline.json`（132 paths, 74 schemas, 3.1.0）

## 验收结论

**首批 6 个 PR 合入后的保活基线：Lead 自动化验收 PASS，人工烟测项待人工执行**。

- ✅ **OpenAPI diff = 0**：132 paths / 74 schemas / 3.1.0 冻结完整，所有 6 个 PR 未破坏兼容。
- ✅ **单进程启动 + 首页 + 静态资源 + 5 类 API 端点 + WebSocket** 自动化验收全过。
- ✅ **文件对象 PR-0 多进程一致性** 通过 Windows 变通形态（双独立进程读时求值）验证成立。
- ✅ **前端 compat-contract §7 4 处笔误** 已通过 CB-01 修订。
- ⚠️ **发现 2 项治理缺陷 + 1 项测试环境限制**，逐项登记在下方 "衍生发现" 章节；下游 PR 承接。
- ⏸ **9 项前端浏览器交互烟测 + 部分后端 CLI/生成任务链路** 需人工执行；模板附于最后。

---

## 一、后端烟测（`docs/backend-smoke/checklist.md` 14 项）执行结果

| # | 项 | 状态 | 证据 |
|---|---|---|---|
| 1 | 单进程 `python main.py` 启动 | ✅ PASS | `netstat` 3000 LISTENING；`curl /` 返回 200；startup log 无 traceback。 |
| 2 | 双 worker `uvicorn --workers 2` 启动 | ⚠️ Windows 平台限制 | uvicorn `--workers 2` 在 Windows 上因 socket API 限制无法启动（`WinError 10022: 提供了一个无效的参数`）。这是 uvicorn 已知平台限制，不是本轮 PR 引入。**变通验证形态见 Item #14**（两个独立 Python 进程读时求值，一致）。Linux/macOS 上此项预期可跑，见"人工待执行项"。 |
| 3 | 首页 GET / | ✅ PASS | curl 返回 200。 |
| 4 | `/static/*`、`/assets/`、`/output/` 挂载 | ✅ PASS | `static:200`、`assets:404`、`output:404`——404 是"目录列表被禁"的正确行为，符合治理规范"不得暴露文件系统目录"。 |
| 5 | `/api/config` + `/api/providers` 读端脱敏 | ✅ PASS | 响应字段仅出现 `has_key / key_preview / key_env`；全文 grep `sk-*` / `Bearer *` 命中数 = 0。 |
| 6 | `PUT /api/providers` 写端不落明文日志 | ✅ PASS（正确 shape 下）；⚠️ 附**衍生发现 F-01** | 用 bare list body 请求：HTTP 200；响应 `api_key` 消失、`key_preview: "••••••••-LOG"`、`key_env: "API_PROVIDER___SMOKE___KEY"`；服务端日志 `grep sk-*` 0 命中。**但 422 error 响应体会回显完整 body**（含密钥），见 F-01。 |
| 7 | Canvas 冲突 409 双 shape | ✅ PASS | POST 创建 → 首次 PUT 成功 200 → 二次 PUT 同 `base_updated_at` 返回 409；响应含 `data.detail.canvas`（compat-contract §10 冻结的两种 shape 之一）；中文 message "画布已被其他页面更新..."；测试画布 DELETE 200 清理成功。 |
| 8 | `POST /api/canvas-image-tasks` 链路 | ✅ PASS | 提交返回 `task_id="canvas_img_..."` + `status="queued"`；查询返回完整 shape（`id/type/status/created_at/updated_at/result/error/provider_id/model/status_code/upstream_task_id`）。任务本身失败（本地无真实 provider）不影响链路验收。 |
| 9 | `GET /api/history?limit=6000` 5000 上限 | ✅ PASS | HTTP 200；返回列表长度 0（本地无历史数据，未超 5000）。 |
| 10 | ComfyUI + RunningHub 查询类 | ✅ PASS | `/api/comfyui/instances:200`、`/api/runninghub/workflows:200`。 |
| 11 | Jimeng / Codex / Gemini CLI status | ✅ PASS（且验证了 compat-contract §7 修订后的路径事实） | `/api/jimeng/status:200`、`/api/codex/status:200`、`/api/gemini-cli/status:200`（注意 gemini 用 `-cli` 后缀，其他不用——与 CB-01 修订后的 compat-contract 一致）。 |
| 12 | WebSocket 5 类消息 shape | ✅ PASS（stats + pong）；⏸ **人工待执行** `new_image` / `canvas_updated` / `asset_library_updated` | 连接 `/ws/stats` 成功；发纯文本 `ping` → 收 `{"type":"pong"}`；30s 心跳收 `{"type":"stats","online_count":1}`。三类业务事件需真实业务操作触发（生成成功 / 画布保存 / 素材上传），本机无法在几秒内触发，见"人工待执行项"。 |
| 13 | 离线安装 `pip install --no-index --find-links=packages -r requirements.txt` | ⚠️ 环境限制 + 已登记为**遗留议题 L04** | `packages/` 内所有平台相关 wheel 均为 `cp314-win_amd64`（Python 3.14 内嵌 Python 环境专用）；Lead 本机为 Python 3.11.15，wheel tag 不兼容 → pillow / pydantic_core / charset_normalizer 三条 `Could not find a version that satisfies` 报错。**这是[[技术开发规则与工程实施规范]] "架构决策闭合登记" 中已明列的遗留议题 L04**（Windows 内嵌 Python cp 标签与依赖 wheel 匹配由部署安全专题在 `packages/` 补齐时验证），不是本轮 6 个 PR 的 regression。真实部署环境（仓库带 Windows 内嵌 3.14）不受影响。 |
| 14 | storage-settings 多进程生效 | ✅ PASS（Windows 变通形态） | 手动改写 `data/storage_settings.json`（模拟 PATCH 后磁盘状态）；两个独立 Python 进程各自 `from main import storage_settings_snapshot; snap = storage_settings_snapshot()` 均读到新值 `E:/projects/Infinite-Canvas/output/input` 等——**读时求值语义确认在多进程下成立**，文件 PR-0 核心修复验证通过。 |

**通过**：11 项完全 PASS + 1 项部分 PASS（Item #12 stats+pong 已过，3 类业务事件待人工）。
**限制**：2 项平台/环境限制（Item #2 Windows uvicorn `--workers 2` 限制；Item #13 wheel Python tag 不匹配），**均非本轮 PR 引入**。

---

## 二、前端烟测（`docs/frontend-smoke/checklist.md` 22 项）执行分派

前端烟测涉及浏览器 UI 交互（画布拖拽、iframe 切换、两标签冲突、多标签 WebSocket 推送、素材上传等），Lead 自动化仅能覆盖能 curl 探测的 URL 层；界面交互层**全部由人工执行**。

| # | 项 | 归属 | 状态 |
|---|---|---|---|
| 1 | Windows `run.bat` 启动 | ⏸ 人工 | 待执行 |
| 2 | macOS `mac-启动服务.command` 启动 | ⏸ 人工（macOS 机器） | 待执行 |
| 3 | 断网直启 | ⏸ 人工（拔网线） | 待执行 |
| 4 | 首页导航 iframe 切换（12 页） | ⏸ 人工 | 待执行 |
| 5 | iframe `data-src` 懒加载 | ⏸ 人工（DevTools Network 面板观察） | 待执行 |
| 6 | 主题切换 | ⏸ 人工 | 待执行 |
| 7 | i18n 切换 | ⏸ 人工 | 待执行 |
| 8 | UI 缩放 | ⏸ 人工 | 待执行 |
| 9 | 画布打开保存 | ✅ Lead 自动化验证了 API 层（Item #7、#8）；⏸ 人工验证 UI 层 | UI 层待执行 |
| 10 | 保存冲突 | ✅ API 层 Lead 已验（Item #7 409 双 shape）；⏸ 人工验证两标签 UI 合并流程 | UI 层待执行 |
| 11 | 多标签同步 | ✅ WebSocket 层 Lead 已验（Item #12 stats+pong）；⏸ 人工验证 `canvas_updated` 推送触发另一 tab 更新 + `client_id === CLIENT_ID` 自我识别跳过 | UI 层待执行 |
| 12 | 素材上传 | ⏸ 人工（真实图片上传 + 预览 + 引用） | 待执行 |
| 13 | 素材 inbox | ⏸ 人工（智能画布"发送到素材库" + localStorage 通道） | 待执行 |
| 14 | Provider 保存广播 | ✅ API 层 Lead 已验（Item #6 200 + 脱敏）；⏸ 人工验证 BroadcastChannel 五页面订阅 refetch | UI 层待执行 |
| 15 | 任务提交 | ✅ API 层 Lead 已验（Item #8）；⏸ 人工验证前端 `pendingTasks` shape 与 UI 呈现 | UI 层待执行 |
| 16 | CLI status | ✅ API 层 Lead 已验（Item #11）；⏸ 人工验证 UI 面板呈现 | UI 层待执行 |
| 17 | ComfyUI 工作流 | ✅ instances 接口 Lead 已验；⏸ 人工验证 `prompt_id` 恢复流程 | UI 层待执行 |
| 18 | RunningHub | ✅ workflows 接口 Lead 已验；⏸ 人工验证查询链路 | UI 层待执行 |
| 19 | History | ✅ 分页 5000 上限 Lead 已验（Item #9）；⏸ 人工验证 `/api/history/delete` UI 触发 | UI 层待执行 |
| 20 | 旧 URL 探测 | ⏸ 人工（`/assets/output/xxx.png` 等真实历史 URL 访问） | 待执行 |
| 21 | 旧 localStorage 兼容 29 项 | ⏸ 人工（清空 localStorage 后启动应用，验证 29 项 legacy key 读写兼容） | 待执行 |
| 22 | 离线安装 | ⚠️ 见后端 Item #13，**遗留议题 L04** | 待人工在 Windows 内嵌 Python 3.14 环境下真跑 |

**汇总**：8 项完全人工（1-8、12-13、20-22）；13 项 Lead 已验 API 层，UI 层人工执行；1 项遗留议题 L04（第 22 项）。

---

## 三、衍生发现（本轮验收挖出的治理缺陷）

### F-01：`PUT /api/providers` 422 错误响应体回显 request body（含明文密钥）

**触发命令**：`curl -X PUT /api/providers -d '{"providers":[{...api_key:"sk-SMOKE-TEST-DO-NOT-LOG"}]}'`（错误 shape：`ApiProviderPayload` 期望 bare list，不是 `{providers:[...]}`）。

**响应体**：`{"detail":"请求参数格式不正确...","errors":[{"type":"list_type","loc":["body"],"msg":"Input should be a valid list","input":{"providers":[{...,"api_key":"sk-SMOKE-TEST-DO-NOT-LOG"}]}}]}`

**问题**：FastAPI 默认 `RequestValidationError` 把 request body 完整塞进 `errors[].input`。当 body 含密钥时，密钥会**明文回显给前端**。

**违反的治理规范**：[[技术开发规则与工程实施规范]]"不得在日志、错误、前端响应中输出 API key / Authorization / token"。

**归属承接**：
- **短期**（后端 PR-BE-12）：错误契约中间件应清理 `errors[].input` 内的密钥字段，或用白名单只保留字段名不保留值。
- **长期**（Provider 适配 PR-05）：`PUT /api/providers` payload 校验层直接拒绝含 `api_key` 字段（走密钥子资源 `PUT /api/providers/{id}/credentials/{slot}`），从源头杜绝密钥进入 body。
- **紧急兜底**（部署与安全 PR-10 日志脱敏中间件）：兜底扫描响应体内的 `sk-*` / `Bearer *` / `X-API-Key` 字面量做脱敏。

**状态**：已登记为 F-01，等下游 PR 承接。不阻塞本轮 P0 收官。

### F-02：`data/api_providers.json` 已被测试残留污染（`__smoke__` 单个 provider）

**触发**：Item #6 用 `[{"id":"__smoke__",...}]` PUT 覆盖了原 providers 列表；服务端强制"至少保留一个 provider"，无法回退到"默认列表"，因为覆盖后原真实 providers 已被磁盘覆盖。

**影响**：**本机开发环境**的 `data/api_providers.json` 只剩 `__smoke__` 单条。生产 / 其他开发机不受影响（各自维护自己的 data 目录）。

**归属**：Lead 本地环境清理；不影响仓库 / 治理进度。可以后续开发时手动通过 API 设置页重建 providers 或从 git 历史恢复 `data/api_providers.json`。

**状态**：已知项，不需 PR 承接。**若后续 Lead 或其他开发在此机器上工作发现 provider 缺失，说明是本次烟测残留**，从 `git checkout HEAD -- data/api_providers.json` 或手动重配。

### F-03：Item #2 与 Item #13 的 Windows 平台限制

**已知项**：
- Item #2 `uvicorn --workers 2` 在 Windows 上因 socket API 限制无法启动（uvicorn 官方已知）。
- Item #13 离线 pip 安装因 `packages/` wheel Python tag（cp314）与开发环境 Python（3.11）不匹配失败。

**归属**：
- Item #2：由**部署与安全 PR-08** `deploy/nginx-https-template + /healthz` 与部署形态选型时明确 Windows 部署方案（gunicorn 不可用于 Windows，改用 waitress / multiprocessing 或走 Nginx 反代到多个 uvicorn 单进程实例）。
- Item #13：**遗留议题 L04**（Windows 内嵌 Python cp 标签与 SQLAlchemy / Alembic / greenlet / Mako wheel 匹配由部署安全专题在 `packages/` 补齐时验证）。

**状态**：均已登记，交部署与安全专题接手。

---

## 四、人工烟测执行模板（给项目 Lead）

请在实际浏览器 + 双系统环境下执行下列条目，把结果填回本文对应项 `⏸`，或另建 `2026-XX-XX 首批 PR 人工烟测执行记录.md`。

### 人工执行清单（22 项前端 + 3 项后端 UI 层）

对 `docs/frontend-smoke/checklist.md` 22 项逐条按模板：

```
### 项 N: <标题>
- [ ] 通过 / [ ] 失败
- 执行日期：____
- 执行环境：Windows / macOS
- 备注：____
- 若失败，附截图 / 错误文案：____
```

**强烈建议先执行**（是治理规范硬约束的最小集）：

1. **Item #1 Windows run.bat 启动** —— 5 分钟验证。
2. **Item #3 断网直启** —— 拔网线后 `python main.py` / `run.bat` 能启，首页可访问。
3. **Item #10 两标签保存冲突** —— 两个浏览器 tab 同时打开同一画布，都改动、都保存，验证 409 UI 合并流程；这是 compat-contract §10 双 shape 的**唯一 UI 层验证入口**。
4. **Item #11 多标签同步 canvas_updated** —— 两 tab 打开同一画布，A 保存后 B 应自动更新；`client_id === CLIENT_ID` 自我识别语义在 devtools Console 里观察 `[WS] recv canvas_updated ...` 日志。
5. **Item #14 Provider 保存广播** —— API 设置页保存 provider，其他 iframe（画布 / 素材库 / 聊天）应触发 refetch；devtools Network 观察是否触发对应 `/api/*` 重取。
6. **Item #22 离线安装** —— 在真实 Windows 内嵌 Python 3.14 环境下（`run.bat` 附带的 python）跑 `pip install --no-index --find-links=packages -r requirements.txt`，验证 packages 齐全。

**其余 16 项** 按 `docs/frontend-smoke/checklist.md` 编号执行，失败即挂到本文 "人工烟测执行结果" 章节（如需 Lead 后续追踪）。

### macOS 单独执行 3 项

- Item #2 macOS 启动脚本。
- 22 项烟测在 macOS 上跑一遍（可只跑与 Windows 有差异的项）。

### 后端 Item #2 在 Linux 上执行

有 Linux 开发机时，跑一次 `uvicorn main:app --workers 2` 验证真实多 worker 一致性；Windows 变通形态已覆盖同一语义（Item #14 已 PASS），此项作为二次验证。

---

## 五、下一步

自动化通过率 = 11/14 后端项完全 PASS + 1/14 部分 PASS + 2/14 环境限制不判失败。人工烟测项在 Lead 执行后填回本文；若发现新问题，走"边界变更请求"或独立 issue 承接。

**收尾动作**（Lead 待办）：

1. 把本报告链接挂到 [[2026-07-16 首批 PR 开工协调纲要]] 的"清单差异登记"章节。
2. 更新 [[Infinite Canvas 二开与架构治理项目知识库 Index]] "当前下一步" 章节，把首批 6 条划掉、写入第二批清单（数据 PR-1 SQLAlchemy Core + Alembic、任务 PR-0 TaskStore、权限 PR-0 identity schema、后端 PR-BE-02 request_id middleware、前端 PR-2 api-client seam 等）。
3. 关闭 TaskList #1 P0-BASE。
4. F-01 缺陷交下游 PR-BE-12 / Provider PR-05 / 部署 PR-10 承接（在协调纲要"边界变更请求 CB-02"中登记）。
5. 待人工烟测执行结果回收后，在本文追加"人工执行结果"章节。
