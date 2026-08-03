#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SERVICE_DIR="$ROOT_DIR/services/agent"
BACKEND_HOST=${BACKEND_HOST:-${CHAT_HOST:-127.0.0.1}}
BACKEND_PORT=${BACKEND_PORT:-${CHAT_PORT:-8123}}

if [ ! -f "$SERVICE_DIR/pyproject.toml" ]; then
  echo "Missing services/agent/pyproject.toml. Scaffold the Python agent service before running pnpm dev:backend." >&2
  exit 1
fi

cd "$SERVICE_DIR"

if [ -n "${BACKEND_SERVER_CMD:-}" ]; then
  exec sh -lc "$BACKEND_SERVER_CMD"
fi

exec uv run ops_pilot serve --host "$BACKEND_HOST" --port "$BACKEND_PORT"
