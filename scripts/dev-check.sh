#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
missing=0

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing command: $1" >&2
    missing=1
  fi
}

need_file() {
  if [ ! -f "$ROOT_DIR/$1" ]; then
    echo "Missing file: $1" >&2
    missing=1
  fi
}

need_cmd node
need_cmd pnpm
need_cmd uv

need_file package.json
need_file pnpm-workspace.yaml
need_file config/config.example.yaml
need_file apps/web/package.json
need_file apps/copilot-runtime/package.json
need_file services/agent/pyproject.toml

if [ "$missing" -ne 0 ]; then
  echo "Local stack is not fully scaffolded yet. Add apps/web, apps/copilot-runtime, and services/agent before running pnpm dev." >&2
  exit 1
fi

echo "Local development preflight passed."
