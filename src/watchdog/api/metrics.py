from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, Response

from watchdog.observability.metrics_export import PROM_CONTENT_TYPE, build_watchdog_metrics_text

router = APIRouter(tags=["watchdog"])


@router.get("/metrics")
def metrics(request: Request) -> Response:
    settings = request.app.state.settings
    data_dir = Path(settings.data_dir)
    body = build_watchdog_metrics_text(
        data_dir=data_dir,
        audit_path=data_dir / "audit.jsonl",
        settings=settings,
    )
    return Response(content=body, media_type=PROM_CONTENT_TYPE)
