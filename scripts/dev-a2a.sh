#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SERVICE_DIR="$ROOT_DIR/services/agent"
A2A_HOST=${A2A_HOST:-127.0.0.1}
A2A_PORT=${A2A_PORT:-41241}

if [ ! -f "$SERVICE_DIR/pyproject.toml" ]; then
  echo "Missing services/agent/pyproject.toml. Scaffold the Python agent service before running pnpm dev:a2a." >&2
  exit 1
fi

cd "$SERVICE_DIR"

if [ -n "${A2A_SERVER_CMD:-}" ]; then
  exec sh -lc "$A2A_SERVER_CMD"
fi

exec uv run ops_pilot a2a serve --host "$A2A_HOST" --port "$A2A_PORT"
