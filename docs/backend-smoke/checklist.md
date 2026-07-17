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

---

## 附：OpenAPI baseline 差异校验

作为烟测辅助，任一 PR 合入前追加执行：

- `python tools/openapi_diff.py --baseline tools/openapi_baseline.json`
- 期望：`OK: baseline == current`，退出码 `0`。

若差异为合规扩展（新增可选字段 / 新增 error code），须在
[[2026-07-16 首批 PR 开工协调纲要]] "OpenAPI diff 登记" 章节追加一条。
