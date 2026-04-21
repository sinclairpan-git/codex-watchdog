from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response

from a_control_agent.api import approvals as approvals_routes
from a_control_agent.api import recovery as recovery_routes
from a_control_agent.api import tasks as tasks_routes
from a_control_agent.observability.metrics_export import PROM_CONTENT_TYPE, build_a_metrics_text
from a_control_agent.services.codex.app_server_bridge import CodexAppServerBridge
from a_control_agent.services.codex.client import CodexClient, LocalCodexClient, NoOpCodexClient
from a_control_agent.services.codex.stdio_transport import SubprocessCodexTransport
from a_control_agent.settings import Settings
from a_control_agent.storage.approvals_store import ApprovalsStore
from a_control_agent.storage.tasks_store import TaskStore
from watchdog.services.session_spine.task_state import normalize_task_status


def _preserve_operator_paused_status(
    task_store: TaskStore,
    session: dict[str, object],
) -> dict[str, object]:
    thread_id = str(session.get("thread_id") or "").strip()
    if not thread_id:
        return session
    existing = task_store.get_by_thread(thread_id)
    if not isinstance(existing, dict):
        return session
    if normalize_task_status(existing) != "paused":
        return session
    incoming_status = normalize_task_status(session)
    if incoming_status in {"completed", "failed", "paused"}:
        return session
    guarded = dict(session)
    guarded["status"] = "paused"
    guarded["phase"] = str(existing.get("phase") or session.get("phase") or "planning")
    if "pending_approval" not in guarded:
        guarded["pending_approval"] = bool(existing.get("pending_approval"))
    if guarded.get("approval_risk") in (None, "") and existing.get("approval_risk") not in (None, ""):
        guarded["approval_risk"] = existing.get("approval_risk")
    return guarded


async def _sync_codex_threads(app: FastAPI) -> None:
    client = app.state.codex_client
    try:
        if not client.ping():
            return
        sessions = client.list_threads()
    except Exception:
        return
    if not isinstance(sessions, list):
        return
    ordered = [dict(session) for session in sessions if isinstance(session, dict)]
    ordered.sort(key=lambda session: str(session.get("last_progress_at") or session.get("thread_id") or ""))
    for session in ordered:
        session = _preserve_operator_paused_status(app.state.task_store, session)
        app.state.task_store.upsert_native_thread(session)


async def _run_codex_sync_loop(app: FastAPI) -> None:
    interval = max(float(app.state.settings.codex_sync_interval_seconds), 0.01)
    while True:
        await asyncio.sleep(interval)
        await _sync_codex_threads(app)


def build_default_codex_bridge(
    settings: Settings,
    *,
    task_store: TaskStore,
    approvals_store: ApprovalsStore,
) -> CodexAppServerBridge:
    bridge_ref: dict[str, CodexAppServerBridge] = {}

    async def handle_server_request(message: dict[str, object]) -> None:
        bridge = bridge_ref.get("bridge")
        if bridge is None:
            return
        await bridge.ingest_server_request(dict(message))

    transport = SubprocessCodexTransport(
        command=settings.codex_bridge_command,
        server_request_handler=handle_server_request,
        request_timeout_seconds=float(settings.codex_bridge_request_timeout_seconds),
    )
    bridge = CodexAppServerBridge(
        transport=transport,
        approvals_store=approvals_store,
        task_store=task_store,
        audit_path=Path(settings.data_dir) / "audit.jsonl",
    )
    bridge_ref["bridge"] = bridge
    return bridge


def create_app(
    settings: Settings | None = None,
    *,
    codex_client: CodexClient | None = None,
    codex_bridge: CodexAppServerBridge | None = None,
    start_background_workers: bool = False,
) -> FastAPI:
    settings = settings or Settings()
    base = Path(settings.data_dir)
    store_path = base / "tasks_store.json"
    task_store = TaskStore(store_path)
    approvals_store = ApprovalsStore(base / "approvals.json")
    bridge = codex_bridge
    if bridge is None and settings.codex_bridge_enabled:
        bridge = build_default_codex_bridge(
            settings,
            task_store=task_store,
            approvals_store=approvals_store,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop_task: asyncio.Task[None] | None = None
        bridge = app.state.codex_bridge
        if bridge is not None:
            await bridge.start()
        if start_background_workers:
            await _sync_codex_threads(app)
            loop_task = asyncio.create_task(_run_codex_sync_loop(app))
        try:
            yield
        finally:
            if loop_task is not None:
                loop_task.cancel()
                with suppress(asyncio.CancelledError):
                    await loop_task
            if bridge is not None:
                await bridge.stop()

    app = FastAPI(title="A-Control-Agent", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.task_store = task_store
    app.state.approvals_store = approvals_store
    app.state.codex_bridge = bridge
    if codex_client is not None:
        app.state.codex_client = codex_client
    else:
        local_client = LocalCodexClient(settings.codex_home)
        app.state.codex_client = local_client if local_client.ping() else NoOpCodexClient()
    app.include_router(tasks_routes.router, prefix="/api/v1")
    app.include_router(approvals_routes.router, prefix="/api/v1")
    app.include_router(recovery_routes.router, prefix="/api/v1")

    @app.get("/healthz")
    def healthz() -> dict[str, int | str]:
        return {
            "status": "ok",
            "tracked_threads": app.state.task_store.count_tasks(),
            "tracked_projects": app.state.task_store.count_projects(),
        }

    @app.get("/metrics")
    def metrics(request: Request) -> Response:
        s: Settings = request.app.state.settings
        b = Path(s.data_dir)
        body = build_a_metrics_text(
            request.app.state.task_store,
            b / "audit.jsonl",
            approvals_audit_path=b / "approvals_audit.jsonl",
        )
        return Response(content=body, media_type=PROM_CONTENT_TYPE)

    return app


app = create_app(start_background_workers=True)


def main() -> None:
    s = Settings()
    uvicorn.run(
        "a_control_agent.main:app",
        host=s.host,
        port=s.port,
        factory=False,
    )


if __name__ == "__main__":
    main()
