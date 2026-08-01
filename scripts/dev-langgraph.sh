#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SERVICE_DIR="$ROOT_DIR/services/agent"
LANGGRAPH_HOST=${LANGGRAPH_HOST:-127.0.0.1}
LANGGRAPH_PORT=${LANGGRAPH_PORT:-2024}
LANGGRAPH_STUDIO_URL=${LANGGRAPH_STUDIO_URL:-http://localhost:3000}
LANGGRAPH_RELOAD=${LANGGRAPH_RELOAD:-false}
if [ -z "${LANGGRAPH_CLI_SPEC:-}" ]; then
  LANGGRAPH_CLI_SPEC='langgraph-cli[inmem]>=0.4.31,<1'
fi

if [ ! -f "$SERVICE_DIR/pyproject.toml" ]; then
  echo "Missing services/agent/pyproject.toml. Scaffold the Python agent service before running pnpm dev:langgraph." >&2
  exit 1
fi

if [ ! -f "$SERVICE_DIR/langgraph.json" ]; then
  echo "Missing services/agent/langgraph.json. LangGraph dev needs a local graph config." >&2
  exit 1
fi

cd "$SERVICE_DIR"

# Keep local development fully local. Do not open LangSmith Studio in the
# browser, and do not enable LangSmith/LangChain tracing from this wrapper.
export LANGGRAPH_NO_VERSION_CHECK=${LANGGRAPH_NO_VERSION_CHECK:-true}
export LANGSMITH_TRACING=${LANGSMITH_TRACING:-false}
export LANGCHAIN_TRACING_V2=${LANGCHAIN_TRACING_V2:-false}

if [ -n "${LANGGRAPH_DEV_CMD:-}" ]; then
  exec sh -lc "$LANGGRAPH_DEV_CMD"
fi

RELOAD_ARGS="--no-reload"
if [ "$LANGGRAPH_RELOAD" = "true" ]; then
  RELOAD_ARGS=""
fi

# The in-memory LangGraph dev server writes .langgraph_api/*.pckl files under
# services/agent. Disabling reload by default keeps long local chat runs stable.
# Set LANGGRAPH_RELOAD=true when actively editing backend code.
# shellcheck disable=SC2086

exec uv run --with "$LANGGRAPH_CLI_SPEC" langgraph dev \
  --host "$LANGGRAPH_HOST" \
  --port "$LANGGRAPH_PORT" \
  --studio-url "$LANGGRAPH_STUDIO_URL" \
  --no-browser \
  $RELOAD_ARGS
