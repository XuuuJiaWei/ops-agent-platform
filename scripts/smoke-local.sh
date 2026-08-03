#!/usr/bin/env sh
set -eu

pnpm run smoke:model
pnpm run smoke:agent
pnpm run smoke:a2a
