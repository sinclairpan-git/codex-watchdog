from __future__ import annotations

import asyncio
import inspect
import logging
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from watchdog.api import approvals_proxy as approvals_proxy_routes
from watchdog.api import events_proxy as events_proxy_routes
from watchdog.api import feishu_control as feishu_control_routes
from watchdog.api import feishu_ingress as feishu_ingress_routes
from watchdog.api import memory_hub_preview as memory_hub_preview_routes
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
from watchdog.services.approvals.service import (
    ApprovalResponseStore,
    CanonicalApprovalStore,
    expire_pending_canonical_approvals,
)
from watchdog.services.delivery.http_client import OpenClawDeliveryClient
from watchdog.services.delivery.feishu_client import FeishuAppDeliveryClient
from watchdog.services.delivery.openclaw_webhook_store import (
    OpenClawWebhookEndpointStore,
    openclaw_webhook_endpoint_state_path,
)
from watchdog.services.delivery.store import DeliveryOutboxStore
from watchdog.services.delivery.worker import DeliveryWorker
from watchdog.services.future_worker.service import FutureWorkerExecutionService
from watchdog.services.brain.service import BrainDecisionService
from watchdog.services.memory_hub.ingest_queue import (
    MemoryIngestEnqueuer,
    MemoryIngestEnqueueFailureStore,
    MemoryIngestQueueStore,
)
from watchdog.services.memory_hub.ingest_worker import MemoryIngestWorker
from watchdog.services.memory_hub.service import MemoryHubService
from watchdog.services.policy.decisions import PolicyDecisionStore
from watchdog.services.resident_experts.service import ResidentExpertRuntimeService
from watchdog.services.session_service import SessionService, SessionServiceStore
from watchdog.services.session_spine.orchestration_store import ResidentOrchestrationStateStore
from watchdog.services.session_spine.command_leases import CommandLeaseStore
from watchdog.services.session_spine.orchestrator import ResidentOrchestrator
from watchdog.services.session_spine.runtime import SessionSpineRuntime
from watchdog.services.session_spine.store import SessionSpineStore
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore
from watchdog.api.ops import build_ops_health_summary

logger = logging.getLogger(__name__)


def _run_background_step(step_name: str, fn, /, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        logger.exception("watchdog background step failed: %s", step_name)
        return None


def _resident_orchestrator_call_kwargs(orchestrate_all) -> dict[str, object]:
    try:
        signature = inspect.signature(orchestrate_all)
    except (TypeError, ValueError):
        return {}
    if "continue_on_error" in signature.parameters:
        return {"continue_on_error": True}
    if any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        return {"continue_on_error": True}
    return {}


def _run_resident_orchestrator_step(orchestrate_all, *, now: datetime):
    return orchestrate_all(now=now, **_resident_orchestrator_call_kwargs(orchestrate_all))


def _build_delivery_client(
    *,
    settings: Settings,
    openclaw_endpoint_store: OpenClawWebhookEndpointStore,
):
    transport = str(settings.delivery_transport or "").strip()
    if transport in {"feishu", "feishu-app"}:
        return FeishuAppDeliveryClient(settings=settings)
    if transport == "openclaw":
        return OpenClawDeliveryClient(
            settings=settings,
            endpoint_store=openclaw_endpoint_store,
        )
    raise ValueError(f"unsupported delivery_transport: {transport or '<empty>'}")


async def _run_background_step_async(step_name: str, fn, /, *args, **kwargs):
    return await asyncio.to_thread(_run_background_step, step_name, fn, *args, **kwargs)


def _delivery_run_lock(app: FastAPI) -> asyncio.Lock:
    existing = getattr(app.state, "delivery_run_lock", None)
    if existing is not None:
        return existing
    created = asyncio.Lock()
    app.state.delivery_run_lock = created
    return created


def _reconcile_stale_pending_approvals(app: FastAPI) -> int:
    reconciled = app.state.canonical_approval_store.reconcile_pending_records_against_decisions(
        app.state.policy_decision_store.list_records(),
        decided_by="policy-startup-reconcile",
    )
    deduped = app.state.canonical_approval_store.reconcile_duplicate_pending_records_by_approval_id(
        decided_by="policy-startup-approval-id-reconcile",
    )
    deduped_by_action_signature = (
        app.state.canonical_approval_store.reconcile_duplicate_pending_records_by_action_signature(
            decided_by="policy-startup-action-signature-reconcile",
        )
    )
    expired = expire_pending_canonical_approvals(
        approval_store=app.state.canonical_approval_store,
        session_service=app.state.session_service,
        now=datetime.now(UTC),
        expiration_seconds=float(app.state.settings.approval_expiration_seconds),
    )
    reconciled_records = [*reconciled, *deduped, *deduped_by_action_signature, *expired]
    if reconciled_records:
        updated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        app.state.delivery_outbox_store.supersede_records(
            envelope_reasons={
                record.envelope_id: next(
                    (
                        note
                        for note in reversed(record.operator_notes)
                        if note.startswith("approval_superseded_by_")
                        or note.startswith("approval_expired_by_timeout")
                    ),
                    "approval_state_reconciled",
                )
                for record in reconciled_records
            },
            updated_at=updated_at,
        )
        logger.info(
            "watchdog startup reconciled approvals: stale=%s duplicate=%s action_signature=%s expired=%s",
            len(reconciled),
            len(deduped),
            len(deduped_by_action_signature),
            len(expired),
        )
    return len(reconciled_records)


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


def _drain_memory_ingest_queue(app: FastAPI) -> None:
    while app.state.memory_ingest_worker.process_next():
        continue


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
        await _run_delivery_drain_once(app)
        await asyncio.sleep(interval_seconds)


async def _run_memory_ingest_loop(app: FastAPI) -> None:
    interval_seconds = max(
        float(app.state.settings.memory_ingest_worker_interval_seconds),
        0.01,
    )
    while True:
        await _run_background_step_async(
            "memory_ingest_drain_queue",
            _drain_memory_ingest_queue,
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
        await _run_resident_orchestrator_once(app, now=datetime.now(UTC))


async def _run_startup_orchestrator_once(app: FastAPI) -> None:
    await _run_resident_orchestrator_once(app, now=datetime.now(UTC))


async def _run_resident_orchestrator_once(
    app: FastAPI,
    *,
    now: datetime,
) -> None:
    async with app.state.resident_orchestrator_run_lock:
        outcomes = await _run_background_step_async(
            "resident_orchestrator.orchestrate_all",
            _run_resident_orchestrator_step,
            app.state.resident_orchestrator.orchestrate_all,
            now=now,
        )
        if outcomes is None:
            logger.error("resident orchestrator step failed; skipping delivery drain")
            return
        await _run_delivery_drain_once(app, now=now)


async def _run_delivery_drain_once(
    app: FastAPI,
    *,
    now: datetime | None = None,
) -> None:
    async with _delivery_run_lock(app):
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
        startup_reconcile_task: asyncio.Task[object] | None = None
        session_spine_loop_task: asyncio.Task[None] | None = None
        startup_orchestrator_task: asyncio.Task[None] | None = None
        resident_orchestrator_task: asyncio.Task[None] | None = None
        memory_ingest_loop_task: asyncio.Task[None] | None = None
        delivery_loop_task: asyncio.Task[None] | None = None
        if start_background_workers:
            startup_reconcile_task = asyncio.create_task(
                _run_background_step_async(
                    "canonical_approval_store.reconcile_pending_records_against_decisions",
                    _reconcile_stale_pending_approvals,
                    app,
                )
            )
            await _run_background_step_async(
                "session_spine_runtime.refresh_all",
                app.state.session_spine_runtime.refresh_all,
            )
            await _run_background_step_async(
                "memory_ingest_queue.recover_inflight",
                app.state.memory_ingest_queue_store.recover_inflight,
            )
            await _run_background_step_async(
                "memory_ingest_drain_queue",
                _drain_memory_ingest_queue,
                app,
            )
            session_spine_loop_task = asyncio.create_task(_run_session_spine_refresh_loop(app))
            memory_ingest_loop_task = asyncio.create_task(_run_memory_ingest_loop(app))
            await startup_reconcile_task
            startup_orchestrator_task = asyncio.create_task(
                _run_startup_orchestrator_once(app)
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
            if startup_reconcile_task is not None:
                startup_reconcile_task.cancel()
                with suppress(asyncio.CancelledError):
                    await startup_reconcile_task
            if session_spine_loop_task is not None:
                session_spine_loop_task.cancel()
                with suppress(asyncio.CancelledError):
                    await session_spine_loop_task
            if startup_orchestrator_task is not None:
                startup_orchestrator_task.cancel()
                with suppress(asyncio.CancelledError):
                    await startup_orchestrator_task
            if resident_orchestrator_task is not None:
                resident_orchestrator_task.cancel()
                with suppress(asyncio.CancelledError):
                    await resident_orchestrator_task
            if memory_ingest_loop_task is not None:
                memory_ingest_loop_task.cancel()
                with suppress(asyncio.CancelledError):
                    await memory_ingest_loop_task
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
    app.state.memory_hub_service = MemoryHubService.from_data_dir(
        settings.data_dir,
        preview_contract_overrides=settings.build_memory_preview_contract_overrides(),
    )
    app.state.resident_expert_runtime_service = ResidentExpertRuntimeService.from_data_dir(
        settings.data_dir,
        stale_after_seconds=settings.resident_expert_stale_after_seconds,
    )
    app.state.resident_expert_runtime_service.ensure_registry()
    app.state.memory_ingest_queue_store = MemoryIngestQueueStore(
        Path(settings.data_dir) / "memory_ingest_queue.json"
    )
    app.state.memory_ingest_enqueue_failure_store = MemoryIngestEnqueueFailureStore(
        Path(settings.data_dir) / "memory_ingest_enqueue_failures.json"
    )
    app.state.memory_ingest_enqueuer = MemoryIngestEnqueuer(
        queue_store=app.state.memory_ingest_queue_store,
        failure_store=app.state.memory_ingest_enqueue_failure_store,
    )
    app.state.session_service = SessionService(
        SessionServiceStore(Path(settings.data_dir) / "session_service.json"),
        event_listeners=[app.state.memory_ingest_enqueuer.enqueue_event],
    )
    app.state.memory_ingest_worker = MemoryIngestWorker(
        store=app.state.memory_ingest_queue_store,
        memory_hub_service=app.state.memory_hub_service,
        max_attempts=settings.memory_ingest_max_attempts,
        initial_backoff_seconds=settings.memory_ingest_initial_backoff_seconds,
    )
    app.state.command_lease_store = CommandLeaseStore(
        Path(settings.data_dir) / "command_leases.json",
        session_service=app.state.session_service,
    )
    app.state.future_worker_service = FutureWorkerExecutionService(
        app.state.session_service,
    )
    app.state.openclaw_webhook_endpoint_store = OpenClawWebhookEndpointStore(
        openclaw_webhook_endpoint_state_path(settings)
    )
    app.state.delivery_client = _build_delivery_client(
        settings=settings,
        openclaw_endpoint_store=app.state.openclaw_webhook_endpoint_store,
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
        future_worker_service=app.state.future_worker_service,
        brain_service=BrainDecisionService(
            settings=settings,
            memory_hub_service=app.state.memory_hub_service,
            session_service=app.state.session_service,
        ),
        resident_expert_runtime_service=app.state.resident_expert_runtime_service,
    )
    app.state.resident_orchestrator_run_lock = asyncio.Lock()
    app.state.delivery_run_lock = asyncio.Lock()
    app.include_router(progress_routes.router, prefix="/api/v1")
    app.include_router(events_proxy_routes.router, prefix="/api/v1")
    app.include_router(feishu_control_routes.router, prefix="/api/v1")
    app.include_router(feishu_ingress_routes.router, prefix="/api/v1")
    app.include_router(memory_hub_preview_routes.router, prefix="/api/v1")
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
        return build_ops_health_summary(
            data_dir=Path(app.state.settings.data_dir),
            settings=app.state.settings,
            decision_store=app.state.policy_decision_store,
            approval_store=app.state.canonical_approval_store,
            delivery_store=app.state.delivery_outbox_store,
            receipt_store=app.state.action_receipt_store,
        )

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
