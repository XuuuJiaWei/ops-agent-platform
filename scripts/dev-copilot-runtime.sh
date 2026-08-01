#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ ! -f "$ROOT_DIR/apps/copilot-runtime/package.json" ]; then
  echo "Missing apps/copilot-runtime/package.json. Scaffold the Copilot runtime before running pnpm dev:copilot." >&2
  exit 1
fi

cd "$ROOT_DIR"
exec pnpm --filter "./apps/copilot-runtime" dev
