#!/usr/bin/env sh
set -eu

exec /opt/homebrew/bin/cloudflared tunnel --url http://127.0.0.1:8710 --no-autoupdate
