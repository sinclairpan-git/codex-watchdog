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
