from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from watchdog.contracts.session_spine.models import (
    FactRecord,
    SessionProjection,
    TaskProgressView,
)
from watchdog.services.policy.decisions import (
    CanonicalDecisionRecord,
    PolicyDecisionStore,
    brain_intent_to_runtime_disposition,
    build_canonical_decision_record,
    build_decision_key,
)
from watchdog.services.session_spine.store import PersistedSessionRecord


def _fact(fact_code: str) -> FactRecord:
    return FactRecord(
        fact_id=f"fact-{fact_code}",
        fact_code=fact_code,
        fact_kind="signal",
        severity="info",
        summary=fact_code,
        detail=f"{fact_code} detail",
        source="watchdog",
        observed_at="2026-04-07T00:00:00Z",
    )


def _record(*, fact_snapshot_version: str = "fact-v7") -> PersistedSessionRecord:
    facts = [_fact("recovery_available")]
    return PersistedSessionRecord(
        project_id="repo-a",
        thread_id="session:repo-a",
        native_thread_id="thr_native_1",
        session_seq=7,
        fact_snapshot_version=fact_snapshot_version,
        last_refreshed_at="2026-04-07T00:00:00Z",
        session=SessionProjection(
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="thr_native_1",
            session_state="active",
            activity_phase="editing_source",
            attention_state="normal",
            headline="editing files",
            pending_approval_count=0,
            available_intents=["continue"],
        ),
        progress=TaskProgressView(
            project_id="repo-a",
            thread_id="session:repo-a",
            native_thread_id="thr_native_1",
            activity_phase="editing_source",
            summary="editing files",
            files_touched=["src/example.py"],
            context_pressure="low",
            stuck_level=0,
            primary_fact_codes=["recovery_available"],
            blocker_fact_codes=[],
            last_progress_at="2026-04-07T00:00:00Z",
        ),
        facts=facts,
        approval_queue=[],
    )


def test_build_decision_key_is_stable_for_same_snapshot_and_decision() -> None:
    decision_key = build_decision_key(
        session_id="session:repo-a",
        fact_snapshot_version="fact-v7",
        policy_version="policy-v1",
        decision_result="auto_execute_and_notify",
        brain_intent="propose_execute",
        action_ref="execute_recovery",
        approval_id=None,
    )

    assert (
        decision_key
        == "session:repo-a|fact-v7|policy-v1|auto_execute_and_notify|propose_execute|execute_recovery|"
    )


def test_build_decision_key_distinguishes_brain_intent() -> None:
    proposed = build_decision_key(
        session_id="session:repo-a",
        fact_snapshot_version="fact-v7",
        policy_version="policy-v1",
        decision_result="auto_execute_and_notify",
        brain_intent="propose_execute",
        action_ref="continue_session",
        approval_id=None,
    )
    legacy = build_decision_key(
        session_id="session:repo-a",
        fact_snapshot_version="fact-v7",
        policy_version="policy-v1",
        decision_result="auto_execute_and_notify",
        brain_intent=None,
        action_ref="continue_session",
        approval_id=None,
    )

    assert proposed != legacy


def test_policy_decision_store_reuses_existing_canonical_decision_for_same_decision_key(
    tmp_path: Path,
) -> None:
    store = PolicyDecisionStore(tmp_path / "policy_decisions.json")
    persisted_record = _record()

    first = build_canonical_decision_record(
        persisted_record=persisted_record,
        decision_result="auto_execute_and_notify",
        risk_class="none",
        action_ref="execute_recovery",
        matched_policy_rules=["registered_action"],
        decision_reason="registered action and complete evidence",
        why_not_escalated="policy_allows_auto_execution",
        why_escalated=None,
        uncertainty_reasons=[],
        policy_version="policy-v1",
    )
    second = build_canonical_decision_record(
        persisted_record=persisted_record,
        decision_result="auto_execute_and_notify",
        risk_class="none",
        action_ref="execute_recovery",
        matched_policy_rules=["registered_action"],
        decision_reason="registered action and complete evidence",
        why_not_escalated="policy_allows_auto_execution",
        why_escalated=None,
        uncertainty_reasons=[],
        policy_version="policy-v1",
    )

    stored_first = store.put(first)
    stored_second = store.put(second)

    assert stored_first.decision_key == stored_second.decision_key
    assert stored_first.decision_id == stored_second.decision_id
    assert store.list_records() == [stored_first]


def test_canonical_decision_record_carries_policy_and_fact_snapshot_evidence() -> None:
    record = build_canonical_decision_record(
        persisted_record=_record(fact_snapshot_version="fact-v9"),
        decision_result="block_and_alert",
        risk_class="hard_block",
        action_ref="continue_session",
        matched_policy_rules=["controlled_uncertainty"],
        decision_reason="mapping incomplete",
        why_not_escalated=None,
        why_escalated="controlled uncertainty requires block",
        uncertainty_reasons=["mapping_incomplete"],
        policy_version="policy-v2",
    )

    assert isinstance(record, CanonicalDecisionRecord)
    assert record.policy_version == "policy-v2"
    assert record.fact_snapshot_version == "fact-v9"
    assert record.operator_notes[0] == "decision=block_and_alert risk=hard_block action=continue_session"
    assert record.evidence["decision"]["decision_result"] == "block_and_alert"
    assert record.evidence["decision_reason"] == "mapping incomplete"
    assert record.evidence["why_escalated"] == "controlled uncertainty requires block"
    assert record.evidence["idempotency_key"] == record.decision_key
    assert record.evidence["operator_notes"] == record.operator_notes
    assert record.evidence["facts"][0]["fact_code"] == "recovery_available"


def test_brain_intent_adapter_keeps_runtime_disposition_compatible() -> None:
    auto_execute = brain_intent_to_runtime_disposition("propose_execute")
    auto_recovery = brain_intent_to_runtime_disposition("propose_recovery")
    require_approval = brain_intent_to_runtime_disposition("require_approval")
    suggest_only = brain_intent_to_runtime_disposition("suggest_only")

    assert auto_execute == "auto_execute_and_notify"
    assert auto_recovery == "auto_execute_and_notify"
    assert require_approval == "require_user_decision"
    assert suggest_only == "block_and_alert"


def test_canonical_decision_record_carries_brain_intent_alongside_runtime_disposition() -> None:
    record = build_canonical_decision_record(
        persisted_record=_record(),
        decision_result="auto_execute_and_notify",
        brain_intent="propose_execute",
        risk_class="none",
        action_ref="continue_session",
        matched_policy_rules=["registered_action"],
        decision_reason="registered action and complete evidence",
        why_not_escalated="policy_allows_auto_execution",
        why_escalated=None,
        uncertainty_reasons=[],
        policy_version="policy-v1",
    )

    assert record.brain_intent == "propose_execute"
    assert record.runtime_disposition == "auto_execute_and_notify"
    assert record.evidence["decision"]["brain_intent"] == "propose_execute"
    assert record.evidence["decision"]["runtime_disposition"] == "auto_execute_and_notify"


def test_policy_decision_store_serializes_concurrent_puts_across_instances(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store_path = tmp_path / "policy_decisions.json"
    seed_store = PolicyDecisionStore(store_path)
    seed_store.put(
        build_canonical_decision_record(
            persisted_record=_record(),
            decision_result="auto_execute_and_notify",
            brain_intent="propose_execute",
            risk_class="none",
            action_ref="continue_session",
            matched_policy_rules=["registered_action"],
            decision_reason="seed",
            why_not_escalated="policy_allows_auto_execution",
            why_escalated=None,
            uncertainty_reasons=[],
            policy_version="policy-v1",
        )
    )

    original_write_text = Path.write_text

    def slow_write_text(self: Path, data: str, *args, **kwargs) -> int:
        if self.parent == store_path.parent and self.name.startswith(f"{store_path.name}."):
            encoding = kwargs.get("encoding", "utf-8")
            midpoint = len(data) // 2
            with self.open("w", encoding=encoding) as handle:
                handle.write(data[:midpoint])
                handle.flush()
                time.sleep(0.01)
                handle.write(data[midpoint:])
                handle.flush()
            return len(data)
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", slow_write_text)

    errors: list[str] = []

    def writer(label: str) -> None:
        store = PolicyDecisionStore(store_path)
        for attempt in range(5):
            try:
                store.put(
                    build_canonical_decision_record(
                        persisted_record=_record(fact_snapshot_version=f"fact-v{attempt + 10}"),
                        decision_result="auto_execute_and_notify",
                        brain_intent="propose_execute",
                        risk_class="none",
                        action_ref=f"continue_session_{label}_{attempt}",
                        matched_policy_rules=["registered_action"],
                        decision_reason=f"{label}-{attempt}",
                        why_not_escalated="policy_allows_auto_execution",
                        why_escalated=None,
                        uncertainty_reasons=[],
                        policy_version="policy-v1",
                    )
                )
            except Exception as exc:  # pragma: no cover - captured for assertion
                errors.append(f"{type(exc).__name__}: {exc}")
                return

    left = threading.Thread(target=writer, args=("left",))
    right = threading.Thread(target=writer, args=("right",))
    left.start()
    right.start()
    left.join()
    right.join()

    assert errors == []
    records = PolicyDecisionStore(store_path).list_records()
    assert len(records) == 11


def test_policy_decision_store_keeps_previous_snapshot_when_atomic_replace_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store_path = tmp_path / "policy_decisions.json"
    store = PolicyDecisionStore(store_path)
    seed = build_canonical_decision_record(
        persisted_record=_record(),
        decision_result="auto_execute_and_notify",
        brain_intent="propose_execute",
        risk_class="none",
        action_ref="continue_session",
        matched_policy_rules=["registered_action"],
        decision_reason="seed",
        why_not_escalated="policy_allows_auto_execution",
        why_escalated=None,
        uncertainty_reasons=[],
        policy_version="policy-v1",
    )
    store.put(seed)

    original_replace = Path.replace

    def fail_replace(self: Path, target: Path) -> Path:
        if self.parent == store_path.parent and self.name.startswith(f"{store_path.name}."):
            raise OSError("atomic replace failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="atomic replace failed"):
        store.put(
            build_canonical_decision_record(
                persisted_record=_record(fact_snapshot_version="fact-v99"),
                decision_result="block_and_alert",
                brain_intent="suggest_only",
                risk_class="hard_block",
                action_ref="continue_session",
                matched_policy_rules=["controlled_uncertainty"],
                decision_reason="replace-fail",
                why_not_escalated=None,
                why_escalated="controlled uncertainty requires block",
                uncertainty_reasons=["mapping_incomplete"],
                policy_version="policy-v1",
            )
        )

    reparsed = PolicyDecisionStore(store_path).list_records()
    assert [record.decision_key for record in reparsed] == [seed.decision_key]
    assert list(tmp_path.glob("*.tmp")) == []
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert list(raw) == [seed.decision_key]


def test_policy_decision_store_reuses_cached_snapshot_until_file_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store_path = tmp_path / "policy_decisions.json"
    store = PolicyDecisionStore(store_path)
    seed = build_canonical_decision_record(
        persisted_record=_record(),
        decision_result="auto_execute_and_notify",
        brain_intent="propose_execute",
        risk_class="none",
        action_ref="continue_session",
        matched_policy_rules=["registered_action"],
        decision_reason="seed",
        why_not_escalated="policy_allows_auto_execution",
        why_escalated=None,
        uncertainty_reasons=[],
        policy_version="policy-v1",
    )
    store.put(seed)

    original_loads = json.loads
    load_calls = 0

    def counting_loads(*args, **kwargs):
        nonlocal load_calls
        load_calls += 1
        return original_loads(*args, **kwargs)

    monkeypatch.setattr(json, "loads", counting_loads)

    assert store.get(seed.decision_key) == seed
    assert store.get(seed.decision_key) == seed
    assert load_calls == 0

    replacement = build_canonical_decision_record(
        persisted_record=_record(fact_snapshot_version="fact-v8"),
        decision_result="block_and_alert",
        brain_intent="suggest_only",
        risk_class="hard_block",
        action_ref="continue_session",
        matched_policy_rules=["controlled_uncertainty"],
        decision_reason="replacement",
        why_not_escalated=None,
        why_escalated="controlled uncertainty requires block",
        uncertainty_reasons=["mapping_incomplete"],
        policy_version="policy-v1",
    )
    raw = original_loads(store_path.read_text(encoding="utf-8"))
    raw[replacement.decision_key] = replacement.model_dump(mode="json")
    store_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    assert store.get(replacement.decision_key) == replacement
    assert load_calls == 1
