from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI

from a_control_agent.api import approvals as approvals_routes
from a_control_agent.api import tasks as tasks_routes
from a_control_agent.settings import Settings
from a_control_agent.storage.approvals_store import ApprovalsStore
from a_control_agent.storage.tasks_store import TaskStore


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    base = Path(settings.data_dir)
    store_path = base / "tasks_store.json"
    app = FastAPI(title="A-Control-Agent", version="0.1.0")
    app.state.settings = settings
    app.state.task_store = TaskStore(store_path)
    app.state.approvals_store = ApprovalsStore(base / "approvals.json")
    app.include_router(tasks_routes.router, prefix="/api/v1")
    app.include_router(approvals_routes.router, prefix="/api/v1")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()


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
