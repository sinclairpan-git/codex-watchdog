# Codex Handoff

## Current Goal

Production hotfix for Watchdog Feishu notification pollution. Feishu must not receive approval prompts or long "next step" text generated from internal handoff/recovery/PR state. Human approval prompts are allowed only when there is a real actionable runtime approval or explicit recovery decision, not when the brain merely says "require approval" or when the action is informational operator guidance.

## AI SDLC Snapshot

- Active git branch: `codex/fix-feishu-guidance-confirmation`
- AI SDLC checkpoint path: `.ai-sdlc/state/checkpoint.yml`
- Top-level resume-pack path: `.ai-sdlc/state/resume-pack.yaml`
- Checkpoint/resume stage: `completed`
- Checkpoint/resume work item: `085-model-first-continuation-governance`
- Checkpoint/resume branch: `codex/reconcile-continuity-runtime`
- Relevant spec: `specs/085-model-first-continuation-governance/spec.md`
- Relevant plan: `specs/085-model-first-continuation-governance/plan.md`
- Relevant tasks: `specs/085-model-first-continuation-governance/tasks.md`

The current hotfix branch intentionally differs from the completed AI SDLC branch recorded in checkpoint/resume. Do not mutate AI SDLC state for this production hotfix unless explicitly directed.

## Current State

- Root cause confirmed from production data: `Ai_AutoSDLC` delivered an approval prompt for `post_operator_guidance` at `2026-05-04T15:28:24Z`, with `requested_action_args.message` containing PR #39 status, merge commit, GitHub Actions, `@Codex review`, Codex app git directives, and next work-item instructions.
- Root cause confirmed in code: `post_operator_guidance` is informational guidance for the managed agent, but the resident expert dual gate converted a degraded guidance path into `require_user_decision`, which materialized a canonical approval and Feishu approval prompt.
- Second root cause confirmed in code: `brain_intent=require_approval` fell back to `continue_session` even when no real active projected approval existed, creating synthetic "brain requested explicit human approval" prompts.
- Third root cause confirmed in Feishu renderer: delivery rendered raw `action_args.message` as "建议下一步" after only whitespace cleanup, so internal handoff and git directive text could leak into Feishu.
- Hotfix now blocks operator guidance when the resident expert gate is degraded without creating a human approval prompt.
- Hotfix now suppresses `require_approval` when no active projected approval exists; it still preserves reminting when a real runtime approval projection exists.
- Hotfix now changes candidate closure from a human approval prompt to a non-executable review notice.
- Hotfix now prevents Feishu from rendering `post_operator_guidance` messages as next-step text and drops unsafe/long next-step text containing git directives, PR metadata, GitHub Actions, or branch handoff markers.
- Delivery worker now suppresses any old/new `post_operator_guidance` approval prompts and blocked operator-guidance notifications before they reach Feishu.
- Production data check found no currently pending `Ai_AutoSDLC` invalid canonical approvals and no pending invalid delivery outbox records; already delivered Feishu history cannot be recalled.
- LaunchAgent `com.codex.watchdog` runs from `/Users/sinclairpan/project/codex-watchdog/scripts/start_watchdog.sh` with working directory `/Users/sinclairpan/project/codex-watchdog`.
- Full local regression is green after the final non-active observe-only suppression.
- Production service has been restarted with this branch loaded. Post-restart `Ai_AutoSDLC` API reports pending approval count `0`, approval queue length `0`, and pending approvals endpoint count `0`.
- Post-restart production scans show no `Ai_AutoSDLC` policy decisions or delivery outbox rows created after `2026-05-04T15:50:00Z`.

## Changed Files

- `src/watchdog/services/session_spine/orchestrator.py`: removed synthetic `continue_session` fallback for `require_approval` unless an active projected approval exists; degraded resident expert gate for `post_operator_guidance` now records `block_and_alert` instead of `require_user_decision`.
- `src/watchdog/services/policy/engine.py`: candidate closure is now a non-executable review notice (`block_and_alert`) instead of a human approval prompt.
- `src/watchdog/services/policy/decisions.py`: updated candidate-closure runtime disposition mapping to `block_and_alert`.
- `src/watchdog/services/delivery/feishu_client.py`: added next-step safety filtering and never renders `post_operator_guidance` message content as Feishu "建议下一步".
- `src/watchdog/services/delivery/worker.py`: suppresses operator-guidance approval prompts and blocked operator-guidance notifications as a delivery safety net.
- `src/watchdog/services/session_spine/text.py`: strips Codex app `::git-*` directives from sanitized session summaries.
- `tests/test_watchdog_session_spine_runtime.py`: added/updated coverage for no synthetic approvals, real runtime approval reminting, candidate-closure notices, and degraded branch guidance without approval prompts.
- `tests/test_watchdog_feishu_delivery.py`: added coverage that operator-guidance/internal handoff messages and unsafe next-step text are not rendered to Feishu.
- `tests/test_watchdog_delivery_worker.py`: added worker suppression coverage for operator-guidance approval and notification envelopes.
- `docs/codex-handoff.md`: updated with the current hotfix state.

## Key Decisions

- Feishu approval cards must represent real operator decisions, not model uncertainty, degraded guidance paths, or internal handoff instructions.
- `post_operator_guidance` is informational. If Watchdog cannot safely post it automatically, it must not ask the user to approve "posting guidance".
- "建议下一步" in Feishu must be concise and action-scoped. It must not be derived from raw handoff text, PR summaries, merge metadata, Codex app git directives, or branch-switch packets.
- Keep real runtime approval reminting intact: when A-Agent exposes an active projected approval, Watchdog may still mint a clean canonical approval even if stale local approval records need superseding.

## Commands And Results

- `.venv/bin/python -m pytest tests/test_watchdog_session_spine_runtime.py::test_resident_orchestrator_suppresses_brain_require_approval_without_trusted_approval ... test_resident_orchestrator_blocks_branch_guidance_without_human_approval_prompt` -> `4 passed`
- `.venv/bin/python -m pytest tests/test_watchdog_feishu_delivery.py::test_feishu_render_text_includes_next_step_and_key_facts_for_approval ... test_feishu_render_text_sanitizes_recursive_rule_based_next_step_message` -> `4 passed`
- `.venv/bin/python -m pytest tests/test_watchdog_delivery_worker.py::test_delivery_worker_delivers_approval_when_session_is_awaiting_approval ... test_delivery_worker_suppresses_blocked_operator_guidance_notification` -> `3 passed`
- `.venv/bin/python -m pytest tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_feishu_delivery.py tests/test_watchdog_delivery_worker.py tests/test_watchdog_policy_engine.py tests/test_watchdog_approval_loop.py` -> `267 passed`
- `uv run ruff check src/watchdog/services/session_spine/orchestrator.py src/watchdog/services/policy/engine.py src/watchdog/services/policy/decisions.py src/watchdog/services/delivery/feishu_client.py src/watchdog/services/delivery/worker.py src/watchdog/services/session_spine/text.py tests/test_watchdog_session_spine_runtime.py tests/test_watchdog_feishu_delivery.py tests/test_watchdog_delivery_worker.py` -> passed
- `uv run ruff check .` -> passed
- `.venv/bin/python -m pytest` -> `1203 passed`
- Production data scan: pending invalid `Ai_AutoSDLC` canonical approvals -> `[]`
- Production data scan: pending invalid `Ai_AutoSDLC` delivery outbox records -> `[]`
- `launchctl print gui/$(id -u)/com.codex.watchdog` -> service running from this repository, pid `90967` at time of check
- Restarted production service with `launchctl kickstart -k gui/502/com.codex.watchdog`; service running from this repository, pid `47325` at post-restart check.
- Post-restart Watchdog API `/api/v1/watchdog/sessions/Ai_AutoSDLC` -> `success=true`, pending `0`, queue `0`, facts `project_not_active`
- Post-restart Watchdog API `/api/v1/watchdog/sessions/Ai_AutoSDLC/pending-approvals` -> `success=true`, count `0`
- Post-restart production scan for `Ai_AutoSDLC` delivery outbox rows created after `2026-05-04T15:50:00Z` -> `[]`
- Post-restart production scan for `Ai_AutoSDLC` policy decisions created after `2026-05-04T15:50:00Z` -> `[]`

## Blockers, Risks, Assumptions

- Already delivered Feishu messages cannot be recalled; the fix prevents new emissions.
- Already delivered Feishu history remains visible in the chat; this change stops new emissions and stops new internal outbox churn for the covered paths.
- AI SDLC checkpoint/resume still represent completed WI-085, not this hotfix branch.
- Do not record or paste runtime secrets from `.env.a`, `.env.w`, Keychain, or shell output.

## Exact Next Steps

1. Commit the hotfix.
2. Push `codex/fix-feishu-guidance-confirmation`.
3. Open PR, request `@codex review`, monitor checks/review, address issues, and merge to `main`.
4. After merge, keep watching production delivery/policy stores for new invalid approval prompts.
