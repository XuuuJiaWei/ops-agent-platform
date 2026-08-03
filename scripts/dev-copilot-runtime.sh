#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ ! -f "$ROOT_DIR/apps/copilot-runtime/package.json" ]; then
  echo "Missing apps/copilot-runtime/package.json. Scaffold the Copilot runtime before running pnpm dev:copilot." >&2
  exit 1
fi

cd "$ROOT_DIR"
if [ -z "${AGUI_AGENT_URL:-}" ] && [ -z "${AGENT_API_URL:-}" ]; then
  export AGUI_AGENT_URL=http://127.0.0.1:8123/chat
fi
exec pnpm --filter "./apps/copilot-runtime" dev
