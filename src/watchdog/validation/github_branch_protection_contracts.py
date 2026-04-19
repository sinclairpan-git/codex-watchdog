from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

BRANCH_PROTECTION_CONTRACT_REL = Path(".github/branch-protection.main.json")
BRANCH_PROTECTION_AUDIT_WORKFLOW_REL = Path(".github/workflows/branch-protection-audit.yml")

_EXPECTED_BRANCH_PROTECTION_CONTRACT: dict[str, Any] = {
    "owner": "sinclairpan-git",
    "repo": "openclaw-codex-watchdog",
    "branch": "main",
    "required_status_checks": {
        "strict": True,
        "checks": [
            {"context": "lint", "app_id": None},
            {"context": "test", "app_id": None},
            {"context": "verify-constraints", "app_id": None},
        ],
        "contexts": ["lint", "test", "verify-constraints"],
    },
    "required_pull_request_reviews": {
        "dismiss_stale_reviews": True,
        "require_code_owner_reviews": False,
        "require_last_push_approval": False,
        "required_approving_review_count": 1,
    },
    "enforce_admins": True,
    "required_linear_history": True,
    "allow_force_pushes": False,
    "allow_deletions": False,
    "block_creations": False,
    "required_conversation_resolution": True,
}

Runner = Callable[..., subprocess.CompletedProcess[str]]


def validate_branch_protection_contract_surfaces(repo_root: Path | None = None) -> list[str]:
    root = repo_root or Path(__file__).resolve().parents[3]
    if not _branch_protection_context_present(root):
        return []

    path = root / BRANCH_PROTECTION_CONTRACT_REL
    if not path.is_file():
        return [f"github branch protection contract missing: {BRANCH_PROTECTION_CONTRACT_REL.as_posix()}"]

    payload, error = _load_contract_payload(path)
    if error is not None:
        return [error]

    return _validate_expected_mapping(path, payload, _EXPECTED_BRANCH_PROTECTION_CONTRACT)


def validate_live_github_branch_protection(
    repo_root: Path | None = None, *, runner: Runner | None = None
) -> list[str]:
    root = repo_root or Path(__file__).resolve().parents[3]
    static_violations = validate_branch_protection_contract_surfaces(root)
    if static_violations:
        return static_violations

    path = root / BRANCH_PROTECTION_CONTRACT_REL
    payload, error = _load_contract_payload(path)
    if error is not None:
        return [error]

    owner = payload["owner"]
    repo = payload["repo"]
    branch = payload["branch"]
    command = ["gh", "api", f"repos/{owner}/{repo}/branches/{branch}/protection"]
    completed = (runner or subprocess.run)(
        command,
        cwd=root,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip() or f"gh api exited {completed.returncode}"
        return [f"github branch protection live check failed for {owner}/{repo}@{branch}: {detail}"]

    try:
        live_payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return [
            f"github branch protection live check returned invalid JSON for {owner}/{repo}@{branch}: {exc}"
        ]

    if not isinstance(live_payload, Mapping):
        return [f"github branch protection live check returned non-object JSON for {owner}/{repo}@{branch}"]

    expected = _normalize_expected_contract(payload)
    actual = _normalize_live_branch_protection(live_payload)
    violations: list[str] = []
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if actual_value != expected_value:
            violations.append(
                f"github branch protection drift ({BRANCH_PROTECTION_CONTRACT_REL.as_posix()}): "
                f"{key} expected {expected_value!r}, got {actual_value!r}"
            )
    return violations


def validate_branch_protection_audit_workflow_surfaces(
    repo_root: Path | None = None,
) -> list[str]:
    root = repo_root or Path(__file__).resolve().parents[3]
    if not _branch_protection_context_present(root):
        return []

    path = root / BRANCH_PROTECTION_AUDIT_WORKFLOW_REL
    if not path.is_file():
        return [
            "github branch protection audit workflow missing: "
            f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()}"
        ]

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return [
            "github branch protection audit workflow "
            f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()} invalid YAML: {exc}"
        ]

    if not isinstance(payload, Mapping):
        return [
            "github branch protection audit workflow "
            f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()} must be a mapping"
        ]

    violations: list[str] = []
    if set(payload.keys()) != {"name", "permissions", "on", "jobs"} and set(payload.keys()) != {
        "name",
        "permissions",
        True,
        "jobs",
    }:
        violations.append(
            "github branch protection audit workflow "
            f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()} top-level keys must equal "
            "['jobs', 'name', 'on', 'permissions']"
        )
    if payload.get("name") != "Branch Protection Audit":
        violations.append(
            "github branch protection audit workflow "
            f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()} name must equal 'Branch Protection Audit'"
        )
    if payload.get("permissions") != {"contents": "read"}:
        violations.append(
            "github branch protection audit workflow "
            f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()} permissions must equal "
            "{'contents': 'read'}"
        )

    on_section = payload.get("on", payload.get(True))
    if not isinstance(on_section, Mapping):
        violations.append(
            "github branch protection audit workflow "
            f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()} must define workflow triggers"
        )
    else:
        if set(on_section.keys()) != {"workflow_dispatch", "schedule"}:
            violations.append(
                "github branch protection audit workflow "
                f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()} triggers must only contain "
                "workflow_dispatch and schedule"
            )
        if on_section.get("workflow_dispatch") != {}:
            violations.append(
                "github branch protection audit workflow "
                f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()} workflow_dispatch must equal {{}}"
            )
        if on_section.get("schedule") != [{"cron": "17 * * * *"}]:
            violations.append(
                "github branch protection audit workflow "
                f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()} schedule must equal "
                "[{'cron': '17 * * * *'}]"
            )

    violations.extend(_validate_branch_protection_audit_job(payload))
    return violations


def _load_contract_payload(path: Path) -> tuple[Mapping[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"github branch protection contract missing: {BRANCH_PROTECTION_CONTRACT_REL.as_posix()}"
    except json.JSONDecodeError as exc:
        return (
            None,
            f"github branch protection contract {BRANCH_PROTECTION_CONTRACT_REL.as_posix()} invalid JSON: {exc}",
        )
    if not isinstance(payload, Mapping):
        return (
            None,
            f"github branch protection contract {BRANCH_PROTECTION_CONTRACT_REL.as_posix()} must be a JSON object",
        )
    return payload, None


def _validate_branch_protection_audit_job(payload: Mapping[str, Any]) -> list[str]:
    jobs = payload.get("jobs")
    if not isinstance(jobs, Mapping):
        return [
            "github branch protection audit workflow "
            f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()} missing jobs mapping"
        ]
    if set(jobs.keys()) != {"branch-protection-audit"}:
        return [
            "github branch protection audit workflow "
            f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()} jobs must only contain "
            "branch-protection-audit"
        ]

    job = jobs.get("branch-protection-audit")
    if not isinstance(job, Mapping):
        return [
            "github branch protection audit workflow "
            f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()} missing branch-protection-audit job"
        ]

    violations: list[str] = []
    if set(job.keys()) != {"runs-on", "timeout-minutes", "steps"}:
        violations.append(
            "github branch protection audit workflow "
            f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()} branch-protection-audit job keys "
            "must equal ['runs-on', 'steps', 'timeout-minutes']"
        )
    if job.get("runs-on") != "ubuntu-latest":
        violations.append(
            "github branch protection audit workflow "
            f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()} branch-protection-audit job "
            "runs-on must equal 'ubuntu-latest'"
        )

    steps = job.get("steps")
    if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes)):
        return violations + [
            "github branch protection audit workflow "
            f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()} branch-protection-audit job "
            "missing steps sequence"
        ]

    expected_steps = [
        {
            "name": "Require audit token",
            "env": {"GH_TOKEN": "${{ secrets.BRANCH_PROTECTION_AUDIT_TOKEN }}"},
            "run": (
                'test -n "$GH_TOKEN" || '
                '(echo "Missing secret: BRANCH_PROTECTION_AUDIT_TOKEN" >&2; exit 1)'
            ),
        },
        {"uses": "actions/checkout@v4"},
        {
            "uses": "actions/setup-python@v5",
            "with": {"python-version": "3.11"},
        },
        {"uses": "astral-sh/setup-uv@v6"},
        {"run": "uv sync --dev"},
        {
            "env": {"GH_TOKEN": "${{ secrets.BRANCH_PROTECTION_AUDIT_TOKEN }}"},
            "run": "uv run python -m ai_sdlc verify github-branch-protection",
        },
    ]

    if len(steps) != len(expected_steps):
        violations.append(
            "github branch protection audit workflow "
            f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()} branch-protection-audit job "
            f"must define exactly {len(expected_steps)} steps"
        )
        return violations

    for index, expected in enumerate(expected_steps):
        step = steps[index]
        if not isinstance(step, Mapping):
            violations.append(
                "github branch protection audit workflow "
                f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()} step {index + 1} must be an object"
            )
            continue
        if set(step.keys()) != set(expected.keys()):
            violations.append(
                "github branch protection audit workflow "
                f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()} step {index + 1} keys "
                f"must equal {sorted(expected.keys())!r}"
            )
        for key, expected_value in expected.items():
            if step.get(key) != expected_value:
                violations.append(
                    "github branch protection audit workflow "
                    f"{BRANCH_PROTECTION_AUDIT_WORKFLOW_REL.as_posix()} step {index + 1} "
                    f"{key} must equal {expected_value!r}"
                )
    return violations


def _validate_expected_mapping(
    path: Path, payload: Mapping[str, Any], expected: Mapping[str, Any], prefix: str = ""
) -> list[str]:
    violations: list[str] = []
    relative_path = path.relative_to(path.parents[1]).as_posix()
    for key, expected_value in expected.items():
        dotted_key = f"{prefix}.{key}" if prefix else key
        actual_value = payload.get(key)
        if isinstance(expected_value, Mapping):
            if not isinstance(actual_value, Mapping):
                violations.append(
                    f"github branch protection contract {relative_path} {dotted_key} must be an object"
                )
                continue
            violations.extend(_validate_expected_mapping(path, actual_value, expected_value, dotted_key))
            continue
        if key == "contexts":
            if _normalize_contexts(actual_value) != expected_value:
                violations.append(
                    f"github branch protection contract {relative_path} {dotted_key} must equal {expected_value!r}"
                )
            continue
        if key == "checks":
            if _normalize_required_checks(actual_value) != _normalize_required_checks(expected_value):
                violations.append(
                    f"github branch protection contract {relative_path} {dotted_key} must equal {expected_value!r}"
                )
            continue
        if actual_value != expected_value:
            comparator = "must be" if isinstance(expected_value, bool) else "must equal"
            violations.append(
                f"github branch protection contract {relative_path} {dotted_key} {comparator} {_format_contract_value(expected_value)}"
            )
    return violations


def _normalize_expected_contract(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "required_status_checks.strict": payload["required_status_checks"]["strict"],
        "required_status_checks.checks": _normalize_required_checks(
            payload["required_status_checks"]["checks"]
        ),
        "required_status_checks.contexts": _normalize_contexts(
            payload["required_status_checks"]["contexts"]
        ),
        "required_pull_request_reviews.dismiss_stale_reviews": payload[
            "required_pull_request_reviews"
        ]["dismiss_stale_reviews"],
        "required_pull_request_reviews.require_code_owner_reviews": payload[
            "required_pull_request_reviews"
        ]["require_code_owner_reviews"],
        "required_pull_request_reviews.require_last_push_approval": payload[
            "required_pull_request_reviews"
        ]["require_last_push_approval"],
        "required_pull_request_reviews.required_approving_review_count": payload[
            "required_pull_request_reviews"
        ]["required_approving_review_count"],
        "enforce_admins": payload["enforce_admins"],
        "required_linear_history": payload["required_linear_history"],
        "allow_force_pushes": payload["allow_force_pushes"],
        "allow_deletions": payload["allow_deletions"],
        "block_creations": payload["block_creations"],
        "required_conversation_resolution": payload["required_conversation_resolution"],
    }


def _normalize_live_branch_protection(payload: Mapping[str, Any]) -> dict[str, Any]:
    reviews = payload.get("required_pull_request_reviews")
    status_checks = payload.get("required_status_checks")
    return {
        "required_status_checks.strict": _mapping_get(status_checks, "strict"),
        "required_status_checks.checks": _normalize_required_checks(
            _mapping_get(status_checks, "checks")
        ),
        "required_status_checks.contexts": _normalize_contexts(
            _mapping_get(status_checks, "contexts")
        ),
        "required_pull_request_reviews.dismiss_stale_reviews": _mapping_get(
            reviews, "dismiss_stale_reviews"
        ),
        "required_pull_request_reviews.require_code_owner_reviews": _mapping_get(
            reviews, "require_code_owner_reviews"
        ),
        "required_pull_request_reviews.require_last_push_approval": _mapping_get(
            reviews, "require_last_push_approval"
        ),
        "required_pull_request_reviews.required_approving_review_count": _mapping_get(
            reviews, "required_approving_review_count"
        ),
        "enforce_admins": _enabled(payload.get("enforce_admins")),
        "required_linear_history": _enabled(payload.get("required_linear_history")),
        "allow_force_pushes": _enabled(payload.get("allow_force_pushes")),
        "allow_deletions": _enabled(payload.get("allow_deletions")),
        "block_creations": _enabled(payload.get("block_creations")),
        "required_conversation_resolution": _enabled(
            payload.get("required_conversation_resolution")
        ),
    }


def _mapping_get(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return None


def _enabled(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value.get("enabled")
    return None


def _normalize_contexts(value: Any) -> list[str] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    contexts = [item for item in value if isinstance(item, str)]
    if len(contexts) != len(value):
        return None
    return sorted(contexts)


def _normalize_required_checks(value: Any) -> list[tuple[str, Any]] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    normalized: list[tuple[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None
        context = item.get("context")
        app_id = item.get("app_id")
        if not isinstance(context, str):
            return None
        if app_id is not None and not isinstance(app_id, int):
            return None
        normalized.append((context, app_id))
    return sorted(normalized)


def _format_contract_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return repr(value)


def _branch_protection_context_present(repo_root: Path) -> bool:
    return (
        (repo_root / ".github").exists()
        or (repo_root / BRANCH_PROTECTION_CONTRACT_REL).is_file()
        or (repo_root / BRANCH_PROTECTION_AUDIT_WORKFLOW_REL).is_file()
    )
