from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response

from watchdog.api import approvals_proxy as approvals_proxy_routes
from watchdog.api import events_proxy as events_proxy_routes
from watchdog.api import recover_watchdog as recover_watchdog_routes
from watchdog.api import progress as progress_routes
from watchdog.api import session_spine_actions as session_spine_actions_routes
from watchdog.api import session_spine_queries as session_spine_query_routes
from watchdog.api import supervision as supervision_routes
from watchdog.observability.metrics_export import PROM_CONTENT_TYPE, build_watchdog_metrics_text
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.settings import Settings
from watchdog.storage.action_receipts import ActionReceiptStore


def create_app(
    settings: Settings | None = None,
    *,
    a_client: AControlAgentClient | None = None,
    start_background_workers: bool = False,
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_background_workers:
            supervision_routes.run_background_supervision(app.state.settings, app.state.a_client)
        yield

    app = FastAPI(title="Watchdog", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.a_client = a_client or AControlAgentClient(settings)
    app.state.action_receipt_store = ActionReceiptStore(
        Path(settings.data_dir) / "action_receipts.json"
    )
    app.include_router(progress_routes.router, prefix="/api/v1")
    app.include_router(events_proxy_routes.router, prefix="/api/v1")
    app.include_router(supervision_routes.router, prefix="/api/v1")
    app.include_router(approvals_proxy_routes.router, prefix="/api/v1")
    app.include_router(recover_watchdog_routes.router, prefix="/api/v1")
    app.include_router(session_spine_query_routes.router, prefix="/api/v1")
    app.include_router(session_spine_actions_routes.router, prefix="/api/v1")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    def metrics(request: Request) -> Response:
        s: Settings = request.app.state.settings
        body = build_watchdog_metrics_text(Path(s.data_dir) / "audit.jsonl")
        return Response(content=body, media_type=PROM_CONTENT_TYPE)

    return app


app = create_app()


def main() -> None:
    s = Settings()
    uvicorn.run(
        "watchdog.main:app",
        host=s.host,
        port=s.port,
        factory=False,
    )


if __name__ == "__main__":
    main()
