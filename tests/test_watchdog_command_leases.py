from __future__ import annotations

from pathlib import Path

import pytest

from watchdog.services.session_spine.command_leases import CommandLeaseStore


def test_command_lease_store_records_canonical_claim_renew_expire_requeue_sequence(
    tmp_path: Path,
) -> None:
    store = CommandLeaseStore(tmp_path / "command_leases.json")

    claimed = store.claim_command(
        command_id="command:repo-a:1",
        session_id="session:repo-a",
        worker_id="worker:a",
        claimed_at="2026-04-12T00:00:00Z",
        lease_expires_at="2026-04-12T00:05:00Z",
    )
    renewed = store.renew_lease(
        command_id="command:repo-a:1",
        worker_id="worker:a",
        claim_seq=claimed.claim_seq,
        renewed_at="2026-04-12T00:02:00Z",
        lease_expires_at="2026-04-12T00:07:00Z",
    )
    expired = store.expire_and_requeue_expired(
        now="2026-04-12T00:07:00Z",
        reason="lease_timeout",
    )

    assert claimed.event_type == "command_claimed"
    assert renewed.event_type == "command_lease_renewed"
    assert [event.event_type for event in expired] == [
        "command_claim_expired",
        "command_requeued",
    ]

    events = store.list_events(command_id="command:repo-a:1")
    assert [event.event_type for event in events] == [
        "command_claimed",
        "command_lease_renewed",
        "command_claim_expired",
        "command_requeued",
    ]
    assert [event.claim_seq for event in events] == [1, 1, 1, 1]
    assert [event.worker_id for event in events] == [
        "worker:a",
        "worker:a",
        "worker:a",
        "worker:a",
    ]
    assert [event.lease_expires_at for event in events] == [
        "2026-04-12T00:05:00Z",
        "2026-04-12T00:07:00Z",
        "2026-04-12T00:07:00Z",
        "2026-04-12T00:07:00Z",
    ]

    state = store.get_command("command:repo-a:1")
    assert state is not None
    assert state.status == "requeued"
    assert state.claim_seq == 1
    assert state.worker_id == "worker:a"
    assert state.lease_expires_at == "2026-04-12T00:07:00Z"


def test_command_lease_store_accepts_terminal_result_for_current_claim(
    tmp_path: Path,
) -> None:
    store = CommandLeaseStore(tmp_path / "command_leases.json")

    claimed = store.claim_command(
        command_id="command:repo-a:2",
        session_id="session:repo-a",
        worker_id="worker:b",
        claimed_at="2026-04-12T01:00:00Z",
        lease_expires_at="2026-04-12T01:05:00Z",
    )
    executed = store.record_terminal_result(
        command_id="command:repo-a:2",
        worker_id="worker:b",
        claim_seq=claimed.claim_seq,
        result_type="command_executed",
        occurred_at="2026-04-12T01:03:00Z",
    )

    assert executed.event_type == "command_executed"
    assert executed.claim_seq == claimed.claim_seq
    state = store.get_command("command:repo-a:2")
    assert state is not None
    assert state.status == "executed"
    assert state.claim_seq == 1


def test_command_lease_store_rejects_late_result_from_stale_claim_generation(
    tmp_path: Path,
) -> None:
    store = CommandLeaseStore(tmp_path / "command_leases.json")

    first_claim = store.claim_command(
        command_id="command:repo-a:3",
        session_id="session:repo-a",
        worker_id="worker:c",
        claimed_at="2026-04-12T02:00:00Z",
        lease_expires_at="2026-04-12T02:05:00Z",
    )
    store.expire_and_requeue_expired(
        now="2026-04-12T02:05:00Z",
        reason="lease_timeout",
    )
    second_claim = store.claim_command(
        command_id="command:repo-a:3",
        session_id="session:repo-a",
        worker_id="worker:c",
        claimed_at="2026-04-12T02:06:00Z",
        lease_expires_at="2026-04-12T02:11:00Z",
    )

    with pytest.raises(ValueError, match="stale claim"):
        store.record_terminal_result(
            command_id="command:repo-a:3",
            worker_id="worker:c",
            claim_seq=first_claim.claim_seq,
            result_type="command_executed",
            occurred_at="2026-04-12T02:06:30Z",
        )

    state = store.get_command("command:repo-a:3")
    assert state is not None
    assert state.status == "claimed"
    assert state.claim_seq == second_claim.claim_seq == 2
    assert state.worker_id == "worker:c"

    events = store.list_events(command_id="command:repo-a:3")
    assert [event.event_type for event in events] == [
        "command_claimed",
        "command_claim_expired",
        "command_requeued",
        "command_claimed",
    ]


def test_command_lease_store_mirrors_lifecycle_events_into_session_service(
    tmp_path: Path,
) -> None:
    from watchdog.services.session_service.service import SessionService
    from watchdog.services.session_service.store import SessionServiceStore

    session_service = SessionService(SessionServiceStore(tmp_path / "session_service.json"))
    store = CommandLeaseStore(
        tmp_path / "command_leases.json",
        session_service=session_service,
    )

    first_claim = store.claim_command(
        command_id="command:repo-a:4",
        session_id="session:repo-a",
        worker_id="worker:d",
        claimed_at="2026-04-12T03:00:00Z",
        lease_expires_at="2026-04-12T03:05:00Z",
    )
    store.renew_lease(
        command_id="command:repo-a:4",
        worker_id="worker:d",
        claim_seq=first_claim.claim_seq,
        renewed_at="2026-04-12T03:02:00Z",
        lease_expires_at="2026-04-12T03:07:00Z",
    )
    store.expire_and_requeue_expired(
        now="2026-04-12T03:07:00Z",
        reason="lease_timeout",
    )
    second_claim = store.claim_command(
        command_id="command:repo-a:4",
        session_id="session:repo-a",
        worker_id="worker:d",
        claimed_at="2026-04-12T03:08:00Z",
        lease_expires_at="2026-04-12T03:13:00Z",
    )
    store.record_terminal_result(
        command_id="command:repo-a:4",
        worker_id="worker:d",
        claim_seq=second_claim.claim_seq,
        result_type="command_failed",
        occurred_at="2026-04-12T03:09:00Z",
    )

    events = [
        event
        for event in session_service.list_events(
            session_id="session:repo-a",
            related_id_key="command_id",
            related_id_value="command:repo-a:4",
        )
        if event.event_type != "command_created"
    ]

    assert [event.event_type for event in events] == [
        "command_claimed",
        "command_lease_renewed",
        "command_claim_expired",
        "command_requeued",
        "command_claimed",
        "command_failed",
    ]
    assert [event.related_ids["claim_seq"] for event in events] == [
        "1",
        "1",
        "1",
        "1",
        "2",
        "2",
    ]
    assert events[0].correlation_id == "corr:command:command:repo-a:4:claim:1"
    assert events[2].payload["reason"] == "lease_timeout"
    assert events[-1].payload["worker_id"] == "worker:d"
