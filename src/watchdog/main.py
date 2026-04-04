from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from watchdog.api import progress as progress_routes
from watchdog.api import supervision as supervision_routes
from watchdog.services.a_client.client import AControlAgentClient
from watchdog.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Watchdog", version="0.1.0")
    app.state.settings = settings
    app.state.a_client = AControlAgentClient(settings)
    app.include_router(progress_routes.router, prefix="/api/v1")
    app.include_router(supervision_routes.router, prefix="/api/v1")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

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
