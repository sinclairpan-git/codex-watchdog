#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${WATCHDOG_ENV_FILE:-$REPO_ROOT/.env.w}"

export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/v24.11.1/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

cd "$REPO_ROOT"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

UV_BIN="${UV_BIN:-$(command -v uv || true)}"
if [[ -z "$UV_BIN" ]]; then
  echo "uv not found on PATH" >&2
  exit 127
fi

exec "$UV_BIN" run uvicorn watchdog.main:create_runtime_app \
  --host "${WATCHDOG_HOST:-127.0.0.1}" \
  --port "${WATCHDOG_PORT:-8720}" \
  --factory \
  --app-dir src
