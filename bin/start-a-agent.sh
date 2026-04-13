#!/bin/zsh
set -euo pipefail

export PATH="/Users/sinclairpan/.local/bin:/Users/sinclairpan/.nvm/versions/node/v24.11.1/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

APP_DIR="/Users/sinclairpan/project/openclaw-codex-watchdog"
cd "$APP_DIR"

set -a
source "$APP_DIR/.env.a"
set +a

exec /Users/sinclairpan/.local/bin/uv run uvicorn a_control_agent.main:app \
  --host "$A_AGENT_HOST" \
  --port "$A_AGENT_PORT" \
  --app-dir src
