#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ ! -f "$ROOT_DIR/apps/copilot-runtime/package.json" ]; then
  echo "Missing apps/copilot-runtime/package.json. Scaffold the Copilot runtime before running pnpm dev:copilot." >&2
  exit 1
fi

cd "$ROOT_DIR"

# Derive backend chat URL and assistant id from config/config.yaml (single
# source of truth). Falls back to hardcoded defaults if derivation fails.
. "$ROOT_DIR/scripts/derive-backend-env.sh"
if [ -n "${BACKEND_URL:-}" ]; then
  : "${AGUI_AGENT_URL:=${BACKEND_URL}${CHAT_PATH}}"
  : "${ASSISTANT_ID:=${ASSISTANT}}"
fi
: "${AGUI_AGENT_URL:=http://127.0.0.1:8123/chat}"
export AGUI_AGENT_URL
[ -n "${ASSISTANT_ID:-}" ] && export ASSISTANT_ID
[ -n "${OPS_PILOT_PERSISTENCE_BACKEND:-}" ] && export OPS_PILOT_PERSISTENCE_BACKEND
[ -n "${OPS_PILOT_PERSISTENCE_SETUP_ON_START:-}" ] && export OPS_PILOT_PERSISTENCE_SETUP_ON_START

exec pnpm --filter "./apps/copilot-runtime" dev
