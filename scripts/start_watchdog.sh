#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${WATCHDOG_ENV_FILE:-$REPO_ROOT/.env.w}"

cd "$REPO_ROOT"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

exec uv run uvicorn watchdog.main:create_runtime_app \
  --host "${WATCHDOG_HOST:-127.0.0.1}" \
  --port "${WATCHDOG_PORT:-8720}" \
  --factory \
  --app-dir src
