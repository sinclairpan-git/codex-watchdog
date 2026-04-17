from __future__ import annotations

import subprocess
import sys


def resolve_secret_value(
    *,
    explicit_value: str | None,
    keychain_service: str | None = None,
    keychain_account: str | None = None,
) -> str | None:
    normalized_explicit = _normalize(explicit_value)
    if normalized_explicit is not None:
        return normalized_explicit

    service = _normalize(keychain_service)
    account = _normalize(keychain_account)
    if service is None or account is None:
        return None
    return _load_macos_keychain_secret(service=service, account=account)


def _normalize(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _load_macos_keychain_secret(*, service: str, account: str) -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-w",
                "-s",
                service,
                "-a",
                account,
            ],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return _normalize(result.stdout)
