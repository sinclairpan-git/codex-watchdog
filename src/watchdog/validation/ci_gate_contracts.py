from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

PR_GATE_WORKFLOW_REL = Path(".github/workflows/pr-gate.yml")
CI_GATE_SURFACES: dict[Path, tuple[str, ...]] = {
    PR_GATE_WORKFLOW_REL: (
        "pull_request",
        "push:main",
        "verify-constraints",
        "test",
        "lint",
    ),
}


def validate_ci_gate_surfaces(repo_root: Path | None = None) -> list[str]:
    root = repo_root or Path(__file__).resolve().parents[3]
    if not _ci_surface_context_present(root):
        return []

    violations: list[str] = []
    path = root / PR_GATE_WORKFLOW_REL
    if not path.is_file():
        return [f"ci gate surface missing: {PR_GATE_WORKFLOW_REL.as_posix()}"]

    text = path.read_text(encoding="utf-8")
    try:
        payload = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        return [f"ci gate surface {PR_GATE_WORKFLOW_REL.as_posix()} invalid YAML: {exc}"]

    if not isinstance(payload, Mapping):
        return [f"ci gate surface {PR_GATE_WORKFLOW_REL.as_posix()} must be a mapping"]

    violations.extend(_validate_triggers(payload))
    violations.extend(_validate_jobs(payload))
    return violations


def _validate_triggers(payload: Mapping[str, Any]) -> list[str]:
    violations: list[str] = []
    on_section = payload.get("on", payload.get(True))
    if not _has_pull_request_trigger(on_section):
        violations.append(
            f"ci gate surface {PR_GATE_WORKFLOW_REL.as_posix()} missing pull_request trigger"
        )
    elif not _has_unfiltered_pull_request_trigger(on_section):
        violations.append(
            f"ci gate surface {PR_GATE_WORKFLOW_REL.as_posix()} missing unfiltered pull_request trigger"
        )
    if not _has_main_push_trigger(on_section):
        violations.append(
            f"ci gate surface {PR_GATE_WORKFLOW_REL.as_posix()} missing push trigger for main"
        )
    return violations


def _validate_jobs(payload: Mapping[str, Any]) -> list[str]:
    jobs = payload.get("jobs")
    if not isinstance(jobs, Mapping):
        return [f"ci gate surface {PR_GATE_WORKFLOW_REL.as_posix()} missing jobs mapping"]

    violations: list[str] = []
    verify_job = jobs.get("verify-constraints")
    if not isinstance(verify_job, Mapping):
        violations.append(
            f"ci gate surface {PR_GATE_WORKFLOW_REL.as_posix()} missing verify-constraints job"
        )
    else:
        violations.extend(_validate_required_job_bypass_controls("verify-constraints", verify_job))
        verify_step = _find_required_run_step(
            verify_job, "uv run python -m ai_sdlc verify constraints"
        )
        if verify_step is None:
            violations.append(
                "ci gate surface .github/workflows/pr-gate.yml missing verify-constraints command: "
                "uv run python -m ai_sdlc verify constraints"
            )
        else:
            violations.extend(
                _validate_required_step_bypass_controls("verify-constraints", verify_step)
            )

    test_job = jobs.get("test")
    if not isinstance(test_job, Mapping):
        violations.append(f"ci gate surface {PR_GATE_WORKFLOW_REL.as_posix()} missing test job")
    else:
        violations.extend(_validate_required_job_bypass_controls("test", test_job))
        if not _job_needs(test_job, "verify-constraints"):
            violations.append(
                f"ci gate surface {PR_GATE_WORKFLOW_REL.as_posix()} missing test needs verify-constraints"
            )
        test_step = _find_required_run_step(test_job, "uv run pytest -q")
        if test_step is None:
            violations.append(
                f"ci gate surface {PR_GATE_WORKFLOW_REL.as_posix()} missing test command: uv run pytest"
            )
        else:
            violations.extend(_validate_required_step_bypass_controls("test", test_step))

    lint_job = jobs.get("lint")
    if not isinstance(lint_job, Mapping):
        violations.append(f"ci gate surface {PR_GATE_WORKFLOW_REL.as_posix()} missing lint job")
    else:
        violations.extend(_validate_required_job_bypass_controls("lint", lint_job))
        if not _job_needs(lint_job, "verify-constraints"):
            violations.append(
                f"ci gate surface {PR_GATE_WORKFLOW_REL.as_posix()} missing lint needs verify-constraints"
            )
        lint_step = _find_required_run_step(lint_job, "uv run ruff check")
        if lint_step is None:
            violations.append(
                f"ci gate surface {PR_GATE_WORKFLOW_REL.as_posix()} missing lint command: uv run ruff check"
            )
        else:
            violations.extend(_validate_required_step_bypass_controls("lint", lint_step))

    return violations


def _has_pull_request_trigger(on_section: Any) -> bool:
    if isinstance(on_section, str):
        return on_section == "pull_request"
    if isinstance(on_section, Sequence) and not isinstance(on_section, (str, bytes)):
        return "pull_request" in on_section
    return isinstance(on_section, Mapping) and "pull_request" in on_section


def _has_unfiltered_pull_request_trigger(on_section: Any) -> bool:
    if isinstance(on_section, (str, bytes)):
        return _has_pull_request_trigger(on_section)
    if isinstance(on_section, Sequence) and not isinstance(on_section, (str, bytes)):
        return _has_pull_request_trigger(on_section)
    if not isinstance(on_section, Mapping):
        return False
    pull_request = on_section.get("pull_request")
    return pull_request is None or pull_request == {}


def _has_main_push_trigger(on_section: Any) -> bool:
    if not isinstance(on_section, Mapping):
        return False
    push = on_section.get("push")
    if push is None:
        return False
    if not isinstance(push, Mapping):
        return False
    branches = push.get("branches")
    return _string_or_sequence_contains(branches, "main")


def _find_required_run_step(
    job: Mapping[str, Any], required_fragment: str
) -> Mapping[str, Any] | None:
    steps = job.get("steps")
    if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes)):
        return None
    for step in steps:
        if isinstance(step, Mapping):
            run = step.get("run")
            if _run_matches_required_command(run, required_fragment):
                return step
    return None


def _job_needs(job: Mapping[str, Any], required_job: str) -> bool:
    return _string_or_sequence_contains(job.get("needs"), required_job)


def _validate_required_job_bypass_controls(
    job_name: str, job: Mapping[str, Any]
) -> list[str]:
    violations: list[str] = []
    for key in ("if", "continue-on-error"):
        if key in job:
            violations.append(
                f"ci gate surface {PR_GATE_WORKFLOW_REL.as_posix()} {job_name} job must not define {key}"
            )
    return violations


def _validate_required_step_bypass_controls(
    job_name: str, step: Mapping[str, Any]
) -> list[str]:
    violations: list[str] = []
    for key in ("if", "continue-on-error"):
        if key in step:
            violations.append(
                f"ci gate surface {PR_GATE_WORKFLOW_REL.as_posix()} {job_name} command step must not define {key}"
            )
    return violations


def _string_or_sequence_contains(value: Any, needle: str) -> bool:
    if isinstance(value, str):
        return value == needle
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(item == needle for item in value)
    return False


def _run_matches_required_command(run: Any, required_command: str) -> bool:
    if not isinstance(run, str):
        return False

    normalized_lines = [line.strip() for line in run.splitlines() if line.strip()]
    return len(normalized_lines) == 1 and normalized_lines[0] == required_command


def _ci_surface_context_present(repo_root: Path) -> bool:
    return (repo_root / ".github").exists() or any(
        (repo_root / rel).is_file() for rel in CI_GATE_SURFACES
    )
