#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SERVICE_DIR="$ROOT_DIR/services/agent"

if [ ! -f "$SERVICE_DIR/pyproject.toml" ]; then
  echo "Missing services/agent/pyproject.toml. Scaffold the Python agent service before running pnpm dev:backend." >&2
  exit 1
fi

cd "$SERVICE_DIR"

exec uv run ops_pilot serve --host "${CHAT_HOST:-127.0.0.1}" --port "${CHAT_PORT:-8123}"
