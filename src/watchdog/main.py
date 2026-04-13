from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from watchdog.api import approvals_proxy as approvals_proxy_routes
from watchdog.api import events_proxy as events_proxy_routes
from watchdog.api import metrics as metrics_routes
from watchdog.api import openclaw_bootstrap as openclaw_bootstrap_routes
from watchdog.api import openclaw_responses as openclaw_response_routes
from watchdog.api import ops as ops_routes
from watchdog.api import recover_watchdog as recover_watchdog_routes
from watchdog.api import progress as progress_routes
from watchdog.api import session_spine_actions as session_spine_actions_routes
from watchdog.api import session_spine_events as session_spine_events_routes
from watchdog.api import session_spine_queries as session_spine_query_routes
from watchdog.api import supervision as supervision_routes
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.services.approvals.service import ApprovalResponseStore, CanonicalApprovalStore
from watchdog.services.delivery.http_client import OpenClawDeliveryClient
from watchdog.services.delivery.openclaw_webhook_store import (
    OpenClawWebhookEndpointStore,
    openclaw_webhook_endpoint_state_path,
)
from watchdog.services.delivery.store import DeliveryOutboxStore
from watchdog.services.delivery.worker import DeliveryWorker
from watchdog.services.policy.decisions import PolicyDecisionStore
from watchdog.services.session_service import SessionService, SessionServiceStore
from watchdog.services.session_spine.orchestration_store import ResidentOrchestrationStateStore
from watchdog.services.session_spine.command_leases import CommandLeaseStore
from watchdog.services.session_spine.orchestrator import ResidentOrchestrator
from watchdog.services.session_spine.runtime import SessionSpineRuntime
from watchdog.services.session_spine.store import SessionSpineStore
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore
from watchdog.api.ops import build_ops_summary

logger = logging.getLogger(__name__)


def _run_background_step(step_name: str, fn, /, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        logger.exception("watchdog background step failed: %s", step_name)
        return None


async def _run_background_step_async(step_name: str, fn, /, *args, **kwargs):
    return await asyncio.to_thread(_run_background_step, step_name, fn, *args, **kwargs)


def _reconcile_stale_pending_approvals(app: FastAPI) -> int:
    reconciled = app.state.canonical_approval_store.reconcile_pending_records_against_decisions(
        app.state.policy_decision_store.list_records(),
        decided_by="policy-startup-reconcile",
    )
    deduped = app.state.canonical_approval_store.reconcile_duplicate_pending_records_by_approval_id(
        decided_by="policy-startup-approval-id-reconcile",
    )
    superseded = [*reconciled, *deduped]
    if superseded:
        updated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        app.state.delivery_outbox_store.supersede_records(
            envelope_reasons={
                record.envelope_id: next(
                    (
                        note
                        for note in reversed(record.operator_notes)
                        if note.startswith("approval_superseded_by_")
                    ),
                    "approval_superseded_by_reconcile",
                )
                for record in superseded
            },
            updated_at=updated_at,
        )
        logger.info(
            "watchdog startup superseded %s stale approvals and %s duplicate approvals",
            len(reconciled),
            len(deduped),
        )
    return len(superseded)


def _drain_delivery_outbox(app: FastAPI, *, now: datetime | None = None) -> None:
    current = now or datetime.now(UTC)
    while True:
        delivered = _run_background_step(
            "delivery_worker.process_next_ready",
            app.state.delivery_worker.process_next_ready,
            now=current,
        )
        if delivered is None:
            break


async def _run_session_spine_refresh_loop(app: FastAPI) -> None:
    interval_seconds = max(
        float(app.state.settings.session_spine_refresh_interval_seconds),
        0.01,
    )
    while True:
        await asyncio.sleep(interval_seconds)
        await _run_background_step_async(
            "session_spine_runtime.refresh_all",
            app.state.session_spine_runtime.refresh_all,
        )


async def _run_delivery_loop(app: FastAPI) -> None:
    interval_seconds = max(
        float(app.state.settings.delivery_worker_interval_seconds),
        0.01,
    )
    while True:
        await _run_background_step_async(
            "delivery_drain_outbox",
            _drain_delivery_outbox,
            app,
        )
        await asyncio.sleep(interval_seconds)


async def _run_resident_orchestrator_loop(app: FastAPI) -> None:
    interval_seconds = max(
        float(app.state.settings.resident_orchestrator_interval_seconds),
        0.01,
    )
    while True:
        await asyncio.sleep(interval_seconds)
        now = datetime.now(UTC)
        await _run_background_step_async(
            "resident_orchestrator.orchestrate_all",
            app.state.resident_orchestrator.orchestrate_all,
            now=now,
        )
        await _run_background_step_async(
            "delivery_drain_outbox",
            _drain_delivery_outbox,
            app,
            now=now,
        )


def create_app(
    settings: Settings | None = None,
    *,
    a_client: AControlAgentClient | None = None,
    start_background_workers: bool = False,
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        session_spine_loop_task: asyncio.Task[None] | None = None
        resident_orchestrator_task: asyncio.Task[None] | None = None
        delivery_loop_task: asyncio.Task[None] | None = None
        if start_background_workers:
            await _run_background_step_async(
                "canonical_approval_store.reconcile_pending_records_against_decisions",
                _reconcile_stale_pending_approvals,
                app,
            )
            await _run_background_step_async(
                "session_spine_runtime.refresh_all",
                app.state.session_spine_runtime.refresh_all,
            )
            session_spine_loop_task = asyncio.create_task(_run_session_spine_refresh_loop(app))
            now = datetime.now(UTC)
            await _run_background_step_async(
                "resident_orchestrator.orchestrate_all",
                app.state.resident_orchestrator.orchestrate_all,
                now=now,
            )
            resident_orchestrator_task = asyncio.create_task(_run_resident_orchestrator_loop(app))
            delivery_loop_task = asyncio.create_task(_run_delivery_loop(app))
            _run_background_step(
                "supervision.run_background_supervision",
                supervision_routes.run_background_supervision,
                app.state.settings,
                app.state.a_client,
            )
        try:
            yield
        finally:
            if session_spine_loop_task is not None:
                session_spine_loop_task.cancel()
                with suppress(asyncio.CancelledError):
                    await session_spine_loop_task
            if resident_orchestrator_task is not None:
                resident_orchestrator_task.cancel()
                with suppress(asyncio.CancelledError):
                    await resident_orchestrator_task
            if delivery_loop_task is not None:
                delivery_loop_task.cancel()
                with suppress(asyncio.CancelledError):
                    await delivery_loop_task

    app = FastAPI(title="Watchdog", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.a_client = a_client or AControlAgentClient(settings)
    app.state.action_receipt_store = ActionReceiptStore(
        Path(settings.data_dir) / "action_receipts.json"
    )
    app.state.policy_decision_store = PolicyDecisionStore(
        Path(settings.data_dir) / "policy_decisions.json"
    )
    app.state.canonical_approval_store = CanonicalApprovalStore(
        Path(settings.data_dir) / "canonical_approvals.json"
    )
    app.state.approval_response_store = ApprovalResponseStore(
        Path(settings.data_dir) / "approval_responses.json"
    )
    app.state.delivery_outbox_store = DeliveryOutboxStore(
        Path(settings.data_dir) / "delivery_outbox.json"
    )
    app.state.session_spine_store = SessionSpineStore(
        Path(settings.data_dir) / "session_spine.json"
    )
    app.state.session_service = SessionService(
        SessionServiceStore(Path(settings.data_dir) / "session_service.json")
    )
    app.state.command_lease_store = CommandLeaseStore(
        Path(settings.data_dir) / "command_leases.json",
        session_service=app.state.session_service,
    )
    app.state.openclaw_webhook_endpoint_store = OpenClawWebhookEndpointStore(
        openclaw_webhook_endpoint_state_path(settings)
    )
    app.state.delivery_client = OpenClawDeliveryClient(
        settings=settings,
        endpoint_store=app.state.openclaw_webhook_endpoint_store,
    )
    app.state.delivery_worker = DeliveryWorker(
        store=app.state.delivery_outbox_store,
        delivery_client=app.state.delivery_client,
        settings=settings,
        session_spine_store=app.state.session_spine_store,
        session_service=app.state.session_service,
    )
    app.state.session_spine_runtime = SessionSpineRuntime(
        client=app.state.a_client,
        store=app.state.session_spine_store,
    )
    app.state.resident_orchestration_state_store = ResidentOrchestrationStateStore(
        Path(settings.data_dir) / "resident_orchestrator.json"
    )
    app.state.resident_orchestrator = ResidentOrchestrator(
        settings=settings,
        client=app.state.a_client,
        session_spine_store=app.state.session_spine_store,
        decision_store=app.state.policy_decision_store,
        approval_store=app.state.canonical_approval_store,
        action_receipt_store=app.state.action_receipt_store,
        delivery_outbox_store=app.state.delivery_outbox_store,
        command_lease_store=app.state.command_lease_store,
        state_store=app.state.resident_orchestration_state_store,
        session_service=app.state.session_service,
    )
    app.include_router(progress_routes.router, prefix="/api/v1")
    app.include_router(events_proxy_routes.router, prefix="/api/v1")
    app.include_router(supervision_routes.router, prefix="/api/v1")
    app.include_router(approvals_proxy_routes.router, prefix="/api/v1")
    app.include_router(openclaw_bootstrap_routes.router, prefix="/api/v1")
    app.include_router(openclaw_response_routes.router, prefix="/api/v1")
    app.include_router(recover_watchdog_routes.router, prefix="/api/v1")
    app.include_router(session_spine_query_routes.router, prefix="/api/v1")
    app.include_router(session_spine_actions_routes.router, prefix="/api/v1")
    app.include_router(session_spine_events_routes.router, prefix="/api/v1")
    app.include_router(ops_routes.router, prefix="/api/v1")
    app.include_router(metrics_routes.router)

    @app.get("/healthz")
    def healthz() -> dict[str, int | str]:
        summary = build_ops_summary(
            data_dir=Path(app.state.settings.data_dir),
            settings=app.state.settings,
        )
        return {
            "status": summary.status,
            "active_alerts": summary.active_alerts,
        }

    return app


app = create_app()


def create_runtime_app() -> FastAPI:
    return create_app(start_background_workers=True)


def main() -> None:
    s = Settings()
    uvicorn.run(
        "watchdog.main:create_runtime_app",
        host=s.host,
        port=s.port,
        factory=True,
    )


if __name__ == "__main__":
    main()
