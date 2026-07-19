# 后端保活烟测清单（PR-BE-01 落地版）

本清单实现自 [[2026-07-16 首批 PR 开工协调纲要]] "保活烟测跨组共享清单"。
每一项一行命令 / 一行期望，任一 PR 合入前须由 PR 作者跑完并把结果附在
知识库对应"完成状态"段落。

前置：`python main.py`（默认端口 3000）；除非另行说明，所有 `curl` 均在
另一终端执行；`--silent -o /dev/null -w '%{http_code}'` 用于取状态码。

## 1. 单进程启动

- 命令：`python main.py`
- 期望：控制台打印 `Uvicorn running on http://0.0.0.0:3000`，无 traceback；`curl -s http://127.0.0.1:3000/ -o /dev/null -w '%{http_code}\n'` 返回 `200`。

## 2. 双 worker 启动（多进程一致性）

- 命令：`uvicorn main:app --host 127.0.0.1 --port 3000 --workers 2`
- 期望：两次连续 `curl -s http://127.0.0.1:3000/api/config` 输出 JSON 一致（同 `providers` 顺序、同 `storage_settings.dirs`）。
- 归属：文件对象 PR-0 强验收项。

## 3. 首页

- 命令：`curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/`
- 期望：`200`。

## 4. 静态与产物挂载

- 命令：
  - `curl -s -o /dev/null -w 'static:%{http_code}\n' http://127.0.0.1:3000/static/index.html`
  - `curl -s -o /dev/null -w 'assets:%{http_code}\n' http://127.0.0.1:3000/assets/`
  - `curl -s -o /dev/null -w 'output:%{http_code}\n' http://127.0.0.1:3000/output/`
- 期望：三条均为 `200`（目录列出）或 `403/404`（禁列表）中与 baseline 相同的状态；重点是**不为 500**。

## 5. Provider 配置读端脱敏

- 命令：`curl -s http://127.0.0.1:3000/api/providers | python -c "import json,sys;d=json.load(sys.stdin);import re;s=json.dumps(d);assert 'api_key' not in s or all('key_preview' in p or 'has_key' in p or 'key_env' in p for p in d.get('providers',[]));print('ok')"`
- 期望：输出 `ok`；响应字段仅出现 `has_key` / `key_preview` / `key_env`，无明文 key。

## 6. Provider 配置写端不落明文日志

- 命令：`curl -s -X PUT http://127.0.0.1:3000/api/providers -H 'Content-Type: application/json' -d '{"providers":[{"id":"__smoke__","name":"smoke","type":"openai","api_key":"sk-SMOKE-TEST-DO-NOT-LOG"}]}'`
- 期望：服务端日志（stdout / uvicorn.access）中不出现字符串 `sk-SMOKE-TEST-DO-NOT-LOG`；响应体中该 provider 的 `api_key` 被脱敏为 `key_preview` / `has_key: true`。

## 7. 画布冲突 shape 双兼容

- 命令：`curl -s -o /tmp/canvas_1.json -w '%{http_code}\n' -X POST http://127.0.0.1:3000/api/canvases -H 'Content-Type: application/json' -d '{"title":"smoke"}'` 然后用同一 `base_updated_at` 连发两次 `PUT /api/canvases/{id}`。
- 期望：第二次 `PUT` 返回 `409`；响应 JSON 同时具备 `data.detail.canvas` 与 `data.canvas`（或 detail 中携带完整 canvas 快照），旧前端解析路径不 KeyError。

## 8. Canvas 图片任务链路

- 命令：`curl -s -X POST http://127.0.0.1:3000/api/canvas-image-tasks -H 'Content-Type: application/json' -d '{"canvas_id":"__smoke__","prompt":"noop","dry_run":true}'` 拿到 `task_id`，再 `curl -s http://127.0.0.1:3000/api/canvas-image-tasks/<task_id>`。
- 期望：第一步返回 `202/200` 与 `task_id`；第二步返回 `state` 字段（`queued|running|succeeded|failed|cancelled`）。

## 9. 历史分页 5000 上限

- 命令：`curl -s 'http://127.0.0.1:3000/api/history?limit=6000' | python -c "import json,sys;d=json.load(sys.stdin);assert len(d.get('items',[]))<=5000;print(len(d.get('items',[])))"`
- 期望：输出 `<= 5000`，无异常。

## 10. ComfyUI / RunningHub 查询类接口

- 命令：
  - `curl -s -o /dev/null -w 'comfyui_instances:%{http_code}\n' http://127.0.0.1:3000/api/comfyui/instances`
  - `curl -s -o /dev/null -w 'runninghub_workflows:%{http_code}\n' http://127.0.0.1:3000/api/runninghub/workflows`
- 期望：均 `200`（未配置账号可能返回空数组，但 HTTP 状态必须为 200 或与 baseline 一致的 401/403）。

## 11. CLI Provider status

- 命令：
  - `curl -s -o /dev/null -w 'jimeng:%{http_code}\n' http://127.0.0.1:3000/api/jimeng-cli/status`
  - `curl -s -o /dev/null -w 'codex:%{http_code}\n' http://127.0.0.1:3000/api/codex-cli/status`
  - `curl -s -o /dev/null -w 'gemini:%{http_code}\n' http://127.0.0.1:3000/api/gemini-cli/status`
- 期望：三条均为 `200`；响应含 `installed` / `logged_in` 布尔字段（未安装亦不得抛 500）。

## 12. WebSocket 消息类型

- 命令：`python -c "import asyncio,websockets,json;\
async def r():\
  async with websockets.connect('ws://127.0.0.1:3000/ws') as ws:\
    await ws.send(json.dumps({'type':'ping'}));\
    print((await ws.recv())[:120]);\
asyncio.run(r())"`
- 期望：至少收到一条 `{"type":"pong"}` 或 `{"type":"stats", ...}`；`stats` / `new_image` / `canvas_updated` / `asset_library_updated` / `pong` 五类消息 shape 不回退。

## 13. 离线安装

- 命令：`pip install --no-index --find-links=packages -r requirements.txt`
- 期望：exit code 0，无 `Could not find a version that satisfies the requirement`；`packages/` 已提供全部 wheel。

## 14. storage-settings 多 worker 生效

- 命令：先 `uvicorn main:app --workers 2`，再 `curl -s -X PATCH http://127.0.0.1:3000/api/storage-settings -H 'Content-Type: application/json' -d '{"dirs":{"upload":"output/input","generated":"output/output","local":"assets/local"}}'`，最后连续 6 次 `curl -s http://127.0.0.1:3000/api/storage-settings` 观察响应。
- 期望：`data/storage_settings.json` 磁盘内容与 PATCH 一致；6 次读取均返回同一 `dirs` shape；两 worker 均生效。归属：文件对象 PR-0 关键验收。

## 15. request_id middleware（PR-BE-02）

- 命令：
  - `curl -s -I http://127.0.0.1:3000/ | grep -i "^X-Request-Id:"`
  - `curl -s -I http://127.0.0.1:3000/ | grep -i "^X-Request-Id:"`（连续两次）
  - `curl -s -I -H "X-Request-Id: smoke-test-fixed-id" http://127.0.0.1:3000/ | grep -i "^X-Request-Id:"`
- 期望：前两次响应含 `X-Request-Id`，且两次值**不同**（uuid4 新生成）；第三次响应回显 `smoke-test-fixed-id`（客户端提供时复用）；服务端日志格式含 `[<request_id>]` 段。归属：PR-BE-02。

## 16. Settings / PathResolver 读时求值（PR-BE-03）

- 命令：
  - `python -c "from app.shared.settings import get_settings, PathResolver; import dataclasses; s=get_settings(); print('fields=', len(dataclasses.fields(type(s)))); r=PathResolver(); print(r.current_upload_dir(), r.current_generated_dir(), r.current_local_dir())"`
  - 手动改 `data/storage_settings.json` 的 `dirs.upload` 值，再新开 Python 进程重跑上一条命令。
- 期望：字段数 = **22**；三个路径 accessor 输出正确；改 `data/storage_settings.json` 后**新进程**读到新值（读时求值语义不破坏）；`main.py:302-388` 冻结区间无 diff。归属：PR-BE-03。

## 17. identity schema + bootstrap（权限 PR-0，编号原 BE-19）

- 命令：
  - `ls data/identity/*.json data/identity/audit_logs.jsonl`
  - `python -c "import json; [json.load(open(f'data/identity/{n}.json')) for n in ('users','user_aliases','workspaces','memberships','roles','role_permissions','resource_acl','auth_migration_state')]; print('ok')"`
  - `python -c "from app.identity import store, schema, request_context, legacy_mapper; print('ok')"`
  - `python tools/migrate_identity_bootstrap.py --dry-run && python tools/migrate_identity_bootstrap.py --apply && python tools/migrate_identity_bootstrap.py --apply`
- 期望：9 个文件全部存在（含 0 字节 `audit_logs.jsonl`）；JSON 加载全部合法；`app.identity` 四模块 import 成功；`--dry-run` 与两次 `--apply` 输出**完全一致**（幂等验证）。归属：权限 PR-0。

## 18. SQLAlchemy Core + Alembic 脚手架（数据 PR-1，编号原 BE-17）

- 命令：
  - `python -c "from app.db import engine, session, base; print(base.metadata.naming_convention)"`
  - `DATA_DB_PATH=/tmp/be17_smoke.db python main.py migrate head`
  - `python -c "import sqlite3; c=sqlite3.connect('/tmp/be17_smoke.db'); print([r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")])"`
- 期望：
  - 首条：`app.db` 三模块 import 成功；`naming_convention` 输出包含 `ix / uq / ck / fk / pk` 五项，无异常。
  - 次条：`migrate head` exit=0，`/tmp/be17_smoke.db` 文件被创建（父目录自动 mkdir）。
  - 末条：sqlite_master 至少含 `alembic_version` 表；本 PR 起点无业务表，Alembic 系统表存在即证明脚手架就位。
- 关联事实：`get_settings().data_db_path` 现读；`app/shared/settings/runtime.py` 22 → 23 字段；`main.py:DATA_DB_PATH` 常量作为启动锚点 + env `DATA_DB_PATH` 覆盖入口；`main.py` L302-388 冻结区间零触碰。归属：数据 PR-1。

## 19. JSON Store facade helper 层收编（PR-BE-04，承接编号 BE-18-store）

- 命令：
  - `python -c "from app.stores import canvas_store, project_store, history_store, prompt_library_store, workflow_store, conversation_store, asset_library_store, provider_config_store, storage_settings_store; print('ok')"`
  - `python -c "import re, ast; src=open('main.py',encoding='utf-8').read(); tree=ast.parse(src); H={'save_canvas','load_canvas','load_projects','save_projects','load_asset_library','save_asset_library','load_prompt_libraries','save_prompt_libraries','load_api_providers','save_api_providers','save_to_history','load_conversation','save_conversation','load_runninghub_workflow_store','save_runninghub_workflow_store','load_storage_settings'}; n=sum(1 for x in ast.walk(tree) if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id in H); print('bare_helper_calls=', n)"`
  - `python -m pytest tests/stores/ -v`
- 期望：
  - 首条：9 个 store 全部 import 成功、打印 `ok`。
  - 次条：`bare_helper_calls` **≤ 3**（`storage_settings_snapshot` 内 1 + `apply_storage_settings` 内 1 + 未来可能的冻结点，全部为豁免项）。数据 PR-0 冻结前该值 ≥ 42（15 helper × 数百 route/helper 使用点，含路由层的 101 处已被 PR-0 收编）。PR-BE-04 后 helper 层 26 处 bare 调用清零，剩余的 bare 调用全部落在文件对象治理 PR-0 冻结区间（`main.py:L302-412` 范围内的 `storage_settings_snapshot` / `apply_storage_settings`）。
  - 末条：`tests/stores/test_be04_bare_call_migration.py` 42 项测试全绿（含 15 项 facade 委派 identity 参数化测试 + 9 项 store round-trip + 10 项 helper-in-helper 场景 + 5 项 TestClient E2E + 3 项 AST 抗回归断言）。
- 关联事实：`main.py:302-388` 冻结区间零触碰；`apply_storage_settings`（L394-412）内的 `load_storage_settings` bare 调用同样保留（该函数被文件对象治理 PR-0 明确命名冻结）；`app/stores/*.py` 9 个 facade 模块**未新增 public 方法**（全部 26 处 bare 调用点均命中现有 facade 方法，无需扩展签名）；`openapi_diff.py --baseline` exit=0。归属：PR-BE-04。

> **§19 编号说明**：§19 承接协调纲要 [[2026-07-17 第二批 PR 开工协调纲要#波次编排]] 中 Wave 1 的 PR-BE-04 收编事项，与协调纲要 §保活烟测 中的 BE-18（任务 PR-0，Wave 2）编号不同——协调纲要按业务口径给"每个 PR 一个 BE 编号"；本 checklist 按"章节序号"编号且不许跳号，所以 PR-BE-04 在此占 §19。BE-18-store 是本项在治理机制层面的稳定别名，避免与任务 PR-0 的 BE-18 命名冲突。

> **烟测编号与协调纲要对齐说明**：本 checklist 的 §15 / §16 / §17 / §18 分别对应协调纲要 [[2026-07-17 第二批 PR 开工协调纲要#保活烟测（继续）]] 中的 BE-15 / BE-16 / BE-19 / BE-17。**BE-18（任务 PR-0）编号保留给 Wave 2**——本 checklist 待其 PR 合入后再落项。文档内的 `##` 序号必须连续（不许跳号），所以协调纲要的 BE-19 在本 checklist 中占用序号 §17，数据 PR-1 的 BE-17 在此占用序号 §18（编号是"业务口径" vs "文档口径"两套映射）。

## 20. Task 层表结构 + Store 端口 + 契约测试（任务 PR-0，承接协调纲要 BE-18-task）

- 命令：
  - `python -c "from app.task.contracts import Task, TaskDraft, NodeRun, NodeRunDraft, ProviderTask, ProviderTaskDraft, TaskEvent, TaskEventDraft, Artifact, ArtifactDraft, CasFailure, RecoveryFilter, LeaseInfo; from app.task.tables import TASK_LAYER_TABLE_NAMES; from app.db.base import metadata; assert set(TASK_LAYER_TABLE_NAMES) <= set(metadata.tables), (list(metadata.tables), TASK_LAYER_TABLE_NAMES); from app.task.store import memory_stores, TaskStore, NodeRunStore, ProviderTaskStore, TaskEventStore, ArtifactStore; print('ok')"`
  - `DATA_DB_PATH=$(pwd)/be18_task_smoke.db python main.py migrate head && python -c "import sqlite3; c=sqlite3.connect('be18_task_smoke.db'); rows=sorted(r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'\")); print('tables=', rows); v=[r[0] for r in c.execute('SELECT version_num FROM alembic_version')]; print('version=', v)" && rm -f be18_task_smoke.db`
  - `python -m pytest tests/task/ -v`
- 期望：
  - 首条：五个 Snapshot dataclass + 五个 Draft dataclass + `CasFailure` / `RecoveryFilter` / `LeaseInfo` import 成功；`app/task/tables.py` 5 张表**全部**已挂到 `app.db.base.metadata`；`memory_stores()` / 5 个 Store `Protocol` import 成功；打印 `ok`。
  - 次条：`migrate head` exit=0；输出 `tables=['alembic_version', 'artifacts', 'node_runs', 'provider_tasks', 'task_events', 'tasks']`（6 项，含 `alembic_version`）；`version=['0001_task_layer']`。
  - 末条：`tests/task/` 全绿（3 个测试文件 · 48 项 = `test_migration_0001.py` 5 项 + `test_metadata_singleton.py` 3 项 + `test_store_contract.py` 40 项含 memory/sqlite 参数化）。
- 关联事实：**首个真 Alembic revision** = `0001_task_layer`（`down_revision=None`）；5 张表主键 `UUID`，`task_events.id` 破例 `BIGINT AUTOINCREMENT`（SQLite 侧走 `INTEGER PRIMARY KEY` 快路径）；4 类必备索引 `(status, updated_at)` / `(idempotency_key)` UNIQUE / `(canvas_id, node_id)` / `(provider_id, upstream_task_id)` 全部就位；Store 端口签名冻结（六类接口：CRUD / CAS / lease / heartbeat / append seq 单调 / recovery scan）；`main.py` 零改动；`openapi_diff.py --baseline` exit=0；`base.metadata.tables` 从 0 → 5 表（数据 PR-1 起点为空）。归属：任务 PR-0（Wave 2）。

## 21. RequestValidationError handler 短期兜底（PR-BE-12，承接编号 BE-20）

- 命令：
  - `curl -s -D /tmp/be20_headers.txt -X PUT http://127.0.0.1:3000/api/providers -H 'Content-Type: application/json' -d '{"providers":[{"id":"__smoke_be20__","name":"smoke","protocol":"openai","api_key":"sk-TEST-DO-NOT-LOG-e2e"}]}'`
  - `tail -n 200 <server-log-path> | grep -c 'sk-TEST-DO-NOT-LOG-e2e'`
  - `python -m pytest tests/api/test_validation_error_handler.py -v`
- 期望：
  - 首条：HTTP 422；响应 body **不含** `sk-TEST-DO-NOT-LOG-e2e` 字面量（`grep -c` = 0）；响应 body 顶层含 `"request_id": "<32-hex>"` 字段；`/tmp/be20_headers.txt` 含 `x-request-id: <32-hex>` 且值与 body 内 `request_id` 一致；`errors[].input` 已剔除。
  - 次条：服务端日志 tail `grep -c 'sk-TEST-DO-NOT-LOG-e2e'` = **0**（本 PR **不改**日志脱敏配置——验证 PR-BE-02 `RequestIdLogFilter` + PR-BE-03 现状不打印 request body 已经足够满足；若日志中出现密钥字面量，则 CB-02 长期根治 Provider PR-05 + 部署 PR-10 未闭合部分暴露，作为发现列到"CB 候选"，**不许在本 PR 内擅自加日志脱敏**）。
  - 末条：`pytest tests/api/test_validation_error_handler.py -v` **9 项全绿**（1 CB-02 主场景 + 1 客户端提供 X-Request-Id 回显 + 2 其它路由 422 剔除 + 1 正确 shape bypass + 4 参数化 dict/list/bare/none 场景）。
- 关联事实：新增 `app/api/errors.py` `validation_error_handler`；`main.py` L145-155（middleware 注册块之后）追加 `app.add_exception_handler(RequestValidationError, validation_error_handler)`；`main.py:777` 旧 inline handler 已下线；`main.py:751-767` 的 `friendly_validation_error` helper 保留（新 handler 懒 import 复用）；`main.py:356-478` 冻结区间零触碰；`openapi_diff.py --baseline` exit=0（FastAPI 默认不在 OpenAPI spec 中详细描述 422 响应 body shape，本 PR 修改 body 结构不进 schema diff）。归属：PR-BE-12（承接 [[70 开发过程跟踪/缺陷追踪/CB-02 - PUT providers 422 error 回显 request body 含密钥]] 短期兜底）。

> **§21 编号说明**：§21 承接协调纲要 §保活烟测 中的 BE-20（PR-BE-12）。**Wave 2 收官时 Lead 独立核对（2026-07-17）**：任务 PR-0 与 PR-BE-12 两个并发 subagent 各自将自己列为 §20；Lead 收官时依据 §20 编号说明中的"若并发的任务 PR-0 subagent 抢先占 §20 则本项顺延到 §21"约定，把 PR-BE-12 从 §20 顺延到 §21（任务 PR-0 保持 §20，因其承接的 BE-18-task 与业务口径 BE-18 强绑定不宜移动）。§20 与 §21 命令段完全不冲突，只是文档序号。KB 镜像 [[90 资料归档/后端保活烟测清单模板]] 已同步 `diff -q` exit=0。

## 22. Legacy Store snapshot 契约（数据 PR-2）

- 命令：`python -m pytest tests/stores -q`
- 期望：**58 passed**；9 个 Store 均提供 `snapshot()`；8 个普通 Store 的 payload 与 raw_json 来自同一次读取；Provider snapshot 对嵌套未知结构、URL query、`raw` / `workflowJson` 中的密钥做深度脱敏；原 load/save 行为不变。归属：数据 PR-2。

## 23. TaskService + worker 事务边界（任务 PR-1）

- 命令：`python -m pytest tests/task -q`
- 期望：**73 passed**；`TaskService` / `ProviderTaskService` / `NodeRunService`、`TaskExecutor` / `TaskDispatcher` 与默认关闭的进程内 worker 均可导入；SQLite lease 使用 DB CAS；同一 task 的 event seq 并发单调；Memory / SQLite UoW 均支持回滚；retry 必须重新进入状态机。归属：任务 PR-1。

## 24. Provider adapter 契约与注册表（Provider PR-01）

- 命令：`python -m pytest tests/provider -q`
- 期望：**21 passed**；adapter 基类、统一异常、注册表和状态映射可用；`canceled <-> cancelled`、`submitted <-> waiting_upstream` 映射明确；`main.py`、路由和 FastAPI 启动装配零触碰。归属：Provider PR-01。

## 25. DeploymentMode 进程稳定配置（部署 PR-01）

- 命令：`python -m pytest tests/shared -q`
- 期望：**25 passed**；部署模式与安全快照在进程生命周期内稳定，目录路径字段仍保持读时求值；不包含启动装配和生产基础设施变更。归属：部署 PR-01。

> **第三批 Wave 0 Lead 核验**：专题测试合计 **189 passed**；全量测试 **333 passed / 35 skipped**。当前 Python 3.13.5 + FastAPI 0.136.1 + Pydantic 2.12.5 环境下，严格 OpenAPI 旧 baseline 存在 6 处依赖生成差异（5 处 binary schema 表达变化 + `ValidationError` 新增 `ctx` / `input`），但本批 `main.py`、`app/api/**`、路由、DTO 与 baseline 文件均零改动，132 条 path 和 security schemes 无差异；不得通过更新 baseline 掩盖该环境漂移。

## 26. 低风险只读 Router 抽离（PR-BE-05）

- 命令：
  - `python -m pytest tests/api/test_be05_readonly_router_extraction.py -q`
  - 在同一 Python/FastAPI/Pydantic 环境分别于改造前后执行 `python tools/openapi_snapshot.py --out <temp>`，比较两份临时快照 SHA-256。
- 期望：**8 passed**；`GET /api/app-info`、`/api/config`、`/api/models`、`/api/history`、`/api/comfyui/instances`、`/api/workflows` 各注册一次且原顺序不变；ComfyUI PUT、workflow 详情/写路由仍留在 `main.py`；五个 router 只通过 callback factory 装配，禁止 `import main` 和直接文件 IO；前后 OpenAPI 临时快照哈希完全相同。Lead 实测哈希均为 `90E7ADE089DD7C6BAABE0F2AC241EC588762A4803C97BE35D358E6DC262A1166`；全量 **341 passed / 35 skipped**。归属：PR-BE-05。

> **脚本入口防回归**：不得在迁出 router 的 handler 内懒 `import main`。项目用 `python main.py` 启动时入口模块名是 `__main__`，再次 `import main` 会形成第二套模块全局，导致写路由更新 `__main__`、读路由读取副本 `main`。本 PR 使用 `create_router(callback...)` 注入当前模块 helper，专门避免该状态分裂。

## 27. FileService 骨架 + 影子登记（文件 PR-2）

- 命令：
  - `python -m pytest tests/files/ -v`
  - `python -c "from main import app; print('routes=', len(app.routes))"`
  - `python -c "from app.services.files import FileService, LegacyPathConflictError; print('services OK')"`
  - `python -c "from app.shared.ids import generate_id; import uuid; v=generate_id(); print('ver=', v.version, 'var=', v.variant)"`
  - `python tools/openapi_diff.py --baseline tools/openapi_baseline.json`
- 期望：**16 passed / 0 failed / 0 skipped**（`test_file_service.py` 8 项 + `test_main_integration.py` 6 项 + `test_uuid7.py` 2 项）；`routes` 数从 PR-BE-05 后的 166 增至 **167**（+1 = `/api/_diag/file-shadow-align`，`include_in_schema=False` 不进 OpenAPI），`openapi_diff` exit=0 `baseline == current`；`generate_id()` 返回 `uuid.UUID` ver=7 var=RFC 4122；全量测试 **357 passed / 35 skipped**（PR-BE-05 后 341 → +16 与新增测试面吻合）。
- 关联事实：新增 `app/services/files/{__init__,file_service.py}`（FileService 骨架，进程内锁 + 跨进程 `_CrossProcessLock` + `os.replace` 原子写；schema_version=1 索引；事件保留 8 天 + 上限 10_000）；`app/shared/ids.py` +60 行（UUIDv7 `generate_id`）；`main.py` 五段 facade 桥后新增第六段 +169 行（`FILE_SHADOW_WRITE` 三值解析 + `file_service` 单例 + `shadow_register_existing[_in_thread|_async]` + `BoundedSemaphore(4)` 后台并发上限 + 21 处 durable 挂钩点 + 3 处 AST 排除函数 + `/api/_diag/file-shadow-align` 内部诊断 `local_personal` + loopback 双门禁）；`data/file_index.json` 治理期 JSON 索引（未入库，`.gitignore` 已就地补一行）；冻结区 AST byte-equivalent 断言（`class StorageSettings` / `apply_storage_settings` / `storage_settings_snapshot` 三段与 `ba4b87e` baseline 完全一致）。归属：文件 PR-2（[[70 开发过程跟踪/开发编年史/2026-07-18 文件 PR-2 补验收]] Lead 亲自补验收）。

> **AST 层机器可验证契约**：`test_ast_has_required_durable_hooks_and_exclusions` 用 AST 遍历强制 21 个 durable 写入函数**必须**挂钩 `shadow_register_existing`，同时强制 3 个明确排除函数（`_local_upload_item` / `export_canvas_workflow` / `upload_comfyui_base64`）**必须不**挂钩 —— 硬门槛防止未来 subagent 手滑加错或遗漏。`test_file_service_never_calls_adapter_put` 用 AST 遍历强制 `FileService` 内部**从不**调用 `adapter.put` / `open_writable_stream` —— 影子不切主写的机器可验证契约。`test_storage_settings_frozen_functions_match_baseline` 用 `git show ba4b87e:main.py` AST byte-equivalent 断言冻结区。三条 AST 契约任一失败即视为 PR 违反治理约定，直接 REJECT。

---

## 28. 幂等导入器 + 对账工具 + 0002_baseline_tables 建表（数据 PR-3，承接 Wave 3-B 编号 §28）

- 命令：
  - `python -m pytest tests/data_import/ -v`
  - `DATA_DB_PATH="$(pwd)/be28_smoke.db" python main.py migrate head`
  - `python -c "import sqlite3, os; c = sqlite3.connect(os.path.abspath('be28_smoke.db')); print(sorted(r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()))"`
  - `DATA_DB_PATH="$(pwd)/be28_smoke.db" python main.py data-import canvas --dry-run`
  - `DATA_DB_PATH="$(pwd)/be28_smoke.db" python main.py data-reconcile canvas`
  - `python -c "from app.data_import import import_domain, reconcile_domain, SUPPORTED_DOMAINS; print(SUPPORTED_DOMAINS)"`
  - `python tools/openapi_diff.py --baseline tools/openapi_baseline.json`
- 期望：**21 passed / 0 failed / 0 skipped**（`test_migration_0002.py` 4 项 + `test_metadata_singleton.py` 3 项 + `test_importer_idempotent.py` 9 项 + `test_provider_credential_never_imported.py` 2 项 + `test_cli_smoke.py` 3 项）；`migrate head` 完成后 `sqlite_master` 应含 `alembic_version` + task 层 5 张 + baseline 9 张 = **15 张 table**（`alembic_version` `artifacts` `asset_categories` `asset_items` `asset_libraries` `canvases` `node_runs` `projects` `prompt_items` `prompt_libraries` `provider_configs` `provider_tasks` `task_events` `tasks` `workflow_definitions`）；`data-import canvas --dry-run` 返回稳定 JSON `{"candidate_count": ..., "domain": "canvas", "dry_run": true, "inserted": ..., "skipped": ..., "source_count": ...}`；`data-reconcile canvas` 返回稳定 JSON `{"counts": {"db": ..., "json": ...}, "domain": "canvas", "field_diffs": [], "missing": [...]}`；`SUPPORTED_DOMAINS == ('project', 'provider_config', 'prompt_library', 'workflow_definition', 'asset_library', 'canvas')`；`openapi_diff` exit=0；全量测试 **390 passed / 35 skipped**（本 PR 前基线 369 = 文件 PR-2 后 357 + 前端 PR-4 `7a19a31` 已合入的 12 项 MediaEditor seam；本 PR 新增 21 项 → 390 完全吻合）。
- 关联事实：新增 Alembic revision `0002_baseline_tables`（`down_revision="0001_task_layer"`）建 9 张业务表（`projects / provider_configs / prompt_libraries / prompt_items / workflow_definitions / asset_libraries / asset_categories / asset_items / canvases`）；主键统一 UUIDv7（`Uuid(as_uuid=True) + default=generate_id`）；`legacy_id TEXT UNIQUE NOT NULL` 幂等键；`raw_json TEXT NULL` + `schema_version TEXT DEFAULT 'v1_legacy_json'` + `imported_at`/`created_at`/`updated_at`（`DateTime(timezone=True)`）；`asset_items` 附带 `file_ref TEXT NULL`（文件对象专题接口预留占位，本 PR 不启用）+ `legacy_url` / `source_url` / `workspace_id NULL` / `project_id NULL`；`canvases` 附带 `content_json TEXT` + `revision INTEGER DEFAULT 0` + `base_updated_at TEXT` + `deleted_at TEXT NULL`；15 个显式命名 Index + 9 个 UNIQUE 约束（每张 `uq_<tbl>_legacy_id`）。新增 `app/data_import/` 包（`__init__.py` re-export `import_domain / reconcile_domain`；`orchestrator.py` 调度；`reconcile.py` re-export；`_shared.py` `now_utc / serialize_raw_json / insert_if_absent`；`importers/{canvas,project,provider_config,prompt_library,workflow_definition,asset_library}.py` 6 个幂等 importer，`INSERT OR IGNORE ON legacy_id` via `sqlite_insert(...).on_conflict_do_nothing(index_elements=['legacy_id'])`；`tables.py` 9 张 Table 全部挂 `app.db.base.metadata` 单例）；`app/db/migrations/env.py` +1 行 `import app.data_import.tables`；`main.py` `if __name__ == "__main__":` 段追加 `data-import <domain> [--dry-run] [--from <path>]` / `data-reconcile <domain>` CLI dispatch +31 行（**不 import sqlalchemy / Session；只调 `from app.data_import import import_domain, reconcile_domain`**）；冻结区（`class StorageSettings` body + `def apply_storage_settings` body + `storage_settings_snapshot` body）AST byte-equivalent 断言通过。归属：数据 PR-3（[[70 开发过程跟踪/PR 状态总账/PR - 数据模型#数据 PR-3：幂等导入器与对账工具]]）。

> **AST 层机器可验证契约**：`tests/data_import/test_no_sqlalchemy_in_main.py` 用 AST 遍历强制 `main.py` 顶层 body **不许** `import sqlalchemy` / `from sqlalchemy.orm import Session` —— CLI 层禁 SQL 泄漏的机器可验证契约。`tests/data_import/test_metadata_singleton.py` 强制 9 张 baseline 表挂 `app.db.base.metadata` 单例 + AST 禁自建 `MetaData()`。`tests/data_import/test_provider_credential_never_imported.py::test_provider_importer_calls_safe_records` AST 断言 provider importer 必须调用 `_safe_provider_records` 深层脱敏。三条 AST 契约任一失败即视为违反治理约定，直接 REJECT。

---

## 29. 影子登记 —— CANVAS_TASKS / pendingTasks 双记录（任务 PR-3，Wave 3-B §29）

- 命令：
  - `python -m pytest tests/task/shadow/ -v`
  - `python -m pytest tests/task -q`
  - `TASK_SHADOW_ENABLE=true python -c "from app.task.shadow import get_shadow_registry, is_shadow_enabled; print('enabled=', is_shadow_enabled()); r = get_shadow_registry(); print('registry_ok=', r is not None)"`
  - `python scripts/task_shadow_reconcile.py`
  - `python -c "from main import app; print('routes=', len(app.routes))"`
  - `python tools/openapi_diff.py --baseline tools/openapi_baseline.json`
- 期望：**21 passed / 0 failed / 0 skipped**（`test_shadow_registration.py` 3 项 + `test_shadow_disabled_default.py` 4 项 + `test_shadow_failure_isolated.py` 3 项 + `test_shadow_state_transitions.py` 3 项 + `test_shadow_provider_task.py` 3 项 + `test_main_shadow_hook_count.py` 3 项 + `test_shadow_reconcile_cli.py` 2 项）；`tests/task -q` **94 passed**（任务 PR-1 遗留 73 + 本 PR 新增 21）；`is_shadow_enabled()` 在 flag on 时为 `True`；对账 CLI 输出稳定 JSON 键 `{"canvas_tasks_count", "shadow_tasks_count", "missing_shadow", "extra_shadow", "kind_stats"}` 且 exit=0；`routes=167` 与文件 PR-2 后基线一致（**不新增路由**）；`openapi_diff` exit=0；全量测试 **411 passed / 35 skipped**（数据 PR-3 后基线 390 + 本 PR 新增 21）。
- 关联事实：新增 `app/task/shadow/{__init__.py, register.py}` —— `ShadowRegistry` 提供 5 个挂钩 API（`register_submit / register_transition / register_provider_task / register_node_run / register_release`）+ 惰性 `_ensure_ready()`（首次触发 `run_migrations("head")` + `sqlite_stores()`）+ `TASK_SHADOW_ENABLE` env 门禁（`{1, true, yes, on, enable, enabled}` 视为 truthy）+ CANVAS 状态字面量到治理方案 14 态的映射表 + `_shortest_path` BFS 合成 `queued→leased→running` 中间态（`_SHADOW_LEASE_OWNER = "shadow-registry@pr3"`）+ 幂等（`idempotency_key=f"canvas_task:{canvas_task_id}"` + `(provider_id, upstream_task_id)` 复用）；`main.py` 第 6 段 facade 桥 import `_get_shadow_registry` + `_shadow_register(operation, ...)` 转发器 + `CANVAS_TASKS` 6 处交互点挂钩（image：running / succeeded / failed + jimeng provider_task；comfy：running / succeeded / failed；create_image：submit；create_comfy：submit）；新增 `scripts/task_shadow_reconcile.py` 对账 CLI（`--since <hours>` 可选窗口，稳定 JSON 输出）；新增 `tests/task/shadow/` 7 个测试文件；`CANVAS_TASKS` 事实源 + `/api/canvas-image-tasks/{id}` / `/api/canvas-comfy-tasks/{id}` 读路径**不切**；`main.py` 冻结区（`class StorageSettings` body + `def apply_storage_settings` body + `storage_settings_snapshot` body）AST byte-equivalent 断言通过；影子写失败仅记 warning，绝不 raise 到旧路径；`TASK_SHADOW_ENABLE=false`（默认）时 registry 不构造 store、不 migrate、不做任何写入。归属：任务 PR-3（[[70 开发过程跟踪/PR 状态总账/PR - 任务模型#任务 PR-3：影子登记 —— CANVAS_TASKS / pendingTasks 双记录]]）。

> **AST 层机器可验证契约**：`tests/task/shadow/test_main_shadow_hook_count.py` 用 AST 遍历强制 `main.py` 内 `_shadow_register(...)` 调用点 **≥ 6**、`_shadow_register` 顶层 `def` 存在、`from app.task.shadow import get_shadow_registry` facade 桥 import 存在。任一项失败即视为未来 PR 误删影子挂钩，直接 REJECT。

---

## 30. 低风险 4 类 shadow 双读 —— Project / ProviderConfig / PromptLibrary / WorkflowDefinition（数据 PR-4，Wave 3-C §30）

- 命令：
  - `python -m pytest tests/shadow_read/ -v`
  - `python -m pytest tests/shared/test_settings.py -q`
  - `SHADOW_READ_PROJECT=false SHADOW_READ_PROVIDER_CONFIG=false SHADOW_READ_PROMPT_LIBRARY=false SHADOW_READ_WORKFLOW_DEFINITION=false python -c "from app.stores import project_store, provider_config_store, prompt_library_store, workflow_store; from app.shadow_read import is_shadow_read_enabled; print(all(not is_shadow_read_enabled(d) for d in ('project', 'provider_config', 'prompt_library', 'workflow_definition')))"`
  - `python -c "from main import app; print('routes=', len(app.routes))"`
  - `python tools/openapi_diff.py --baseline tools/openapi_baseline.json`
  - `git status --short data/shadow_diff/`
- 期望：**26 passed / 0 failed / 0 skipped**（`test_diff_jsonl_schema.py` 4 项 + `test_frozen_zone_untouched.py` 2 项 + `test_project_shadow.py` 6 项 + `test_prompt_library_shadow.py` 3 项 + `test_provider_shadow_no_credentials.py` 3 项 + `test_shadow_disabled_default.py` 5 项 + `test_workflow_definition_shadow.py` 3 项）；`tests/shared/test_settings.py` 15 项全绿（字段总数断言 23 → 27）；`is_shadow_read_enabled` 在四个 env 全默认 `false` 时全部返回 `True/False` 组合应为 `True`（`all not ...` = True）；`routes=167` 与文件 PR-2 后基线一致（**不新增路由**）；`openapi_diff` exit=0；`data/shadow_diff/` 只有 `.gitkeep` 入库，运行时子目录与 `*.jsonl` 由根 `.gitignore` 排除；全量测试 **437 passed / 35 skipped**（任务 PR-3 后基线 411 + 本 PR 新增 26）。
- 关联事实：新增 `app/shadow_read/` 包（`__init__.py` re-export；`runner.py` 通用入口 `run_shadow_read(domain, json_result, *, request_id=None)` + `is_shadow_read_enabled(domain)` 门禁 + JSON→normalized dict + DB baseline 快照读取 + 稳定字段集 diff；`fields.py` 4 domain 稳定字段集常量 `PROJECT_STABLE_FIELDS / PROVIDER_STABLE_FIELDS / PROMPT_LIBRARY_STABLE_FIELDS / WORKFLOW_DEFINITION_STABLE_FIELDS`；`diff_writer.py` `DIFF_RECORD_KEYS = ('ts', 'domain', 'request_id', 'missing_in_db', 'missing_in_json', 'field_diffs')` 稳定键位 + `data/shadow_diff/<domain>/<yyyymmdd>.jsonl` 追加落盘 + 失败隔离）；4 个 Store facade（`app/stores/{project,provider_config,prompt_library,workflow}_store.py`）新增 `read_shadow(json_snapshot, *, request_id=None) -> None` 方法 + `load_*()` 完成 JSON 主读后惰性调 `read_shadow(result)`（`SHADOW_READ_*=false` 时零开销 return，不 import DB 层）；Provider shadow 复用 `_safe_provider_records` 深层脱敏（密钥字段永不进 diff 日志，`grep=0` 硬门槛）；`app/shared/settings/runtime.py` `Settings` 追加 4 字段 `shadow_read_project / shadow_read_provider_config / shadow_read_prompt_library / shadow_read_workflow_definition` + `get_settings()` mirror 到 4 个 `main` 常量（`SHADOW_READ_PROJECT / SHADOW_READ_PROVIDER_CONFIG / SHADOW_READ_PROMPT_LIBRARY / SHADOW_READ_WORKFLOW_DEFINITION`，紧邻 `DATA_DB_PATH` 声明，走 PR-BE-03 "两步走" 约定；`Settings` 字段总数 23 → 27）；`main.py` 冻结区（`class StorageSettings` body + `def apply_storage_settings` body + `def storage_settings_snapshot` body）AST byte-equivalent 断言通过（`test_frozen_zone_untouched.py::test_storage_settings_frozen_zone_unchanged_by_pr4`）；顶层禁 `import sqlalchemy` 抗回归（承接数据 PR-3 `test_no_sqlalchemy_in_main.py` 契约）；`data/shadow_diff/.gitkeep` 保留骨架、根 `.gitignore` 追加 `data/shadow_diff/**/*.jsonl` + `data/shadow_diff/*/` 排除运行时子目录。归属：数据 PR-4（[[70 开发过程跟踪/PR 状态总账/PR - 数据模型#数据 PR-4]]）。

> **AST 层机器可验证契约**：`tests/shadow_read/test_frozen_zone_untouched.py::test_storage_settings_frozen_zone_unchanged_by_pr4` 用 `ast.dump(include_attributes=False)` 对齐 `class StorageSettings` / `def apply_storage_settings` / `def storage_settings_snapshot` 三处与 `ba4b87e:main.py` baseline byte-equivalent —— 数据 PR-4 未来任何 subagent 触碰这三段 body 直接 REJECT。`test_pr4_did_not_import_sqlalchemy_at_main_top_level` 断言 `main.py` 顶层 body 不许 `import sqlalchemy` 或 `from sqlalchemy.orm import Session` —— 承接数据 PR-3 抗回归。`tests/shadow_read/test_shadow_disabled_default.py::test_stores_disabled_do_not_touch_db` 用 monkeypatch 把 `app.db.engine.get_engine` 换成 raise —— 4 个 Store 在 `SHADOW_READ_*=false` 时若触发 engine 构造即视为违反"零开销 short-circuit"契约，直接 REJECT。

---

## 32. GenerationHistory 与 Task 分离（任务 PR-4，Wave 3-C §32）

- 命令：
  - `python -m pytest tests/task/history/ -v`
  - `python -m pytest tests/task -q`
  - `TASK_HISTORY_ENABLE=true python -c "from app.task.history import get_history_writer, is_history_writer_enabled; print('enabled=', is_history_writer_enabled()); w = get_history_writer(); print('writer_ok=', w is not None)"`
  - `python scripts/task_history_reconcile.py`
  - `python -c "from main import app; print('routes=', len(app.routes))"`
  - `python tools/openapi_diff.py --baseline tools/openapi_baseline.json`
- 期望：**21 passed / 0 failed / 0 skipped**（`test_history_writer_disabled_default.py` 4 项 + `test_history_writer_idempotent.py` 3 项 + `test_history_writer_failure_isolated.py` 3 项 + `test_history_derive_from_task_snapshot.py` 4 项 + `test_history_reader_compat.py` 3 项 + `test_main_history_hook_count.py` 2 项 + `test_history_reconcile_cli.py` 2 项）；`tests/task -q` **115 passed**（任务 PR-1 遗留 73 + 任务 PR-3 遗留 21 + 本 PR 新增 21）；`is_history_writer_enabled()` 在 flag on 时为 `True`；对账 CLI 输出稳定 JSON 键 `{"history_json_count", "derived_count", "missing_derived", "extra_derived", "kind_stats"}` 且 exit=0；`routes=167` 与文件 PR-2 后基线一致（**不新增路由**）；`openapi_diff` exit=0；全量测试 **474 passed / 35 skipped**（前端 PR-5 未合入基线情形下 =453+21；前端 PR-5 已合入基线情形下 =前端 PR-5 后基线 + 21）。
- 关联事实：新增 `app/task/history/{__init__.py, writer.py, reader.py}` —— `HistoryWriter` 提供 `write_from_task(task_snapshot, artifacts, *, source_record)` 派生副本入口 + 惰性 `_ensure_ready()`（首次触发 `run_migrations("head")` + `sqlite_stores()`）+ `TASK_HISTORY_ENABLE` env 门禁（`{1, true, yes, on, enable, enabled}` 视为 truthy，与 `TASK_SHADOW_ENABLE` 对齐）+ record 摘要 key（`sha1(task_id|request_id|timestamp)`）幂等（idempotency_key = `history:<sha>`）+ `_HISTORY_TYPE_TO_TASK_TYPE` 5 类字面量映射（online→online-image / angle→online-image / zimage→comfy-workflow / runninghub→runninghub-workflow / video→online-video；未映射 fallback 直传）+ `HistoryReader.read_history_compat(*, filter_type, writer)` 只读兼容层（`TASK_HISTORY_ENABLE=false` 时 byte-equivalent `get_history_api`，启用后追加 `derived_task_id / derived_artifact_ids` 派生字段）；`main.py` 顶部第 7 段 facade 桥 import `_get_history_writer` + 顶层 helper `def _history_derive(operation, *args, **kwargs)` 转发器（对齐任务 PR-3 `_shadow_register` 模式）+ `main.py:13596 / 13645 / 13713` 3 处**在 `history_store.save_to_history` 旁边**追加 `_history_derive("write_from_result", record=result)` 调用（不改主写函数体）；新增 `scripts/task_history_reconcile.py` 对账 CLI（`--since <hours>` 可选窗口，稳定 JSON 输出）；新增 `tests/task/history/` 7 文件 21 项测试；`history.json` 主写路径**完全不变**（`main.save_to_history` body byte-equivalent）；读路径**不切**（`GET /api/history` 仍读 `history.json`）；派生写失败仅记 warning，绝不 raise 到 `save_to_history` 主路径（`_history_derive` 双层 try/except 保护）；`TASK_HISTORY_ENABLE=false`（默认）时 writer 不构造 store、不 migrate、不做任何写入；`main.py` 冻结区（`class StorageSettings` body + `def apply_storage_settings` body + `storage_settings_snapshot` body）AST byte-equivalent 断言通过；任务 PR-3 六处影子挂钩点（image `run_*` / `create_*`、comfy `run_*` / `create_*`）body 零触碰（`_shadow_register` 函数体 byte-equivalent + 调用点数 10 恒定）。归属：任务 PR-4（[[70 开发过程跟踪/PR 状态总账/PR - 任务模型#任务 PR-4：GenerationHistory 与 Task 分离，历史归历史]]）。

> **AST 层机器可验证契约**：`tests/task/history/test_main_history_hook_count.py` 用 AST 遍历强制 `main.py` 内 `_history_derive(...)` 调用点 **≥ 3**、`_history_derive` 顶层 `def` 存在、`from app.task.history import get_history_writer` facade 桥 import 存在。任一项失败即视为未来 PR 误删 History 派生挂钩，直接 REJECT。

---

---

## 33. Canvas shadow 双读（数据 PR-5，Wave 3-D §33）

- 命令：
  - `python -m pytest tests/shadow_read/test_canvas_shadow.py -v`
  - `python -m pytest tests/shared/test_settings.py -q`
  - `SHADOW_READ_CANVAS=false python -c "from app.shadow_read import is_shadow_read_enabled; print(is_shadow_read_enabled('canvas'))"`
  - `python -c "from main import app; print('routes=', len(app.routes))"`
  - `python tools/openapi_diff.py --baseline tools/openapi_baseline.json`
  - `git status --short data/shadow_diff/`
- 期望：**6 passed / 0 failed / 0 skipped**（`test_canvas_shadow.py` 6 项）；`tests/shared/test_settings.py` 15 项全绿（字段总数断言 27 → 28）；`is_shadow_read_enabled('canvas')` 在 `SHADOW_READ_CANVAS=false` 时返回 `False`；`routes=167` 与基线一致（**不新增路由**）；`openapi_diff` exit=0；`data/shadow_diff/` 只有 `.gitkeep` 入库，运行时子目录与 `*.jsonl` 由根 `.gitignore` 排除。
- 关联事实：`app/shadow_read/fields.py` 新增 `CANVAS_STABLE_FIELDS`（`id, title, kind, project_legacy_id, owner_label, pinned, created_at, updated_at, deleted_at, revision, base_updated_at`）+ `STABLE_FIELDS_BY_DOMAIN` + `SUPPORTED_SHADOW_DOMAINS` 追加 `"canvas"`；`app/shadow_read/runner.py` `_DOMAIN_TO_ENV` 追加 `"canvas": "SHADOW_READ_CANVAS"` + `_normalize_json_canvas` + `_load_db_snapshot` canvas 域查询 + `_project_db_row_to_stable` canvas 域行映射；`app/stores/canvas_store.py` 新增 `DOMAIN = "canvas"` + `read_shadow()` + `load_canvas()` 惰性 hook；`app/shared/settings/runtime.py` `Settings` 追加 `shadow_read_canvas: bool` 字段（27 → 28）；`main.py` 追加 `SHADOW_READ_CANVAS = False` 常量；`tests/shared/test_settings.py` 映射 + 断言 27 → 28；`main.py` 冻结区（`class StorageSettings` body + `def apply_storage_settings` body + `storage_settings_snapshot` body）AST byte-equivalent 断言通过；`save_canvas` 函数体（L3528-3532）零触碰。归属：数据 PR-5（[[70 开发过程跟踪/PR 状态总账/PR - 数据模型#数据 PR-5]]）。

> **AST 层机器可验证契约**：`SHADOW_READ_CANVAS=false` 时 `load_canvas` 行为与数据 PR-4 基线完全一致，shadow 结果不进入 HTTP 响应。任何异常仅记 warning，不冒泡。`main.py` 顶层 body 禁 `import sqlalchemy` 抗回归（承接数据 PR-3 契约）。

---

## 34. Canvas 内容 shadow 短窗双写 + `content_hash` 对账（数据 PR-6，Wave 3-E §34）

- 命令：
  - `python -m pytest tests/shadow_write/ -v`
  - `python -m pytest tests/shared/test_settings.py -q`
  - `SHADOW_WRITE_CANVAS=false python -c "from app.shadow_write import is_shadow_write_enabled; print(is_shadow_write_enabled('canvas'))"`
  - `python -c "from main import app; print('routes=', len(app.routes))"`
  - `python tools/openapi_diff.py --baseline tools/openapi_baseline.json`
  - `alembic upgrade head`（首次可选）→ `python -m tools.data_reconcile canvas` → stdout 打印 `{"domain":"canvas","json_count":..,"db_count":..,"missing_in_db":[..],"missing_in_json":[..],"hash_mismatch":[..],"hash_null_in_db":[..]}`
  - `git status --short data/shadow_diff/`
- 期望：**8 passed / 0 failed / 0 skipped**（`test_canvas_shadow_write.py` 8 项）；`tests/shared/test_settings.py` 15 项全绿（字段总数断言 28 → 29）；`is_shadow_write_enabled('canvas')` 在 `SHADOW_WRITE_CANVAS=false` 时返回 `False`；`routes=167` 与基线一致（**不新增路由**）；`openapi_diff` exit=0；`data/shadow_diff/` 只有 `.gitkeep` 入库，运行时 `canvas_write/*.jsonl` 由根 `.gitignore` 排除；对账 CLI stdout JSON 键位稳定；开关打开后 `save_canvas(canvas)` 主写延迟不新增（IO 已完成后异步 upsert，>1MB 画布 hash + upsert 单次 P95 < 500ms）；`content_hash = sha256(disk_bytes(canvas.json))` 字节等价（磁盘为字节权威源，避免 Windows text-mode `\r\n` 差异）；全量测试 **488 passed / 35 skipped**（数据 PR-5 后基线 480 + 本 PR 新增 8）。
- 关联事实：新增 `app/db/migrations/versions/0003_canvas_content_hash.py`（`revision="0003_canvas_content_hash"` / `down_revision="0002_baseline_tables"`；`op.batch_alter_table("canvases", recreate="auto")` 走 SQLite 兼容路径；`alembic upgrade head → downgrade -1 → upgrade head` 三次干净往返）；`app/data_import/tables.py:canvases` 新增 `Column("content_hash", Text, nullable=True)`；`app/data_import/importers/canvas.py:_record_from_payload` 补写 `content_hash = sha256(raw_text.encode("utf-8"))`（导入器幂等契约保持）；新增 `app/shadow_write/` 模块（`__init__.py` re-export `is_shadow_write_enabled` / `run_shadow_write`；`runner.py` 通用入口 `run_shadow_write(domain, snapshot, *, request_id=None)` + `is_shadow_write_enabled(domain)` 门禁 + 磁盘字节读回作 hash 权威源 + `sqlite_insert(...).on_conflict_do_update(index_elements=["legacy_id"])` upsert；`diff_writer.py` `WRITE_FAILURE_KEYS = ('ts','domain','legacy_id','error','request_id')` 稳定键位 + `data/shadow_diff/canvas_write/<yyyymmdd>.jsonl` 追加落盘 + 失败隔离）；`app/stores/canvas_store.py:save_canvas` wrapper 内在 `_impl(*args, **kwargs)` 调用**成功后**追加 `_write_shadow_after_save(args, kwargs)` hook + `_extract_canvas_snapshot` 位置/关键字参数还原 + 双层 `try/except` 失败隔离（异常仅 warning，永不冒泡到 `save_canvas` 主路径）；`app/shared/settings/runtime.py:Settings` 追加 `shadow_write_canvas: bool` 字段（28 → 29）+ `get_settings()` mirror 到 `main.SHADOW_WRITE_CANVAS`；`main.py` 追加 `SHADOW_WRITE_CANVAS = False` 常量（紧邻 `SHADOW_READ_CANVAS` 声明，走 PR-BE-03 "两步走" 约定）；`tests/shared/test_settings.py` 映射 + 断言 28 → 29；`tests/shadow_write/test_canvas_shadow_write.py` 8 项 STRONG 测试；新增 `tools/data_reconcile.py`（`python -m tools.data_reconcile canvas [--source-dir <path>]` 只读对账 CLI，stdout 稳定 JSON 摘要，不写盘、不改数据）；`main.py:save_canvas` 函数体（L3530-3534）零字节触碰（AST byte-equivalent 断言通过 vs baseline `ae50b28`）；`main.py` 冻结区（`class StorageSettings` body + `def apply_storage_settings` body + `storage_settings_snapshot` body）AST byte-equivalent 断言通过；顶层禁 `import sqlalchemy` 抗回归（承接数据 PR-3 契约）；读/写路径独立（不改 `app/shadow_read/` 任何文件）；`SHADOW_WRITE_CANVAS=false` 默认关闭路径无任何行为变化（不 import DB 层、不构造 engine、不落 diff 文件）。归属：数据 PR-6（[[70 开发过程跟踪/PR 状态总账/PR - 数据模型#数据 PR-6]]）。

> **AST 层机器可验证契约**：`tests/shadow_write/test_canvas_shadow_write.py::test_save_canvas_frozen_zone_byte_equivalent` 用 `ast.dump(include_attributes=False)` 对齐当前 `main.py:save_canvas` 与 baseline `ae50b28:main.py:save_canvas` byte-equivalent —— 数据 PR-6 未来任何 subagent 触碰 `save_canvas` 函数体直接 REJECT。`test_frozen_zone_ast_still_byte_equivalent` 保持 `class StorageSettings` / `def apply_storage_settings` / `def storage_settings_snapshot` 三处与 `ba4b87e:main.py` baseline byte-equivalent（承接数据 PR-4 抗回归契约）。`test_shadow_write_disabled_default_is_zero_effect` 用 monkeypatch 把 `app.db.engine.get_engine` 换成 raise —— `SHADOW_WRITE_CANVAS=false` 时若触发 engine 构造即视为违反"零开销 short-circuit"契约，直接 REJECT。`test_shadow_write_failure_does_not_block_json_primary_write` 用 monkeypatch 把 `_upsert_canvas` 换成 raise —— shadow 内部异常必须仅记 warning + 落 `data/shadow_diff/canvas_write/*.jsonl`，JSON 主写仍成功（P0 硬约束）。

---

## 35. Canvas 主写机制运维手册（数据 PR-7，Wave 3-F §35）

**定位**：本段是**运维手册**，不是烟测通过条件。数据 PR-7 只交付"主写机制搭建 + 显式 DB 启用能力"，**默认仍为 JSON 主写**（`CANVAS_PRIMARY_WRITE=json`）。反转默认值（切 `db`）是独立运维动作 / 独立 PR，不在 PR-7 代码范围。

- 命令：
  - `python -m pytest tests/db/test_canvas_writer.py tests/shared/test_settings.py -v`
  - `python -c "from main import CANVAS_PRIMARY_WRITE; assert CANVAS_PRIMARY_WRITE == 'json', 'default must be json'"`
  - `python -c "from main import app; print('routes=', len(app.routes))"`
  - `python tools/openapi_diff.py --baseline tools/openapi_baseline.json`
- 期望：`tests/db/test_canvas_writer.py` 全绿（~14 项，含 `sys.modules` 隔离断言 + 幂等 + 乐观锁 409 + 异步回写 + 大画布 P95 < 600ms + Settings fail-fast）；`tests/shared/test_settings.py` 字段总数断言 29 → 30；`routes=167` 与基线一致（**不新增路由**）；`openapi_diff` exit=0。

### 灰度切换操作手册

1. **前置观察阶段**（24-48h）：`SHADOW_WRITE_CANVAS=true` 开启短窗双写，观察 `data/shadow_diff/canvas_write/*.jsonl` 应零异常条目；`python -m tools.data_reconcile canvas` 摘要 `hash_mismatch=[]` 且 `missing_in_db=[]`。
2. **对账阶段**：`python -m tools.data_reconcile canvas` 严格检查 `content_hash` 全部一致；有任何 mismatch → 停止切换，先修根因。
3. **切换阶段**：设置 `CANVAS_PRIMARY_WRITE=db` 后重启进程；观察 `data/shadow_diff/canvas_json_fallback/*.jsonl` 应零条目（异步 JSON 回写全成功），`data/shadow_diff/canvas_load_fallback/*.jsonl` 应仅有 `db_empty`（迁移前老数据）条目，无 `db_error`。
4. **回滚阶段**：`CANVAS_PRIMARY_WRITE=json` 重启即回退到 PR-6 行为；JSON 文件已被 DB 主写阶段的异步回写维持最新，无数据回退风险。
5. **禁止**：HTTP 不可修改此开关；只能通过环境变量 + 进程重启切换（P0 硬约束 #8）。

### 关联事实

- 新增 `app/db/canvas_writer.py`（`save_canvas_db(canvas: dict) -> None` DB 主写 + 乐观锁 `WHERE base_updated_at = ?` + `revision` 单调递增；`load_canvas_db(canvas_id) -> dict | None` DB 主读；`_async_write_json_fallback` 异步 JSON 回写走 `asyncio.run_in_executor` / `threading.Thread(daemon=True)` 两条路径；`CanvasConflictError(HTTPException)` `status_code=409` `detail={"message": "画布已被其他页面更新，已拒绝旧版本覆盖。"}` 与路由层 `main.py:16286` 冲突 message 键位字节等价；`_record_json_fallback_failure` 落 `data/shadow_diff/canvas_json_fallback/<yyyymmdd>.jsonl` 稳定键位 `(ts, domain, legacy_id, error, fallback_reason)`）。
- `app/stores/canvas_store.py:save_canvas` 增加 `_get_primary_write_mode("canvas")` 分派；`json` 分支 100% 保留 PR-6 行为（老 `_impl` + `_write_shadow_after_save` hook）；`db` 分支懒 import `app.db.canvas_writer`。`load_canvas` 同理分派；`db` 模式下 DB 命中直接返回，未命中 fallback 到 `main.load_canvas` 并落 `canvas_load_fallback/*.jsonl`（`fallback_reason={db_empty|db_error}`）。
- `app/shared/settings/runtime.py:Settings` 追加 `canvas_primary_write: str` 字段（29 → 30）+ `_validate_canvas_primary_write` 值域校验 `{"json","db"}`，其他值 `ValueError`；`get_settings()` mirror 到 `main.CANVAS_PRIMARY_WRITE`。
- `main.py` 追加 `CANVAS_PRIMARY_WRITE` 常量（紧邻 `SHADOW_WRITE_CANVAS`，走 PR-BE-03 "两步走"约定；默认 `"json"`）；**`save_canvas` 函数体（L3534-3538）零字节触碰**（AST byte-equivalent 断言承接数据 PR-6 契约）。
- 冻结区 AST 3/3（`class StorageSettings` / `def apply_storage_settings` / `storage_settings_snapshot`）继续 byte-equivalent 跨 8 PR 保持。
- 读/写路径独立：本 PR 不动 `app/shadow_read/` / `app/shadow_write/` 任何文件；三条链路各自扩展。
- **P0 抗回归**：`tests/db/test_canvas_writer.py::test_json_mode_default_does_not_import_canvas_writer` 断言 `CANVAS_PRIMARY_WRITE=json` 默认下 `sys.modules` 中**没有** `app.db.canvas_writer`；未来任何 subagent 在默认路径引入 DB 层拉起即视为违反"零开销 short-circuit"契约，直接 REJECT。`test_db_mode_primary_write_error_propagates` 用 monkeypatch 把 `get_engine` 换成 raise —— DB 主写失败必须原样上抛，禁止 fallback 到 JSON 主写（P0 硬约束 #4）。

归属：数据 PR-7（[[70 开发过程跟踪/PR 状态总账/PR - 数据模型#数据 PR-7]]）。

---

## 36. 3 类低风险 domain 主写机制运维手册（数据 PR-8，Wave 3-G §36）

**定位**：本段是**运维手册**，不是烟测通过条件。数据 PR-8 只交付 3 类低风险 domain（Project / PromptLibrary / WorkflowDefinition）"主写机制搭建 + 显式 DB 启用能力"，**默认全部为 JSON 主写**（`PROJECT_PRIMARY_WRITE=json` / `PROMPT_LIBRARY_PRIMARY_WRITE=json` / `WORKFLOW_DEFINITION_PRIMARY_WRITE=json`）。反转默认值（切 `db`）是独立运维动作 / 独立 PR，不在 PR-8 代码范围。

- 命令：
  - `python -m pytest tests/db/test_project_writer.py tests/db/test_prompt_library_writer.py tests/db/test_workflow_writer.py tests/shared/test_settings.py -v`
  - `python -c "from main import PROJECT_PRIMARY_WRITE, PROMPT_LIBRARY_PRIMARY_WRITE, WORKFLOW_DEFINITION_PRIMARY_WRITE; assert PROJECT_PRIMARY_WRITE == PROMPT_LIBRARY_PRIMARY_WRITE == WORKFLOW_DEFINITION_PRIMARY_WRITE == 'json', 'defaults must be json'"`
  - `python -c "from main import app; print('routes=', len(app.routes))"`
  - `python tools/openapi_diff.py --baseline tools/openapi_baseline.json`
- 期望：3 个新 writer 契约测试全绿（≥22 项 STRONG，含 sys.modules 隔离 / 集合级 UPSERT+DELETE 事务 / 异步 JSON 回写 / P0 密钥剪枝 AST+grep 双验证 / DB 主写失败上抛 / Settings 层 fail-fast）；`tests/shared/test_settings.py` 字段总数断言 30 → 33；`routes=167` 与基线一致；`openapi_diff` exit=0。

### 灰度切换操作手册（任一 domain 独立执行；DB 是 SQLite 单库）

1. **前置观察阶段**（24-48h，任一 domain 独立执行）：设置对应 `SHADOW_READ_<DOMAIN>=true` 开启只读双读（PR-4 已就位），观察 `data/shadow_diff/<domain>/*.jsonl` 应零异常条目；`python -m tools.data_reconcile <domain>` 摘要 `missing_in_db=[]`。
2. **对账阶段**：`python -m tools.data_reconcile <domain>` 严格检查 JSON snapshot 与 DB 行数一致；有任何 missing → 停止切换，先修根因。
3. **切换阶段**：设置 `<DOMAIN>_PRIMARY_WRITE=db` 后重启进程；观察 `data/shadow_diff/<domain>_json_fallback/*.jsonl` 应零条目（异步 JSON 回写全成功）。
4. **回滚阶段**：`<DOMAIN>_PRIMARY_WRITE=json` 重启即回退到 PR-4 行为；JSON 文件已被 DB 主写阶段的异步回写维持最新，无数据回退风险。
5. **禁止**：HTTP 不可修改此开关；只能通过环境变量 + 进程重启切换（P0 硬约束 #6）。

### 关联事实

- 新增 `app/db/project_writer.py`（`save_projects_db(projects: list[dict])` 集合级 UPSERT + DELETE 事务 + JSON 异步回写 + shadow diff 落 `data/shadow_diff/project_json_fallback/<yyyymmdd>.jsonl`；`load_projects_db()` DB 主读；D-1=B 决策下不做乐观锁，`updated_at` 仅作诊断）。
- 新增 `app/db/prompt_library_writer.py`（同上结构；D-2=B 决策：整个 `{active_library_id, libraries: [...]}` payload 全塞 `prompt_libraries.raw_json`；`prompt_items` 表 PR-8 **不主写**，M2 后续 PR 展平；`system/readonly/version` 语义由 `main.normalize_prompt_libraries` 承担字节等价）。
- 新增 `app/db/workflow_writer.py`（同上结构；**P0 密钥剪枝**：`raw_json` 深度剪除任何 `_is_sensitive_field` 匹配的字段——`api_key` / `access_token` / `secret` / `authorization` / `password` / `client_secret` / `env_file` / `dot_env` / 前缀/后缀匹配 `_SENSITIVE_AFFIXES` 清单；DB DELETE 仅清 `provider_id='runninghub'` 域，不误伤 builtin `file:*`；`prune_runninghub_workflow_store_for_provider` 通过 store facade 调用，`db` 模式下 prune 语义由集合级 DELETE 事务自动承接）。
- 3 个 store wrapper（`app/stores/project_store.py` / `prompt_library_store.py` / `workflow_store.py`）新增 `_get_primary_write_mode` 分派：`json` 分支 100% 保留 PR-4 行为（**必须**保证 `sys.modules` 无对应 `app.db.*_writer`，不构造 DB engine，不落 fallback 文件）；`db` 分支懒 import writer + JSON 异步回写。
- `main.py` 追加 3 行常量（紧邻 L369 `CANVAS_PRIMARY_WRITE`）：`PROJECT_PRIMARY_WRITE` / `PROMPT_LIBRARY_PRIMARY_WRITE` / `WORKFLOW_DEFINITION_PRIMARY_WRITE`，全部默认 `"json"`。**`save_projects` / `save_prompt_libraries` / `save_runninghub_workflow_store` 函数体零字节触碰**（byte-identical vs `ae50b28`）。
- `app/shared/settings/runtime.py:Settings` 追加 3 字段（30 → 33）+ 3 校验器 `_validate_project_primary_write` / `_validate_prompt_library_primary_write` / `_validate_workflow_definition_primary_write`；值域 `{"json","db"}` fail-fast；`tests/shared/test_settings.py` `FIELD_TO_MAIN_CONST` + 断言同步。
- **PR-7 P2 承接**：`tests/db/test_canvas_writer.py::test_db_mode_large_canvas_latency_p95_sampled` 改造为 N=20 次采样 + 排序取 P95（上界 baseline * 1.2）；`test_db_mode_e2e_fallback_diff_chain` 端到端触发 `_async_write_json_fallback → _write_json_fallback_sync → _record_json_fallback_failure` 链路（注入 IO 异常），断言 `data/shadow_diff/canvas_json_fallback/*.jsonl` 真实产生。
- 冻结区 AST 3/3（`class StorageSettings` / `def apply_storage_settings` / `def storage_settings_snapshot`）byte-equivalent 断言跨 9 PR 保持。`routes=167` 不变；OpenAPI baseline exit=0。
- **P0 抗回归**：3 个 `test_json_mode_default_does_not_import_*_writer` 分别断言 `PROJECT_PRIMARY_WRITE=json` / `PROMPT_LIBRARY_PRIMARY_WRITE=json` / `WORKFLOW_DEFINITION_PRIMARY_WRITE=json` 默认下 `sys.modules` 无对应 writer；未来 subagent 在默认路径引入 DB 层拉起即视为违反"零开销 short-circuit"契约，直接 REJECT。3 个 `test_*_db_mode_primary_write_error_propagates` monkeypatch `get_engine` raise → DB 主写失败必须原样上抛，禁止 fallback（P0 硬约束 #4）。`test_workflow_writer_raw_json_strips_provider_secrets` AST + 端到端 dump grep 双验证 provider 密钥零入 DB（P0 硬约束 #5）。

归属：数据 PR-8（[[70 开发过程跟踪/PR 状态总账/PR - 数据模型#数据 PR-8]]）。

---

## 附：OpenAPI baseline 差异校验

作为烟测辅助，任一 PR 合入前追加执行：

- `python tools/openapi_diff.py --baseline tools/openapi_baseline.json`
- 期望：`OK: baseline == current`，退出码 `0`。

若差异为合规扩展（新增可选字段 / 新增 error code），须在
[[2026-07-16 首批 PR 开工协调纲要]] "OpenAPI diff 登记" 章节追加一条。
