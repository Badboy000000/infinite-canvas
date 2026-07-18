# CodeGraph 使用教程（仓库内速查版）

> **完整版**：Obsidian 知识库 `00 索引与规范/CodeGraph 使用规范与 Obsidian 配合指南.md`
> **本文用途**：仓库内速查、给团队 / 未来的自己一个不依赖 Obsidian 就能上手的入口

## 一、CodeGraph 是什么

[CodeGraph](https://github.com/colbymchenry/codegraph) 是一个本地的**代码知识图谱**：

- 用 tree-sitter 解析代码，建立符号、调用、依赖的关系图
- 存在项目根目录的 `.codegraph/codegraph.db`（SQLite）
- 通过 MCP 暴露给 Claude Code / Cursor / Codex 等 AI Agent

它是 Obsidian 知识库的搭档：

| 图谱 | 内容 | 谁在维护 |
|------|------|---------|
| **Obsidian 知识库** | 规范、架构、决策、实施计划 | 人 + Agent 协作维护 |
| **CodeGraph** | 代码事实：符号 / 调用 / 依赖 / 影响面 | 工具自动生成，随代码同步 |

## 二、一次性的全局安装（本机已完成）

```bash
# 需要 Node（本机通过 fnm 管理，默认 v22.22.3）
npm i -g @colbymchenry/codegraph

# 验证
codegraph --version   # 期望输出 >= 1.4.1
```

## 三、一次性的全局 MCP 配置（本机已完成）

`C:\Users\lwj\.claude.json` 顶层 `mcpServers`：

```json
{
  "mcpServers": {
    "codegraph": {
      "type": "stdio",
      "command": "codegraph",
      "args": ["serve", "--mcp"]
    }
  }
}
```

`C:\Users\lwj\.claude\settings.json` 顶层 `permissions`：

```json
{
  "permissions": {
    "allow": [
      "mcp__codegraph__*"
    ]
  }
}
```

配好后，任何项目里的 Claude Code 会话都能自动调用 CodeGraph，不再弹窗询问。

## 四、每个新项目的接入步骤

```bash
cd /path/to/your-project
codegraph init          # 一次性建立索引
codegraph status        # 查看统计
```

`.codegraph/` 目录会自带一份 `.gitignore`，**不会**被提交到仓库。索引之后 CodeGraph 会通过文件监听自动增量同步。

## 五、日常命令备忘

| 命令 | 用途 |
|------|------|
| `codegraph status` | 查看当前项目索引状态 |
| `codegraph sync` | 手动增量同步（一般不用，自动的） |
| `codegraph index` | 全量重建索引（结构大改后可用） |
| `codegraph query <keyword>` | 命令行搜符号 |
| `codegraph explore <query>` | 命令行版 `codegraph_explore` |
| `codegraph callers <symbol>` | 谁在调用它 |
| `codegraph callees <symbol>` | 它调用了谁 |
| `codegraph impact <symbol>` | 改这个符号的影响面 |
| `codegraph uninit` | 移除本项目的 `.codegraph/` |

## 六、Agent 应该怎么用

**核心原则**：项目里有 `.codegraph/` 时，Agent 优先用 `mcp__codegraph__codegraph_explore` 而不是 `Read` / `Grep` 去理解代码。

已在以下位置沉淀规则：

- 全局：`C:\Users\lwj\.claude\CLAUDE.md`（对所有项目生效）
- 本项目：`E:\projects\Infinite-Canvas\CLAUDE.md`（"CodeGraph — Local Code Intelligence" 章节）

**你（用户）不需要记这些命令**——只要让 Claude 处理代码任务，它会自己按规则决定何时查 CodeGraph、何时读 Obsidian、何时改代码。

## 七、故障排查

| 现象 | 处理 |
|------|------|
| `codegraph: command not found` | 检查 fnm 当前 Node 是否激活；重新 `npm i -g @colbymchenry/codegraph` |
| Agent 一直在用 Grep 不用 CodeGraph | 检查项目根目录是否有 `.codegraph/`；检查全局 `CLAUDE.md` 是否被覆盖 |
| MCP 每次都要授权 | 检查 `~/.claude/settings.json` 的 `permissions.allow` 是否包含 `mcp__codegraph__*` |
| CodeGraph 返回过期文件警告 | 对提示的文件用 `Read` 拿最新内容；或跑 `codegraph sync` |
| `.codegraph/` 被 git 追踪 | 检查 `.codegraph/.gitignore` 是否存在且内容为 `*` + `!.gitignore` |

## 八、当前项目索引概况

```
Files:     167  (python 121 / javascript 46)
Nodes:     6,739
Edges:     26,769
```

（数字会随代码变化，以 `codegraph status` 为准。）

## 九、参考

- [GitHub - colbymchenry/codegraph](https://github.com/colbymchenry/codegraph)
- [npm - @colbymchenry/codegraph](https://www.npmjs.com/package/@colbymchenry/codegraph)
- Obsidian 完整版教程：`00 索引与规范/CodeGraph 使用规范与 Obsidian 配合指南.md`
