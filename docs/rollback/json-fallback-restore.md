# JSON 回退读通道下线判据 · 回滚剧本

**关联 PR**: 数据 PR-14（Wave 3-N.7 Batch 4 主线 B · 数据模型收官）
**开关**: `JSON_FALLBACK_READ` / `JSON_ASYNC_MIRROR`

---

## 场景 A：DB 主写异常，需要紧急恢复 JSON 回退读

```bash
# 1. 开启 JSON 回退读（立即生效，重启即恢复）
export JSON_FALLBACK_READ=on

# 2. 重启进程
#    按实际部署方式重启（uvicorn 热重载 / systemctl restart / docker restart）

# 3. 验证回退读生效
#    检查日志中是否有 JSON fallback read 命中记录
```

## 场景 B：DB 主写异常，需要暂停 DB 主写，切换回 JSON 主写

```bash
# 1. 按 domain 逐个暂停 DB 主写
export CANVAS_PRIMARY_WRITE=json
export PROJECT_PRIMARY_WRITE=json
export PROMPT_LIBRARY_PRIMARY_WRITE=json
export WORKFLOW_DEFINITION_PRIMARY_WRITE=json
export ASSET_LIBRARY_PRIMARY_WRITE=json
export HISTORY_PRIMARY_WRITE=json

# 2. 等待 5 个 domain 的静默期（确保所有 in-flight 写入完成）
#    建议等待 30 秒后观察日志确认无 DB 写异常

# 3. 重启进程
```

## 场景 C：DB 恢复后，逐个 domain 切回 DB 主写

```bash
# 1. 按 domain 逐个恢复 DB 主写
export CANVAS_PRIMARY_WRITE=db
# 验证 5 分钟后切下一个
export PROJECT_PRIMARY_WRITE=db
# 验证 5 分钟
export PROMPT_LIBRARY_PRIMARY_WRITE=db
# 验证 5 分钟
export WORKFLOW_DEFINITION_PRIMARY_WRITE=db
# 验证 5 分钟
export ASSET_LIBRARY_PRIMARY_WRITE=db
# 验证 5 分钟
export HISTORY_PRIMARY_WRITE=db

# 2. 重启进程
```

## 对账补齐

DB 恢复后，对每个 domain 执行对账补齐，确保 JSON 回退期间写入的变更已同步到 DB：

```bash
# 对账补齐（需先启动主进程，确保 DB 引擎已就绪）
python main.py data-reconcile canvas
python main.py data-reconcile project
python main.py data-reconcile prompt_library
python main.py data-reconcile workflow_definition
python main.py data-reconcile asset_library
python main.py data-reconcile generation_history
```

> **注意**：`data-reconcile` CLI 需主进程启动后执行（DB 引擎依赖 `get_engine()` 初始化）。
> 对账补齐是幂等操作，可重复执行。

## 场景 D：关闭异步镜像写（停止 JSON 回退文件写入）

```bash
# 关闭 JSON 异步镜像写（DB 主写正常，但不再写 JSON 回退文件）
export JSON_ASYNC_MIRROR=off

# 重启进程
```

## 开关参考

| 开关 | 默认值 | 作用 | 生效方式 |
|------|--------|------|----------|
| `JSON_FALLBACK_READ` | `off` | DB 读失败时是否回退到 JSON 文件 | 进程重启 |
| `JSON_ASYNC_MIRROR` | `off` | DB 写成功后是否异步写 JSON 镜像 | 进程重启 |
| `CANVAS_PRIMARY_WRITE` | `db` | Canvas 主写模式 | 进程重启 |
| `PROJECT_PRIMARY_WRITE` | `db` | Project 主写模式 | 进程重启 |
| `PROMPT_LIBRARY_PRIMARY_WRITE` | `db` | PromptLibrary 主写模式 | 进程重启 |
| `WORKFLOW_DEFINITION_PRIMARY_WRITE` | `db` | WorkflowDefinition 主写模式 | 进程重启 |
| `ASSET_LIBRARY_PRIMARY_WRITE` | `db` | AssetLibrary 主写模式 | 进程重启 |
| `HISTORY_PRIMARY_WRITE` | `json` | GenerationHistory 主写模式 | 进程重启 |