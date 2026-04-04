from __future__ import annotations

import uvicorn
from pathlib import Path

from fastapi import FastAPI, Request, Response

from watchdog.api import approvals_proxy as approvals_proxy_routes
from watchdog.api import recover_watchdog as recover_watchdog_routes
from watchdog.api import progress as progress_routes
from watchdog.api import supervision as supervision_routes
from watchdog.observability.metrics_export import PROM_CONTENT_TYPE, build_watchdog_metrics_text
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Watchdog", version="0.1.0")
    app.state.settings = settings
    app.state.a_client = AControlAgentClient(settings)
    app.include_router(progress_routes.router, prefix="/api/v1")
    app.include_router(supervision_routes.router, prefix="/api/v1")
    app.include_router(approvals_proxy_routes.router, prefix="/api/v1")
    app.include_router(recover_watchdog_routes.router, prefix="/api/v1")

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
