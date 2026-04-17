from __future__ import annotations

from watchdog.validation.docs_contracts import (
    DOC_CONTRACT_CHECKS,
    validate_long_running_autonomy_docs,
)


def test_long_running_autonomy_doc_contracts_pass_in_repo() -> None:
    assert validate_long_running_autonomy_docs() == []


def test_long_running_autonomy_doc_contract_checks_cover_release_and_conflict_guards() -> None:
    names = {check.name for check in DOC_CONTRACT_CHECKS}

    assert "arch_has_stage_goal_conflict_event" in names
    assert "arch_stage_conflict_degrades_to_reference" in names
    assert "arch_release_gate_has_label_manifest" in names
    assert "plan_task6_forbids_manual_splicing" in names
    assert "plan_task8_e2e_blocks_without_report" in names
    assert "plan_risk_control_requires_stage_goal_conflict_schema" in names
    assert "env_example_covers_feishu_ingress_and_delivery" in names
    assert "env_example_covers_openai_compatible_provider" in names
    assert "env_example_covers_ai_autosdlc_preview_cursor_toggle" in names
    assert "env_example_covers_feishu_control_smoke" in names
    assert "getting_started_covers_feishu_official_ingress" in names
    assert "getting_started_covers_openai_compatible_provider" in names
    assert "getting_started_covers_ai_autosdlc_preview_cursor" in names
    assert "getting_started_covers_external_integration_smoke_harness" in names
    assert "readme_covers_external_integration_smoke_harness" in names
    assert "readme_covers_watchdog_runtime_factory" in names


def test_long_running_autonomy_doc_validator_reports_missing_files(tmp_path) -> None:
    violations = validate_long_running_autonomy_docs(tmp_path)

    assert (
        "arch_has_stage_goal_conflict_event: missing file "
        "docs/architecture/codex-long-running-autonomy-design.md"
    ) in violations
    assert (
        "plan_task6_creates_runbook_and_script: missing file "
        "docs/plans/2026-04-10-long-running-autonomy-implementation-plan.md"
    ) in violations
