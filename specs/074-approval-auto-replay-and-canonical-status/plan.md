# Plan: 074 Approval Auto Replay And Canonical Status

## Objective

Restore formal-contract-compliant auto-approval behavior for local test execution and safe file permissions, while keeping canonical state output aligned with WI-066.

## Implementation Steps

1. Lock the regression with failing tests for local pytest and safe permission scopes.
2. Update the risk classifier with a narrow allowlist for supported local pytest entrypoints and safe file permissions.
3. Align sync-loop regression coverage with canonical `waiting_for_approval` output.
4. Run targeted tests, full tests, and AI SDLC constraint verification.
5. Capture the work item runtime and summary artifacts.

## Guardrails

- Do not weaken fail-closed behavior for network, credentials, release, or system-level operations.
- Keep the classifier change minimal and explicit.
- Preserve backward-compatible input handling while normalizing outward state.
