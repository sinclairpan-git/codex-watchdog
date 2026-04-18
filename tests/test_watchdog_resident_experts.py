from __future__ import annotations

from pathlib import Path

from watchdog.services.resident_experts.service import ResidentExpertRuntimeService


def _write_registry(repo_root: Path) -> None:
    operations_dir = repo_root / "docs" / "operations"
    operations_dir.mkdir(parents=True, exist_ok=True)
    (operations_dir / "resident-expert-agents.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "resident_expert_agents:",
                "  - id: managed-agent-expert",
                "    name: Managed Agent Expert",
                "    display_name_zh_cn: Managed Agent专家",
                "    layer: third_party_oversight",
                "    independence: outside_project_delivery",
                "    role_summary: managed execution oversight",
                "    consult_before:",
                "      - recovery contract changes",
                "  - id: hermes-agent-expert",
                "    name: Hermes Agent Expert",
                "    display_name_zh_cn: Hermes Agent专家",
                "    layer: third_party_oversight",
                "    independence: outside_project_delivery",
                "    role_summary: orchestration oversight",
                "    consult_before:",
                "      - triage ux changes",
            ]
        ),
        encoding="utf-8",
    )
    (operations_dir / "resident-expert-agents.zh-CN.md").write_text(
        "# charter\nfixed experts\n",
        encoding="utf-8",
    )


def test_resident_expert_runtime_persists_fixed_bindings_across_restart(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_registry(repo_root)

    service = ResidentExpertRuntimeService.from_data_dir(data_dir, repo_root=repo_root)
    ensured = service.ensure_registry()

    assert [binding.expert_id for binding in ensured] == [
        "managed-agent-expert",
        "hermes-agent-expert",
    ]
    assert all(binding.status == "unavailable" for binding in ensured)
    assert ensured[0].charter_version_hash.startswith("sha256:")

    restarted = ResidentExpertRuntimeService.from_data_dir(data_dir, repo_root=repo_root)
    restored = restarted.list_runtime_views()

    assert [view.expert_id for view in restored] == [
        "managed-agent-expert",
        "hermes-agent-expert",
    ]
    assert all(view.status == "unavailable" for view in restored)


def test_consult_or_restore_prefers_existing_runtime_handle_over_ad_hoc_redefinition(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_registry(repo_root)

    service = ResidentExpertRuntimeService.from_data_dir(data_dir, repo_root=repo_root)
    service.ensure_registry()
    service.bind_runtime_handle(
        expert_id="managed-agent-expert",
        runtime_handle="agent:managed:1",
        observed_at="2026-04-18T06:00:00Z",
    )

    restarted = ResidentExpertRuntimeService.from_data_dir(data_dir, repo_root=repo_root)
    restored = restarted.consult_or_restore(
        consultation_ref="decision:resident:1",
        expert_ids=["managed-agent-expert"],
        consulted_at="2026-04-18T06:05:00Z",
    )

    assert restored[0].expert_id == "managed-agent-expert"
    assert restored[0].runtime_handle == "agent:managed:1"
    assert restored[0].status == "restoring"
    assert restored[0].last_seen_at == "2026-04-18T06:00:00Z"
    assert restored[0].last_consultation_ref == "decision:resident:1"


def test_bind_runtime_handle_marks_fixed_expert_as_bound_until_consulted(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_registry(repo_root)

    service = ResidentExpertRuntimeService.from_data_dir(data_dir, repo_root=repo_root)
    service.ensure_registry()
    service.bind_runtime_handle(
        expert_id="managed-agent-expert",
        runtime_handle="agent:managed:1",
        observed_at="2026-04-18T06:00:00Z",
    )

    views = service.list_runtime_views()

    assert views[0].expert_id == "managed-agent-expert"
    assert views[0].status == "bound"
    assert views[0].runtime_handle_bound is True
    assert views[0].oversight_ready is False


def test_resident_expert_runtime_becomes_stale_after_threshold(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    data_dir = tmp_path / "data"
    _write_registry(repo_root)

    service = ResidentExpertRuntimeService.from_data_dir(
        data_dir,
        repo_root=repo_root,
        stale_after_seconds=60.0,
    )
    service.ensure_registry()
    service.bind_runtime_handle(
        expert_id="managed-agent-expert",
        runtime_handle="agent:managed:1",
        observed_at="2026-04-18T06:00:00Z",
    )

    views = service.list_runtime_views(now="2026-04-18T06:02:00Z")

    assert views[0].expert_id == "managed-agent-expert"
    assert views[0].status == "stale"
    assert views[0].runtime_handle_bound is True
    assert views[0].oversight_ready is False
