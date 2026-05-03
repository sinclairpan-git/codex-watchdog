# Agent Continuity Protocol

This repository uses the AI SDLC framework. Treat AI SDLC state as the source of truth for framework progress, and use this `AGENTS.md` file as Codex runtime guidance for preserving continuity when chat context compaction fails.

Important AI SDLC state and rule locations:

- `.ai-sdlc/state/checkpoint.yml`
- `.ai-sdlc/state/resume-pack.yaml`
- `.ai-sdlc/work-items/<work-item>/resume-pack.yaml`
- `.ai-sdlc/memory/constitution.md`
- `src/ai_sdlc/rules/`
- `.cursor/rules/ai-sdlc.md` as optional IDE guidance, not canonical truth

## Resume Procedure

When starting or resuming work in this repository:

1. Check `git status --short` before editing.
2. Read `.ai-sdlc/state/checkpoint.yml` and `.ai-sdlc/state/resume-pack.yaml` if they exist.
3. For SDLC work, read the active work item files referenced by the checkpoint or resume pack.
4. Read `docs/codex-handoff.md` if it exists.
5. Continue from the recorded next steps instead of restarting from scratch.

If `.ai-sdlc/state/checkpoint.yml`, `.ai-sdlc/state/resume-pack.yaml`, the active branch, or the working tree disagree, stop and report the mismatch before mutating SDLC state. Trust the working tree for local edits, but do not silently overwrite framework truth.

## Codex Handoff Bridge

Use `docs/codex-handoff.md` as a concise Codex-readable bridge for fresh threads. Create it if it does not exist.

The handoff is not a replacement for AI SDLC checkpoint or resume-pack files. It should summarize the current working context, point to the relevant SDLC truth files, and capture transient progress since the last formal SDLC checkpoint.

## When To Update

Update `docs/codex-handoff.md`:

- after any meaningful code, config, documentation, or test change
- after running tests, smoke checks, or debugging commands with important results
- after discovering a blocker, risk, root cause, or important repo convention
- after detecting or resolving any mismatch in AI SDLC state
- before inspecting or producing very large logs or files
- before starting a long-running command or multi-step refactor
- before pausing, ending, switching tasks, or handing off work
- at least every 20 minutes during extended work

For substantial tasks, prefer updating the handoff at natural milestones instead of waiting for the context window to become large.

## Required Contents

`docs/codex-handoff.md` must include:

- Current goal
- AI SDLC snapshot: active work item, stage, branch, checkpoint path, resume-pack path, and relevant spec/plan/tasks paths
- Current state
- Changed files and what changed
- Key decisions and rationale
- Commands/tests run and result summaries
- Blockers, risks, or assumptions
- Exact next steps

Do not paste large command outputs into the handoff. Summarize the result and reference the relevant file or command.

Do not record secrets, tokens, API keys, private credentials, or sensitive environment values.
