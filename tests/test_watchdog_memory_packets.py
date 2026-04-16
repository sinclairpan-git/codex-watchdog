from __future__ import annotations

import importlib
import importlib.util


def _find_spec(module_name: str):
    try:
        return importlib.util.find_spec(module_name)
    except ModuleNotFoundError:
        return None


def test_memory_hub_contract_modules_exist_for_packet_pipeline() -> None:
    expected_modules = (
        "watchdog.services.memory_hub.models",
        "watchdog.services.memory_hub.contracts",
        "watchdog.services.memory_hub.packets",
        "watchdog.services.memory_hub.service",
    )

    missing = [
        module_name
        for module_name in expected_modules
        if _find_spec(module_name) is None
    ]

    assert missing == []


def test_memory_hub_packet_contract_exports_quality_and_worker_scope_types() -> None:
    module_spec = _find_spec("watchdog.services.memory_hub.models")
    assert module_spec is not None

    models = importlib.import_module("watchdog.services.memory_hub.models")
    expected_symbols = (
        "ExpansionHandle",
        "PacketInputRef",
        "ContextQualitySnapshot",
        "WorkerScopedPacketInput",
    )
    missing = [symbol for symbol in expected_symbols if not hasattr(models, symbol)]

    assert missing == []


def test_session_search_archive_only_returns_summary_refs_and_expansion_handles() -> None:
    indexer_module = importlib.import_module("watchdog.services.memory_hub.indexer")
    service_module = importlib.import_module("watchdog.services.memory_hub.service")

    archive_entry = indexer_module.SessionArchiveEntry(
        entry_id="archive:repo-a:1",
        project_id="repo-a",
        session_id="session:repo-a",
        summary="Recover command lease after runtime failure",
        source_ref="session:event:42",
        content_hash="sha256:abc123",
        raw_content="full transcript that must stay out of hot path",
        expansion_handles=[
            indexer_module.ExpansionHandle(
                handle_id="exp:42",
                source_ref="session:event:42",
                content_hash="sha256:abc123",
            )
        ],
    )
    indexer = indexer_module.SessionSearchArchiveIndexer(entries=[archive_entry])
    service = service_module.MemoryHubService(indexer=indexer)

    refs = service.search_session_archive("command lease")

    assert [ref.summary for ref in refs] == ["Recover command lease after runtime failure"]
    assert refs[0].source_ref == "session:event:42"
    assert refs[0].expansion_handles == ["exp:42"]
    assert "raw_content" not in refs[0].model_dump()


def test_skill_registry_prefers_local_source_and_preview_contracts_stay_disabled() -> None:
    skills_module = importlib.import_module("watchdog.services.memory_hub.skills")
    service_module = importlib.import_module("watchdog.services.memory_hub.service")

    registry = skills_module.SkillRegistry(
        records=[
            skills_module.SkillMetadata(
                name="python-debugging",
                short_description="shared playbook",
                trust_level="shared",
                security_verdict="pass",
                content_hash="sha256:shared",
                installed_version="1.0.0",
                last_scanned_at="2026-04-13T10:00:00Z",
                source_ref="skill:shared:python-debugging",
                source_kind="shared",
            ),
            skills_module.SkillMetadata(
                name="python-debugging",
                short_description="local playbook",
                trust_level="local",
                security_verdict="pass",
                content_hash="sha256:local",
                installed_version="1.1.0",
                last_scanned_at="2026-04-13T11:00:00Z",
                source_ref="skill:local:python-debugging",
                source_kind="local",
            ),
        ]
    )
    service = service_module.MemoryHubService(skill_registry=registry)

    metadata = service.list_skill_metadata()
    preview_contracts = service.preview_contracts()

    assert [item.source_ref for item in metadata] == ["skill:local:python-debugging"]
    assert metadata[0].read_only is False
    assert all(contract.enabled is False for contract in preview_contracts.values())


def test_ai_autosdlc_cursor_preview_returns_stage_aware_packet_when_enabled() -> None:
    models = importlib.import_module("watchdog.services.memory_hub.models")
    service_module = importlib.import_module("watchdog.services.memory_hub.service")
    skills_module = importlib.import_module("watchdog.services.memory_hub.skills")

    class FakeIndexer:
        def search(
            self,
            query: str,
            *,
            project_id: str | None = None,
            session_id: str | None = None,
            limit: int | None = None,
        ):
            assert query == "补齐 release gate"
            assert project_id == "repo-a"
            assert session_id is None
            assert limit == 4
            return [
                models.PacketInputRef(
                    ref_id="ref-1",
                    summary="recent release gate recovery",
                    source_ref="archive:repo-a:release-gate-1",
                )
            ]

    registry = skills_module.SkillRegistry(
        records=[
            skills_module.SkillMetadata(
                name="pytest",
                short_description="python test runner",
                trust_level="trusted",
                security_verdict="pass",
                content_hash="hash:pytest-v1",
                installed_version="8.0.0",
                last_scanned_at="2026-04-15T00:00:00Z",
                source_ref="skill:local:pytest",
                source_kind="local",
            )
        ]
    )
    service = service_module.MemoryHubService(
        indexer=FakeIndexer(),
        skill_registry=registry,
        preview_contract_overrides={"ai-autosdlc-cursor": True},
    )
    service.upsert_resident_memory(
        project_id="repo-a",
        memory_key="goal.current",
        summary="补齐 release gate",
        source_ref="session:event:goal-1",
        source_scope="project-local",
        source_runtime="watchdog",
    )

    response = service.ai_autosdlc_cursor(
        request=models.AIAutoSDLCCursorRequest(
            project_id="repo-a",
            repo_fingerprint="fingerprint:repo-a",
            stage="verification",
            task_kind="closeout",
            capability_request="release-gate",
            active_goal="补齐 release gate",
            current_phase_goal="补齐 release gate",
            requested_packet_kind="stage-aware",
        ),
        quality=models.ContextQualitySnapshot(
            key_fact_recall=0.9,
            irrelevant_summary_precision=0.8,
            token_budget_utilization=0.4,
            expansion_miss_rate=0.1,
        ),
    )

    assert response.enabled is True
    assert response.goal_alignment.status == "aligned"
    assert response.goal_alignment.mode == "advisory"
    assert response.packet_inputs["refs"][0]["source_ref"] == "archive:repo-a:release-gate-1"
    assert response.resident_capsule[0]["summary"] == "补齐 release gate"
    assert response.skills[0]["name"] == "pytest"


def test_ai_autosdlc_cursor_preview_downgrades_conflicting_stage_goal_to_reference_only() -> None:
    models = importlib.import_module("watchdog.services.memory_hub.models")
    service_module = importlib.import_module("watchdog.services.memory_hub.service")

    service = service_module.MemoryHubService(
        preview_contract_overrides={"ai-autosdlc-cursor": True},
    )

    response = service.ai_autosdlc_cursor(
        request=models.AIAutoSDLCCursorRequest(
            project_id="repo-a",
            repo_fingerprint="fingerprint:repo-a",
            stage="implementation",
            task_kind="feature",
            capability_request="brain-runtime",
            active_goal="直接去改 Brain provider",
            current_phase_goal="先补 release gate 红测",
            requested_packet_kind="stage-aware",
        ),
        quality=models.ContextQualitySnapshot(
            key_fact_recall=0.9,
            irrelevant_summary_precision=0.8,
            token_budget_utilization=0.4,
            expansion_miss_rate=0.1,
        ),
    )

    assert response.enabled is True
    assert response.goal_alignment.status == "conflict"
    assert response.goal_alignment.mode == "reference_only"
    assert "直接去改 Brain provider" in response.goal_alignment.summary


def test_ai_autosdlc_cursor_preview_without_current_goal_stays_reference_only() -> None:
    models = importlib.import_module("watchdog.services.memory_hub.models")
    service_module = importlib.import_module("watchdog.services.memory_hub.service")

    service = service_module.MemoryHubService(
        preview_contract_overrides={"ai-autosdlc-cursor": True},
    )

    response = service.ai_autosdlc_cursor(
        request=models.AIAutoSDLCCursorRequest(
            project_id="repo-a",
            repo_fingerprint="fingerprint:repo-a",
            stage="design",
            task_kind="spec",
            capability_request="memory-hub",
            active_goal="补齐 memory hub capability",
            current_phase_goal=None,
            requested_packet_kind="stage-aware",
        ),
        quality=models.ContextQualitySnapshot(
            key_fact_recall=0.9,
            irrelevant_summary_precision=0.8,
            token_budget_utilization=0.4,
            expansion_miss_rate=0.1,
        ),
    )

    assert response.enabled is True
    assert response.goal_alignment.status == "missing_goal_contract"
    assert response.goal_alignment.mode == "reference_only"
    assert "current_phase_goal missing" in response.goal_alignment.summary
