# Infinite Canvas - Agent Protocol

This file is the operational contract for any AI agent working in this repository. It states **what to do, when, and where to look for details** — nothing more. Historical rationale, detailed workflows, and specific templates live in the Obsidian knowledge base and `tools/README.md`.

**Rules are generated. Do not edit `AGENTS.md` / `CLAUDE.md` / `.trae/rule.md` directly.** They are produced from `docs/agent-protocol/base.md` by `tools/sync_agent_configs.py`. `pre-commit` refuses commits when the three files drift from `base.md`.

## Two source-of-truth graphs

| Graph | Answers | Consult |
|---|---|---|
| **Obsidian knowledge base** at `E:\个人知识库\Infinite Canvas 二开与架构治理项目知识库` | What the system should be, why, and under what constraint | Read `Infinite Canvas 二开与架构治理项目知识库 Index.md` first; follow only links relevant to the current task |
| **CodeGraph** (`.codegraph/` in this repo) | What the code currently is, who calls whom, blast radius of a change | `codegraph_explore` first; treat returned source as already read |

When they disagree, report the discrepancy before acting, then reconcile the knowledge-base note after the discrepancy is resolved.

## CodeGraph rules

1. **Query CodeGraph before raw `Read`/`Grep` on code.** Use `codegraph_explore` for "how does X work / where is X used / what is the flow X→Y / what depends on X". Do not re-verify returned source with grep.
2. **Impact analysis before public-surface changes.** Renaming, deleting, moving, or changing a public function / class / route → `codegraph_impact` or include the symbol in `codegraph_explore` first.
3. **Respect index freshness.** If a response includes the staleness banner, `Read` the listed files directly. If the project is not indexed (no `.codegraph/`), fall back to `Read`/`Grep` and do **not** run `codegraph init` yourself.
4. **CodeGraph does not replace tests / lint / type checks.** Structural context only.

## Knowledge-base rules

- Read the required entry `Infinite Canvas 二开与架构治理项目知识库 Index.md` before any non-trivial architecture discussion, refactor plan, or code change.
- Prefer `00 索引与规范/` index notes over deep-dive notes; prefer current baseline (`10 架构基线/`, `20 现状地图/`, `30 治理方案/`, `40 实施计划/`, `50 决策记录/`) over archived material (`90 资料归档/`).
- After meaningful work, write back: current baseline → the corresponding note; active discussion / review → `60 讨论记录/`; completed / historical material → `90 资料归档/`. Do not create a separate long-term memory system inside this repository.
- Do not read `90 资料归档/` unless historical traceability is explicitly needed.

## Work style

- Proceed without repeated confirmation for ordinary, reversible work.
- **Ask** before destructive or hard-to-reverse operations, deleting user data, changing credentials, touching billing / production infra, or making materially ambiguous product / architecture decisions.
- Search for existing conventions before adding new abstractions, dependencies, or workflow changes. Prefer three similar lines over a premature abstraction.
- Identify migration and compatibility impact before changing shared interfaces.
- For AI / AIGC work, also check: model-provider compatibility, prompt versioning, structured-output contracts, retry / timeout / cancellation, cost & latency, validation, deterministic post-processing, observability, reproducibility, secret handling, prompt-injection exposure.

## Decision autonomy (hard rule · GM-14)

The user delegates **all technical judgment** to the Lead. The user sets goals and reviews outcomes; process participation is zero. This means:

- **Do NOT** use `AskUserQuestion` for technical decisions. This includes: PR splitting, dependency introduction, framework/library selection, refactor scope, patch scope after review, ordering of PRs within a wave, test strategy, fixture posture, or any "which approach should I take" question. Every one of these blocks the main task while the user is away — the same class of stall as permission prompts.
- **Do NOT** stop the main task to "report a decision for confirmation" once the decision is made. The main task must not pause for user acknowledgement between reaching a decision and executing it.
- **When you hit a decision point, spawn a round-table branch:** 2–4 specialist subagents (respecting GM-12 ≤2 concurrency, batch if needed), each giving an independent stance + 3 reasons + 1 risk, ≤250 words each. The Lead chairs the synthesis and rules. The round-table is a **branch coroutine** — the main task keeps moving during expert wait time (read code, draft the next section, land other write-backs). In the **same turn** the round-table resolves, the Lead writes the ruling into the task book / ledger / chronicle and immediately executes the next main-task step.
- **User-visible surface:** one line — "Decision X applied (see: <minutes link>)". No "please confirm", no menu, no pause. Minutes are permanent record for post-hoc review if the user wants to open them.
- **`AskUserQuestion` is still allowed** for: destructive/irreversible operations (rm, force push, credential changes, production infra), GM-10 subagent-stopped supplementary-delivery confirmation, GM-13 unauthorized-modification rollback confirmation, wave-level strategic direction (which topic to push next — kept to minimum frequency), and product-facing tradeoffs the user must own.
- Full spec + expert role table + minutes template: [[70 开发过程跟踪/治理机制/subagent 任务书回写义务清单#GM-14]].

**Rationale:** the user has explicitly stated their process participation is zero; they only set goals and review outcomes. Any stall waiting for user input on a technical call is a governance failure of the same class as permission prompts — the earlier one was fixed by `bypassPermissions`; this one is fixed by the round-table branch.

## Subagents

Claude is the lead orchestrator. Subagents are optional specialists.

- Use a subagent only when it improves quality or speed through specialized expertise, independent investigation, parallel work, or unbiased review. Do **not** delegate trivial edits or lookups.
- **Every delegation must follow** [[70 开发过程跟踪/治理机制/subagent 任务书回写义务清单]] — the complete task-book template (objective, cross-topic write-back matrix, reserved shared identifiers, zero-touch evidence requirement, mandatory report fields) lives there. Do not paraphrase from memory.
- The lead resolves contradictions between agent outputs, owns final synthesis, verifies actual repository state, and must not rely only on a self-report.
- **Worktree isolation for concurrent writers (hard rule · GM-15 · CB-P5-27 承接)**: when dispatching ≥2 subagents concurrently and **any** of them may write files / commit / checkout / rebase, **every** such subagent MUST be launched with `isolation: "worktree"`. Sharing a working tree between concurrent writers is a data race — a later `git checkout` in one subagent silently wipes another's uncommitted work. GM-12 (≤2 concurrency) caps the **number**; GM-15 covers the **filesystem**. Read-only reconnaissance (codegraph / grep / Read only) may share the working tree. Single-subagent dispatch may share the working tree regardless of write intent.

## Delivery standard

For substantial work: (1) context → (2) specialist analysis if useful → (3) synthesize order + file ownership → (4) implement with serialized edits to shared files → (5) run lint / tests / smoke → (6) verify repository state → (7) write back to knowledge base.

- **Do not claim completion until acceptance criteria are checked against actual project state.**
- Final response states: files changed, checks run with results, knowledge-base updates, unresolved risks, subagents used (or "none — delegation would not improve quality").

## Git delivery closure

- Commits align with the PR / issue boundaries defined in the knowledge base. Use the currently designated branch unless the task requires another.
- **A PR is not `merged` until**: its commits are pushed, remote-reachable, and the PR status ledger has the branch + commit hash(es). Tests passing / KB write-back do **not** replace push evidence.
- Before committing, inspect the staged diff. Exclude unrelated user changes, credentials, real user data, test artifacts. Never absorb pre-existing unrelated work.
- Enforcement + full policy: `tools/check_delivery_closure.py` (when present) and [[10 架构基线/技术开发规则与工程实施规范#Git 交付闭环规则]].

## Test artifact hygiene

After **any** test / smoke / contract / `curl` run, before the turn ends:

1. `python tools/cleanup_test_artifacts.py` — dry-run
2. `python tools/cleanup_test_artifacts.py --apply`
3. `git status` shows only intended production diff

Extending patterns, exclusion list, and full rationale: `tools/README.md#测试残留清理`.

## Automation & guardrails

Regenerate rules and hard-checked invariants (do not skip):

- **Session preflight** (recommended first step of any coding session): `python tools/check_env.py` — verifies Obsidian path, CodeGraph index, `codegraph` CLI, Node/fnm, tools/ scripts.
- **Regenerate rules** after editing `docs/agent-protocol/base.md`: `python tools/sync_agent_configs.py --apply`
- **Rule consistency** (pre-commit blocks otherwise): `python tools/check_agent_configs.py`
- **Delivery closure** (before marking a PR merged): `python tools/check_delivery_closure.py`
- **Test residue** (before finishing any turn that ran tests): `python tools/cleanup_test_artifacts.py --apply`

Full script index: `tools/README.md`.
