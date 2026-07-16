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

Before any non-trivial architecture discussion, refactor plan, or code change:

1. Read this file.
2. Read the required knowledge-base entry.
3. Follow only links relevant to the current task, preferring index notes before detailed notes.
4. Inspect the relevant repository files, scripts, tests, configuration, and recent changes.

Source-of-truth rule:

- Use the repository for what currently exists.
- Use the knowledge base for intended architecture and recorded decisions.
- If they disagree, report the discrepancy before making consequential changes, then update the relevant knowledge-base note after the discrepancy is resolved.

After meaningful architecture discussion, refactor planning, or implementation work:

- Update the relevant knowledge-base index or note.
- Put discussion records under `讨论记录/` when needed.
- Put reference material under `资料归档/` when needed.
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
