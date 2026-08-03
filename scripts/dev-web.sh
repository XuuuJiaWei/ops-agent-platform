#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WEB_WAIT_TIMEOUT=${WEB_WAIT_TIMEOUT:-120}
WEB_WAIT_FOR_BACKENDS=${WEB_WAIT_FOR_BACKENDS:-true}
WEB_WAIT_COPILOT_INFO_URL=${WEB_WAIT_COPILOT_INFO_URL:-http://127.0.0.1:4001/api/copilotkit}
WEB_WAIT_CHAT_HEALTH_URL=${WEB_WAIT_CHAT_HEALTH_URL:-http://127.0.0.1:8123/health}

if [ ! -f "$ROOT_DIR/apps/web/package.json" ]; then
  echo "Missing apps/web/package.json. Scaffold the frontend before running pnpm dev:web." >&2
  exit 1
fi

wait_for_url() {
  label=$1
  url=$2
  timeout=$3
  start=$(date +%s)

  echo "Waiting for $label at $url ..."
  while true; do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      echo "$label is ready."
      return 0
    fi

    now=$(date +%s)
    elapsed=$((now - start))
    if [ "$elapsed" -ge "$timeout" ]; then
      echo "Timed out waiting for $label at $url after ${timeout}s." >&2
      return 1
    fi

    sleep 1
  done
}

wait_for_copilot_runtime() {
  label=$1
  url=$2
  timeout=$3
  start=$(date +%s)

  echo "Waiting for $label at $url ..."
  while true; do
    if curl -fsS --max-time 2 \
      -H 'Content-Type: application/json' \
      --data '{"method":"info"}' \
      "$url" >/dev/null 2>&1; then
      echo "$label is ready."
      return 0
    fi

    now=$(date +%s)
    elapsed=$((now - start))
    if [ "$elapsed" -ge "$timeout" ]; then
      echo "Timed out waiting for $label at $url after ${timeout}s." >&2
      return 1
    fi

    sleep 1
  done
}

case "$WEB_WAIT_FOR_BACKENDS" in
  true|1|yes)
    wait_for_copilot_runtime "Copilot runtime" "$WEB_WAIT_COPILOT_INFO_URL" "$WEB_WAIT_TIMEOUT"
    wait_for_url "Backend" "$WEB_WAIT_CHAT_HEALTH_URL" "$WEB_WAIT_TIMEOUT"
    ;;
esac

cd "$ROOT_DIR"
exec pnpm --filter "./apps/web" dev:vite
