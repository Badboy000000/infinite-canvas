# Infinite Canvas · tools/ 使用说明

本目录集中放置所有开发/交付/治理相关的一次性脚本。每个脚本都遵循：

- **纯 Python 3，可独立运行**，不依赖第三方包（除非目录内 `README` 单独说明）
- **默认 dry-run**，加 `--apply` 才写盘/改仓库
- **UTF-8 输出**（自动 reconfigure，Windows GBK 终端也不乱码）
- **Exit code 有含义**（0 = 一致 / 通过；1 = 内容有差异；2 = 缺文件；3 = 参数错）

Agent 项目规则文件（`AGENTS.md` / `CLAUDE.md` / `.trae/rule.md`）**只列出触发条件和脚本名**，具体执行细节都在本 README。这样规则文件保持精简，模型 attention 不会被稀释。

---

## 分类速查

| 脚本 | 触发场景 | 默认动作 | 详细章节 |
|---|---|---|---|
| `check_env.py` | 会话开始 / 换机器 / 换 shell | 检查 Obsidian / CodeGraph / Node 等前置 | [环境前置](#环境前置) |
| `check_agent_configs.py` | 修改任一 Agent 规则文件后 | dry-run（比对三份 + strip CRLF） | [Agent 规则一致性](#agent-规则一致性) |
| `sync_agent_configs.py` | 修改 `docs/agent-protocol/base.md` 后 | dry-run（展示差异） | [Agent 规则同步](#agent-规则同步) |
| `check_delivery_closure.py` | 收官前 / 标记 PR merged 前 | 检查 HEAD 已推 + 工作树状态 | [Git 交付闭环](#git-交付闭环) |
| `cleanup_test_artifacts.py` | 跑完测试/烟测/curl 验证后 | dry-run（列出将删除） | [测试残留清理](#测试残留清理) |
| `openapi_snapshot.py` / `openapi_diff.py` | 后端接口治理 PR 前后 | 见脚本 `--help` | 见知识库 `40 实施计划/` 后端专题 |
| `migrate_identity_bootstrap.py` | 权限治理 PR 相关 | 见脚本 `--help` | 见知识库权限专题 |

---

## Agent 规则一致性

`AGENTS.md`（Codex）、`CLAUDE.md`（Claude Code）、`.trae/rule.md`（Trae）三份 Agent 项目规则必须**内容全文一致**，仅换行符差异视为等价（AGENTS/CLAUDE 是 CRLF、Trae 是 LF）。

```bash
python tools/check_agent_configs.py              # 检查
python tools/check_agent_configs.py --verbose    # 检查 + 打印完整 unified diff
```

- Exit 0：三份内容一致
- Exit 1：内容有差异（修改任一份后忘同步另外两份是最常见原因）
- Exit 2：缺少某份文件

**规则出处**：知识库 `10 架构基线/技术开发规则与工程实施规范.md` §"规则落地记录"。

已挂 `.git/hooks/pre-commit`，只要三份不一致就无法提交。

---

## Agent 规则同步

三份规则的**唯一来源**是 `docs/agent-protocol/base.md`。修改规则的唯一正确路径：

```bash
# 1. 编辑 base
$EDITOR docs/agent-protocol/base.md

# 2. 同步生成三份
python tools/sync_agent_configs.py               # dry-run，看差异摘要
python tools/sync_agent_configs.py --apply       # 实际写入

# 3. 复核（pre-commit 也会跑）
python tools/check_agent_configs.py
python tools/sync_agent_configs.py --check       # exit 1 表示三份与 base 不一致
```

**为什么这样设计**：规则越来越多、每份文件越来越长，模型 attention 被稀释，"漏改一份"变成必然错误。把三份变成从单一源生成的产物，`base.md` 是唯一需要维护的文件；pre-commit 兜底"手滑绕过生成器直接改 target 三份之一"。

---

## 测试残留清理

任何跑过测试、烟测、契约测试、`curl` 验证后，**必须**跑一次清理，回到"只有正式代码"的状态：

```bash
python tools/cleanup_test_artifacts.py           # dry-run，列出将删除
python tools/cleanup_test_artifacts.py --apply   # 实际删除
git status                                        # 应只显示预期的正式改动
```

**脚本覆盖的类别**（详见脚本头部注释）：

1. **Python 缓存**：递归 `__pycache__/`、`*.pyc/.pyo`、根 `.pytest_cache/`
2. **顶层临时字母目录**：`X/` / `Y/` / `Z/`（仅当为空时删除）
3. **烟测数据污染**：`data/api_providers.json` 中 `id` 以 `__smoke` 开头的 provider；`data/canvases/*.json` 中 `title` 以 `__smoke` 开头或恰为 `smoke` 的画布
4. **空的烟测输出目录**：`output/input/` / `output/output/`（仅当为空时删除）

**脚本不触碰**：`API/.env*`、`app/`、`docs/`、`tests/`、`tools/`、`static/`、`packages/`、`assets/`、`workflows/`、`data/` 内除上述两处以外的一切。

**扩展规则**：

- 新增一类测试残留（新的临时目录/新的 smoke fixture 模式），**在同一个 commit 里扩展本脚本**，不要留 "please clean up manually" 给下一个 Agent
- 如果真实文件不小心撞上 smoke 模式，重命名文件，不要弱化模式匹配
- `.gitignore` 已排除缓存类，脚本清理仍然必要——`git status` 要对协作方保持干净可读
- Subagent 跑测试后，**自己**跑清理再报完成；Lead 用 `git status` 复核

**规则出处**：知识库 `10 架构基线/技术开发规则与工程实施规范.md` §"Test Artifact Hygiene"（历史条款；现已整体迁移到本 README，规则文件只保留触发条件）。

---

## Git 交付闭环

（Phase 4·A 承接）由 `tools/check_delivery_closure.py` 检查"当前本地 HEAD 是否已推送到远程 / commit hash 已在知识库回写"。规则文件里只保留一句触发条件；具体条款和历史记录见知识库 `10 架构基线/技术开发规则与工程实施规范.md` §"Git 交付闭环"。

---

## 环境前置

（Phase 4·C 承接）由 `tools/check_env.py` 检查 Obsidian 知识库路径、CodeGraph 索引、fnm/Node 版本等前置条件；规则文件里只保留触发条件。

---

## 新增脚本的规范

如果你新增一个 `tools/xxx.py`：

- 头部注释按现有脚本的结构（用途、用法、Exit code、设计选择）
- Windows UTF-8 兜底放在 import 段落
- 默认 dry-run，`--apply` 才写盘
- 更新本 README 的"分类速查"表
- 如果规则相关，把触发条件加进 `docs/agent-protocol/base.md`（一行触发 + 脚本名 + 后果），细节写在本 README
- 如果是硬约束，考虑挂进 `.git/hooks/pre-commit`
