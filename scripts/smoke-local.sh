#!/usr/bin/env sh
set -eu

if [ -n "${SMOKE_LOCAL_CMD:-}" ]; then
  exec sh -lc "$SMOKE_LOCAL_CMD"
fi

pnpm run smoke:model
pnpm run smoke:agent
pnpm run smoke:a2a
