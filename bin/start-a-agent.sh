#!/usr/bin/env sh
set -eu

SCRIPT_PATH=$0
case "$SCRIPT_PATH" in
  /*) ;;
  *) SCRIPT_PATH="$(pwd)/$SCRIPT_PATH" ;;
esac
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$SCRIPT_PATH")" && pwd)
APP_DIR=${APP_DIR:-$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)}

cd "$APP_DIR"

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

set -a
. "$APP_DIR/.env.a"
set +a

UV_BIN="${UV_BIN:-$(command -v uv || true)}"
if [ -z "$UV_BIN" ]; then
  echo "uv is required on PATH" >&2
  exit 1
fi

exec "$UV_BIN" run uvicorn a_control_agent.main:app \
  --host "$A_AGENT_HOST" \
  --port "$A_AGENT_PORT" \
  --app-dir src
