#!/usr/bin/env sh
# Derive backend host/port/base-path/assistant-id from the single source of
# truth (config/config.yaml, read via `ops_pilot settings`) and export them as
# environment variables for the dev processes. Sourced by dev-web.sh and
# dev-copilot-runtime.sh so the backend address is never duplicated.
#
# Exports on success: BACKEND_HOST BACKEND_PORT CHAT_PATH ASSISTANT BACKEND_URL
# On any failure it stays silent; callers fall back to their own defaults.
#
# Sourced under `set -eu`, so every step is guarded to never abort the caller.

# When sourced, $0 is the caller. Prefer ROOT_DIR if the caller exported it.
_derive_root=${ROOT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}

_derived=$( (cd "$_derive_root/services/agent" 2>/dev/null && uv run ops_pilot settings 2>/dev/null) \
  | node -e 'try {
      const s = JSON.parse(require("fs").readFileSync(0, "utf8"));
      process.stdout.write(
        `BACKEND_HOST=${s.chat_host}\n` +
        `BACKEND_PORT=${s.chat_port}\n` +
        `CHAT_PATH=${s.chat_base_path}\n` +
        `ASSISTANT=${s.assistant_id}\n`
      );
    } catch (e) { process.exit(1); }' 2>/dev/null ) || _derived=""

if [ -n "$_derived" ]; then
  eval "$_derived"
  export BACKEND_HOST BACKEND_PORT CHAT_PATH ASSISTANT
  export BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"
fi
