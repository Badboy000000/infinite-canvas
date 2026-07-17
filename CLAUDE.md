# Infinite Canvas - Agent Protocol

This file defines how agents should work in this repository. Keep project decisions, architecture notes, implementation plans, and development records in the Obsidian knowledge base, not here.

## Knowledge Base

Path:

```txt
E:\个人知识库\Infinite Canvas 二开与架构治理项目知识库
```

Required entry:

```txt
Infinite Canvas 二开与架构治理项目知识库 Index.md
```

Current organization:

- Root keeps only the required Index entry.
- `00 索引与规范/`: index notes, vault rules, and navigation.
- `10 架构基线/`: target architecture, gap analysis, roadmap, and engineering rules.
- `20 现状地图/`: current code facts and module maps.
- `30 治理方案/`: long-lived governance plans.
- `40 实施计划/`: implementation plans, PR lists, and issue breakdowns.
- `50 决策记录/`: formal architecture decisions.
- `60 讨论记录/`: discussion or review records that still serve as current baseline context.
- `90 资料归档/`: completed or historical material kept for traceability only.

Before any non-trivial architecture discussion, refactor plan, or code change:

1. Read this file.
2. Read the required knowledge-base entry.
3. Follow only links relevant to the current task, preferring `00 索引与规范/` index notes before detailed notes.
4. Prefer current baseline, maps, governance plans, implementation plans, and decision records over archived material.
5. Read `90 资料归档/` only when historical traceability or source discussion context is explicitly needed.
6. Inspect the relevant repository files, scripts, tests, configuration, and recent changes.

Source-of-truth rule:

- Use the repository for what currently exists.
- Use the knowledge base for intended architecture and recorded decisions.
- If they disagree, report the discrepancy before making consequential changes, then update the relevant knowledge-base note after the discrepancy is resolved.

After meaningful architecture discussion, refactor planning, or implementation work:

- Update the relevant knowledge-base index or note.
- Put active baseline discussion or review records under `60 讨论记录/` when needed.
- Put reference material, historical notes, completed source discussions, and other non-current material under `90 资料归档/` when needed.
- Do not create a separate long-term memory system inside this repository.

## Work Style

- Proceed without repeated confirmation for ordinary, reversible project work.
- Ask before destructive or difficult-to-reverse operations, deleting user data, changing credentials, touching billing or production infrastructure, or making materially ambiguous product or architecture decisions.
- Search for existing implementations and conventions before adding new abstractions, dependencies, frameworks, or workflow changes.
- Preserve established conventions unless a documented reason justifies changing them.
- Avoid duplicate abstractions, parallel state systems, and redundant tooling.
- Identify migration and compatibility impact before changing shared interfaces.

For AI or AIGC functionality, also check model/provider compatibility, prompt and workflow versioning, structured-output contracts, retry/timeout/cancellation behavior, cost and latency impact, validation, deterministic post-processing, observability, reproducibility, secret handling, and prompt-injection exposure.

## Subagents

Claude is the lead orchestrator. Subagents are optional specialists, not a checklist.

Use subagents only when they improve quality or speed through specialized expertise, independent investigation, parallel analysis, implementation on disjoint files, or unbiased review. Do not delegate trivial edits or simple lookups.

Before delegation:

1. Restate the objective and acceptance criteria.
2. Identify affected repository areas and relevant knowledge-base notes.
3. Read enough context to avoid generic assignments.
4. Select the smallest useful set of specialists.
5. Separate parallel work from sequential work and avoid concurrent edits to the same or tightly coupled files.

Every delegated task must include the objective, constraints, edit permission, owned files or modules, expected output, acceptance criteria, required checks, and explicit exclusions.

Every subagent report must include inspected files and notes, findings or decisions, changed files, commands or tests run, completion evidence, unresolved risks, and recommended next action.

The lead resolves contradictions between agent outputs, owns final synthesis, verifies actual repository state, and must not rely only on a subagent self-report.

## Delivery Standard

For substantial implementation work, follow this order when applicable:

1. Establish context and requirements.
2. Run specialist analysis only when useful.
3. Synthesize the implementation order and file ownership.
4. Implement with serialized edits to shared or coupled files.
5. Run relevant linting, type checks, tests, builds, or smoke checks.
6. Verify the final repository state.
7. Write back to the knowledge base when required.

Do not claim completion until the acceptance criteria are checked against the actual project state.

Final responses for substantial work should state files changed, checks run, verification results, knowledge-base updates, unresolved risks, and which subagents were used. If no subagent was needed, say the task was completed directly because delegation would not improve quality or speed.

## Git Delivery Closure

Knowledge-base completion records and Git delivery must describe the same work. A governance PR / issue is not complete merely because its code was written, reviewed, or documented.

- Keep commits aligned with the PR / issue boundaries defined in the knowledge base. Do not mix unrelated governance work into one commit. A PR may use a small ordered series of commits when one commit would hide meaningful implementation steps.
- Use the currently designated branch unless the task explicitly requires another branch. Do not create a branch per PR by default.
- Before a PR can be marked `merged` / completed in the knowledge base, its in-scope changes must be committed, pushed to the configured remote, and recorded in the corresponding PR status ledger with the branch and commit hash(es).
- A successful test, smoke check, Lead review, or knowledge-base write-back does not replace commit and push evidence. If push has not succeeded, keep the PR in `submitted` or `in_progress` and report the blocker.
- Before committing, inspect the staged diff and exclude unrelated user changes, credentials, secrets, real user data, and test artifacts. Never absorb pre-existing unrelated work merely to make `git status` clean.
- At delivery, verify that the PR's commit is reachable from the recorded remote branch and that no in-scope change remains uncommitted. Report any unrelated pre-existing working-tree changes separately.
- Historical recovery commits that cover more than one recorded PR require explicit Lead approval and must map every included PR to the recovery commit in the status ledger. They are a repair mechanism, not the normal workflow.
- Unless the user or task explicitly says not to push, governance implementation work is expected to complete the local commit, remote push, and knowledge-base commit-hash write-back in the same delivery cycle.

## Test Artifact Hygiene

Every time you run tests, backend/frontend smoke checks, contract tests, or ad-hoc `curl` verification against the local server, you MUST leave the repository in a clean "production code only" state before finishing the turn. The repository is not a scratch space; test artifacts are not deliverables.

Canonical cleanup script: `tools/cleanup_test_artifacts.py`.

Mandatory workflow after any test / smoke / verification run:

1. Preview: `python tools/cleanup_test_artifacts.py` — dry-run listing everything the script would remove.
2. Apply: `python tools/cleanup_test_artifacts.py --apply` — actually remove the listed items.
3. Verify: `git status` should now show only the intended production diff. No `__pycache__/`, `.pytest_cache/`, stray top-level letter directories (`X/` / `Y/` / `Z/`), empty smoke-only `output/` subdirs, or `__smoke*` entries inside `data/api_providers.json` / `data/canvases/*.json`.

The script covers:

- Python caches: recursive `__pycache__/`, `*.pyc`, `*.pyo`, top-level `.pytest_cache/`.
- Stray empty letter directories at the repo root (`X/`, `Y/`, `Z/`) created by ad-hoc curl / adhoc scripts.
- Empty smoke-only output subdirs (`output/input/`, `output/output/`) — deleted only when empty, real generated artifacts are preserved.
- Smoke pollution in `data/`: provider entries with `id` starting with `__smoke` inside `data/api_providers.json`, and canvas files whose `title` starts with `__smoke` (or is exactly `smoke`) inside `data/canvases/`.

The script never touches: `API/.env*`, `app/`, `docs/`, `tests/`, `tools/`, `static/`, `packages/`, `assets/`, `workflows/`, or the rest of `data/` (asset library, conversations, history — real user data).

Rules:

- If you added a new class of test artifact (a new temp directory, a new smoke fixture pattern in `data/`, etc.), extend `tools/cleanup_test_artifacts.py` in the same commit — do not leave "please clean up manually" notes for the next agent.
- If a real (non-smoke) file happens to match a smoke pattern, rename the file rather than weakening the pattern.
- `.gitignore` already excludes the cache classes; cleanup is still required so `git status` is meaningful for anyone else inspecting the working tree.
- Subagents that run tests must run the cleanup script themselves before reporting completion; the lead will re-verify with `git status`.

