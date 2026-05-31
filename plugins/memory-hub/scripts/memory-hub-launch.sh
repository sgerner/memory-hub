#!/usr/bin/env bash
set -euo pipefail

env_file="${MEMORY_HUB_ENV_FILE:-$HOME/.config/memory-hub/agent.env}"

if [[ -f "$env_file" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
fi

: "${MEMORY_GATEWAY_URL:?MEMORY_GATEWAY_URL is not set}"
: "${MEMORY_GATEWAY_TOKEN:?MEMORY_GATEWAY_TOKEN is not set}"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec node "$script_dir/memory-hub-mcp.mjs"
