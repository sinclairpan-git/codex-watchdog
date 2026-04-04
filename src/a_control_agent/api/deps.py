from __future__ import annotations

from fastapi import Header, HTTPException, Request


def require_token(request: Request, authorization: str | None = Header(default=None)) -> None:
    settings = request.app.state.settings
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if token != settings.api_token:
        raise HTTPException(status_code=403, detail="invalid token")
