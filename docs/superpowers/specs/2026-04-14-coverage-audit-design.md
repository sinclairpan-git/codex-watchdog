# Coverage Audit Design: PRD + Plan + Architecture Unmet Requirements

## Purpose

Produce a matrix-style audit that lists every requirement or scope item that is not yet
landed, where "not yet landed" means **missing any one** of: implementation evidence,
verification evidence, or a formal entry/route into the main runtime path.

The audit must answer: "Which designed, decomposed, or staged (MVP/Phase 1/Phase 2)
requirements remain unlanded?"

## Scope

**Documents included:**

1. PRD: `openclaw-codex-watchdog-prd.md`
2. Implementation plan: `docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md`
3. Architecture & stage definitions: `docs/architecture/*`

**Artifacts used as evidence:**

- Work item summaries: `.ai-sdlc/work-items/*/latest-summary.md`
- Work item execution logs (for verification lines): `specs/*/task-execution-log.md`
- Tests (for verification evidence): `tests/**`
- Code and routes (for implementation and entry evidence): `src/**`, `scripts/**`, `docs/operations/**`

## Audit Rule (Strict Evidence)

A requirement is **unlanded** if **any** of the following is missing:

1. **Implementation evidence**: code/module/script/route exists and is referenced.
2. **Verification evidence**: tests or verification log exists and passed.
3. **Formal entry evidence**: an explicit entry point exists (API/CLI route or
   primary runtime integration path).

If any evidence slot is empty, record the item as "unlanded" with the missing slot(s).

## Output: Matrix Format

**Columns**

- Source (document + section/line anchor)
- Requirement / Scope Item (1–2 lines)
- Implementation Evidence (file/commit/summary)
- Verification Evidence (test/log)
- Entry Evidence (API/CLI/route/runtime path)
- Missing Evidence (impl / verify / entry)
- Verdict (Unlanded)

**Ordering**

1. PRD requirements and success criteria
2. Implementation plan Tasks/Steps (incl. MVP/Phase 1/Phase 2 commitments)
3. Architecture stage requirements (MVP / Phase 1 / Phase 2 / release gate clauses)

## Evidence Mapping Rules

- Prefer **direct evidence** from work item summaries and execution logs.
- Use **tests** as verification evidence only if a summary/log is missing.
- Use **routes/modules** as entry evidence only if referenced in summaries or plan.
- Do **not** infer completion from "Status: completed" alone.
- If a requirement exists only as a preview/contract without integration,
  record "missing entry evidence."
- If the same requirement appears in multiple sources (PRD + plan + architecture),
  keep a single row and list all source anchors in the Source column.
- If multiple valid entry paths exist, prefer the one explicitly referenced in
  a plan/task summary; otherwise pick the most central runtime path and note
  alternatives in the evidence cell.

## Non-Goals

- Do not produce a full list of completed items.
- Do not adjust or change any implementation.
- Do not rewrite existing plans or specs.
- Do not introduce new requirements.

## Acceptance Criteria

1. Every unlanded requirement is listed in the matrix.
2. Each row names the missing evidence slot(s).
3. Citations point to the exact source and evidence (file + section).
4. Output is scoped to PRD + plan + architecture only.
