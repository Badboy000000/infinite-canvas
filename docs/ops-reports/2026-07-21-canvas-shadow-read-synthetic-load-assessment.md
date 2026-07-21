# 2026-07-21 Canvas shadow_read 就绪度合成负载评估报告（synthetic load · 非真实生产观察）

> **警示 · 这不是真实生产观察 · 是合成负载就绪度评估**
> 本报告的一切数字均由 `tools/synth_shadow_read_probe.py` 在**独立 tmp
> workspace** 里通过合成 mock canvas + 独立 SQLite + 独立 shadow_diff 目录
> 采出。**未启动**过 FastAPI 服务、**未触发**过真实用户 canvas save/load。
> 报告用途：作为 Wave 3-K 数据 PR-10（`CANVAS_PRIMARY_WRITE=db` 显式启用）
> 前的**就绪度事实依据**，替代 Wave 3-J 主线 C 从未真正启动的"24-48h 真实
> 使用观察"。

- **状态**：初次采样 · **YELLOW · 有条件放行 db 主写**
- **命名**：`synthetic load` · `readiness evaluation` · `NOT production observation`
- **对齐**：Wave 3-J 收官编年史"主线 C 订正说明"段落 · CB-P5-08 候选登记
- **产出工具**：`tools/synth_shadow_read_probe.py`（新增 · 本波交付）
- **抗回归测试**：`tests/ops_readiness/test_canvas_shadow_synthetic_probe.py`（新增 · T80-T89 · 9 passed + 1 skipped）

## 0 · 环境事实核查（Wave 3-J 编年史订正段的现场复核）

| 事实 | 观测 |
|---|---|
| `data/canvas/` 目录 | **不存在** |
| `data/canvas/*.json` 数量 | **0**（无真实 canvas 数据集） |
| `data/canvases/` 目录 | 存在（老 canvas 目录 · runtime 使用） |
| `data/canvases/*.json` 数量 | **0**（也是空的） |
| `data/app.db` 文件 | 存在 |
| `data/app.db::canvases` 表 | **不存在**（shadow_read 无对账基线可读） |
| `data/shadow_diff/canvas/` 目录 | 存在（骨架） |
| `data/shadow_diff/canvas/*.jsonl` 数量 | **1** 文件（`20260719.jsonl` · 单条 request_id=`test` · Wave 3-H 测试残留） |

结论：**Wave 3-J 主线 C 编年史订正段 3 项事实 100% 复核成立** —— 生产环境
真实 canvas 使用为**零**，`SHADOW_READ_CANVAS=true` 若启动也会立即以"DB
表不存在 → `_load_db_snapshot` 返 `{}`"路径退化，跑出的 shadow diff 会把
所有 JSON 项算 `missing_in_db`——但因为**连 JSON 都没有**，实际不会有
任何 diff 记录写入。这解释了"Wave 3-J 主线 C 从未产生任何真实事件"。

## 1 · 合成负载配置（可重现）

- 生成器：`python -m tools.synth_shadow_read_probe --scale=50 --output=<path>`
- 随机种子：`--seed=1337`（默认 · 保证可重现）
- 合成 canvas 数量：**50**（`--scale`：允许 10 / 50 / 200 / 500）
- 每 canvas 内容：随机 5-30 nodes + 5-30 connections + 随机 kind/pinned/revision
- 场景 A/B load 次数：100
- 场景 C save 次数：200
- 场景 D shadow_write 锁竞争迭代：3
- 独立 workspace：`tempfile.mkdtemp(prefix="synth_probe_")` · 全局 cleanup

## 2 · 四场景实测数据表（scale=50 · seed=1337）

### 2.1 场景 A · 命中率（N 双写 → 100 次随机 load）

| 指标 | 目标 | 实测 |
|---|---|---|
| `db_inserted` | 50 | **50** |
| `hit_rate`（`missing_in_db` 全空占比） | ≥ 0.99 | **1.0** |
| `records_with_missing_in_db_nonempty` | 0 | **0** |
| `records_with_missing_in_json_nonempty` | 0（理想） | **100**（结构非对称 · P2 观察项 · 详见 §4） |
| `field_diff_count_stats.mean` | 0（理想） | **2.0**（`created_at` / `updated_at` 类型转换 · 既知 · P3 · 详见 §4） |
| `load_latency.p50_ms` | — | **1.659** |
| `load_latency.p95_ms` | ≤ 20（治理方案 §PR-4/5 硬约束） | **2.05** |
| `load_latency.p99_ms` | — | **3.127** |
| `load_latency.max_ms` | — | **8.464** |
| **verdict** | PASS | **PASS** |

### 2.2 场景 B · 差异率（N JSON 全写 · DB 90% · 100 次随机 load）

| 指标 | 目标 | 实测 |
|---|---|---|
| `db_inserted` | 45 | **45** |
| `missing_ids_count` | 5 | **5** |
| `loads_landed_on_missing`（随机命中 missing 分区） | ~10 | **6** |
| `expected_diff_rate` | — | **0.06** |
| `observed_diff_rate` | ≈ `expected_diff_rate` | **0.06** |
| `delta_vs_expected` | ≤ 0.05 | **0.0** |
| **verdict** | PASS | **PASS** |

### 2.3 场景 C · 写入耗时（`SHADOW_WRITE_CANVAS=true` · 200 次 save_canvas）

| 指标 | 目标 | 实测 |
|---|---|---|
| `saves_attempted` | 200 | **200** |
| `saves_bubbled_error` | 0 | **0** |
| `latency_ms.p50_ms` | — | **12.514** |
| `latency_ms.p95_ms` | ≤ 500（治理方案 §PR-6 P1 硬约束） | **15.302** |
| `latency_ms.p99_ms` | — | **18.068** |
| `latency_ms.max_ms` | — | **53.692** |
| **verdict** | PASS | **PASS** |

### 2.4 场景 D · 事务失败率（sqlite `BEGIN EXCLUSIVE` 持锁 · shadow write fail-safe）

| 指标 | 目标 | 实测 |
|---|---|---|
| `iterations` | 3 | **3** |
| `saves_bubbled_exception` | 0（P0 硬约束：shadow write 异常不上抛） | **0** |
| `saves_completed_no_exception` | 3 | **3** |
| `json_primary_write_files_actually_updated` | 3（主路径与 DB 解耦） | **3** |
| `shadow_write_failure_records_logged` | ≥ 1（内部 warning 落 shadow_diff） | **3** |
| `per_iter_latency_ms` (max) | — | **~5300**（**P1 观察项** · 详见 §4） |
| **verdict** | PASS | **PASS** |

## 3 · 与 M1 阶段"5 domain 具备切换能力"的差距分析

M1 目标：5 个 domain (`project` / `provider_config` / `prompt_library` /
`workflow_definition` / `canvas`) 全部达到"`<DOMAIN>_PRIMARY_WRITE=db`
可显式启用"。

| domain | primary_write=db 状态 | 就绪度证据 |
|---|---|---|
| `project` | 数据 PR-8 已合入 | ✅ 有验证 |
| `provider_config` | 待 Wave 3-K/L 数据 PR-11 | — |
| `prompt_library` | 待 Wave 3-K/L 数据 PR-12 | — |
| `workflow_definition` | 待 Wave 3-K/L 数据 PR-13 | — |
| `canvas` | **本报告评估目标** | **YELLOW · 有条件放行** |

canvas 差距：

1. **合成 vs 真实**：合成负载不模拟并发写、不模拟 UI 侧真实用户操作节奏、
   不模拟长活跃 canvas 的连续 revision 递增。
2. **锁竞争幅度**：场景 D 用极端 `BEGIN EXCLUSIVE` 逼真度中等；真实 DB
   竞争多为短事务，shadow_write 触碰上锁概率远低于合成场景。
3. **数据量**：scale=50 只覆盖小样本；scale=200/500 未在本次执行（探针
   支持 · 需时长 30s+/90s+ · 归档在 `tests/ops_readiness/test_..._T88/T89`）。

## 4 · 观察到的 shadow_read/shadow_write 层异常（CB-P5-08 候选）

**统一登记编号**：**CB-P5-08**（Wave 3-J 编年史指定编号池）

### 4.1 P1 · DB 锁竞争下 `save_canvas` 每次 stall ~5s（`busy_timeout` PRAGMA 语义）

- **触发场景**：场景 D · sqlite `BEGIN EXCLUSIVE` 持锁 3 iter
- **实测**：`per_iter_latency_ms = [5308, 5297, 5287]` ms
- **根因**：`app/db/engine.py` 注入 `PRAGMA busy_timeout = 5000`。
  shadow_write 在 DB 被锁定时阻塞到 busy_timeout 才 raise
  `OperationalError`；`canvas_store.save_canvas` 的 `_write_shadow_after_save`
  hook 捕获异常仅 warning（fail-safe 契约成立），但此时**墙钟时间已过 5s**。
- **CANVAS_PRIMARY_WRITE=json 模式的影响**：可接受（异常不冒泡，主路径
  JSON 主写成功；仅 shadow_write 慢）。但用户可见 API 响应也会被拖到 5s+。
- **CANVAS_PRIMARY_WRITE=db 模式的影响**：**用户可见回归风险显著** ——
  DB 主写会直接被 5s 锁阻塞，无 JSON 主写兜底。任何真实并发场景（`save_canvas`
  同一 legacy_id 两个用户几乎同时提交）都可能触发。
- **建议 Wave 3-K 承接**：
  - db 主写切换前：把 `canvas_writer` 的 `busy_timeout` 降到 500-1000ms
  - 增加 SLI/SLO 观察项：`canvas_writer.save_canvas_db` p95 / p99 wall-time
  - 或者引入短事务重试逻辑替代 `busy_timeout` 阻塞
- **CB 编号建议**：CB-P5-08a · severity P1 · title "DB 锁竞争下 canvas save P99 显著劣化"

### 4.2 P2 · shadow_read canvas normalizer 与 DB snapshot 结构非对称

- **触发场景**：场景 A · scale=50 · 100 次 load 全部记录 `records_with_missing_in_json_nonempty == 100`
- **根因**：`app/shadow_read/runner.py:_normalize_json_canvas` 只返回
  `{loaded_id: {...}}` 单元素 dict（因为 `load_canvas(canvas_id)` 语义就是
  单 canvas 读）；而 `_load_db_snapshot` 返回**整表** rows。所以：
  ```
  missing_in_json = set(db_snapshot) - set({loaded_id})
                  = 其它 49 个 canvas 全部
  ```
- **canvas 域独有**：其它 4 个 domain 的 `load_*()` 都是整集合返回
  （`load_projects()` / `load_prompt_libraries()` / …）。canvas 是唯一
  "单 id 读"的域。
- **影响**：不算数据丢失，但会给运维观察增加 O(N) 噪声——每次 load 都会
  产生 `missing_in_json = [<所有其它 canvas>]` 的 diff jsonl 记录，alert
  信噪比很低。
- **建议 Wave 3-K 承接**：
  - shadow_read layer 增加 `load_scope=single_id` 语义：canvas 域 single-id
    load 时只比对**同一 legacy_id**的字段级差异
  - 或者：`_load_db_snapshot("canvas", filter_legacy_id=<loaded_id>)` 只
    从 DB 拿目标那一行
- **CB 编号建议**：CB-P5-08b · severity P2 · title "canvas 域 single-id load shadow_read 全表 missing_in_json 噪声"

### 4.3 P3 · `created_at` / `updated_at` 类型转换稳定触发 `field_diffs`

- **触发场景**：场景 A · `field_diff_count_stats.mean = 2.0`（就是这两个字段）
- **既知**：已在 `tests/shadow_read/test_canvas_shadow.py:test_shadow_enabled_no_diff_when_db_matches`
  的 docstring 中承认此行为。JSON epoch-ms int vs DB `DateTime` ISO 字符串。
- **运维影响**：field_diffs 会被真实运维监控当成"字段级差异"，需要在报警规则
  里过滤掉 `field in {"created_at", "updated_at"}`。
- **建议 Wave 3-K 承接**：
  - 或者在 shadow_read `_project_db_row_to_stable` 把 `_iso(datetime)` 换成
    epoch-ms 输出（与 JSON 侧对齐）
  - 或者在 diff 层过滤"已知类型漂移"字段
- **CB 编号建议**：CB-P5-08c · severity P3 · title "shadow_read canvas 域 created_at/updated_at 类型漂移常态触发"

## 5 · 就绪度结论

**YELLOW · 有条件放行 CANVAS_PRIMARY_WRITE=db 主写**

理由：

- 全 4 场景 verdict = **PASS**
- **无 P0 观察项**（save_canvas fail-safe 契约成立 · JSON 主写与 DB 完全解耦）
- 但存在 1 项 **P1 观察项**（4.1 · DB 锁竞争下 5s stall），**db 主写切换前必须先修**
- P2/P3 观察项建议随 db 主写切换一并承接，但不阻塞放行

**放行条件**（Wave 3-K 数据 PR-10 上马前必须完成）：

1. 修 P1 · 4.1：降低 `busy_timeout` 或引入短事务重试逻辑
2. 补一次 scale=200 或 scale=500 的合成负载复采（探针已支持）
3. 建议一次真实生产观察窗口（哪怕 4-8h）· 详见 §6

## 6 · 后续真实生产观察窗口的启动步骤建议

### 6.1 数据前置（必须）

- 生产 DB 迁移一次：`python -m app.db.engine migrate head`（建 `canvases` 表）
- 数据导入一次：`python -m app.data_import canvas`（把 `data/canvases/*.json`
  导入 DB）—— 但当前 `data/canvases/*.json` 也是 **0** 个文件，说明本机
  从未真正打开过 canvas。用户需要先真实打开一个 canvas 走一次 `save_canvas`
  才能有数据。

### 6.2 env 设置（推荐窗口配置）

```bash
export SHADOW_READ_CANVAS=true      # 开启 shadow read
export SHADOW_WRITE_CANVAS=true     # 开启 shadow write（PR-9 起可用）
export CANVAS_PRIMARY_WRITE=json    # **不切主写** · 观察阶段仅副本
```

### 6.3 窗口时长

- Wave 3-J 编年史订正段建议 24-48h · 本报告改为**先跑合成 → 再跑真实 4-8h 短窗口**
- 目的：验证 P1 观察项修复后的真实 stall 分布

### 6.4 监控埋点

- `data/shadow_diff/canvas/<yyyymmdd>.jsonl` 每 8-12h grep 一次 `missing_in_db`
  + `missing_in_json` 分布（本报告 §4.2 的噪声必须先过滤）
- `logging.getLogger("app.shadow_write.runner")` 的 warning 数 / hr
- `logging.getLogger("app.stores.canvas_store")` 的 `load_canvas fallback_hit`
  warning 数 / hr（只在 db 主写模式产生）

### 6.5 观察窗口结束后回写

- 补一份 `docs/ops-reports/<date>-canvas-shadow-read-real-observation.md`
  （**真实生产观察** · 与本报告的合成负载差异）
- KB 侧：Wave 3-K 编年史追加"真实观察窗口结果"段落

## 7 · 未覆盖面 / 局限

- 合成 canvas 不模拟真实用户节奏（真实场景中两次 save 间可能间隔数秒或数分钟）
- 未测试并发多进程 save（`main.CANVAS_LOCK` 是进程内 Lock，多 worker 场景未覆盖）
- 未测试 canvas 内包含大量 base64 图片资源的极端 payload（合成 canvas 每个 ~3KB）
- 未测试 canvas revision 从 0 递增到高值的长活跃场景
- Windows-only（本机环境）· Linux/macOS 下 sqlite busy_timeout 与
  文件系统 fsync 语义可能不同
- 未与 `data_reconcile.py` 联跑（CB-P5-04 Windows GBK UnicodeEncodeError
  阻塞 · 已单独在编年史登记）
- **本报告零真实用户 canvas** · scale=50/100 都是合成，与真实用户 canvas
  的结构、大小、革命次数分布可能不匹配

## 8 · 引用

- 编年史：[[70 开发过程跟踪/开发编年史/2026-07-21 Wave 3-J 收官编年史]] §主线 C 订正说明
- 上一版报告（scaffold · 未填数字）：`docs/ops-reports/2026-07-21-canvas-shadow-read-first-observation.md`
- 探针源码：`tools/synth_shadow_read_probe.py`
- 抗回归测试：`tests/ops_readiness/test_canvas_shadow_synthetic_probe.py`（T80-T89）
- shadow_read 实现：`app/shadow_read/runner.py`
- shadow_write 实现：`app/shadow_write/runner.py`
- canvas_store facade：`app/stores/canvas_store.py`
- 治理方案：[[30 治理方案/数据模型治理方案.md]]

## 9 · 版本

- 2026-07-21 首版 · Wave 3-K 前置就绪度评估工作 subagent 交付 · scale=50 seed=1337
- **本报告是 subagent 交付事实 · 未 commit · 交付给 Lead 白名单 commit**（Wave 3-J GM-12 交付边界硬约束）
