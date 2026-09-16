#!/usr/bin/env bash
# Start Chaos Control locally. Reads .env if present.
set -e
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
: "${PORT:=8000}"
exec python3 -m uvicorn chaos.app:app --host 127.0.0.1 --port "$PORT" "$@"
