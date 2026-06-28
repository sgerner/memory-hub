#!/bin/sh
set -eu

apk add --no-cache git >/dev/null

cd /app

branch="${MEMORY_HUB_UPDATE_BRANCH:-main}"
interval="${MEMORY_HUB_UPDATE_INTERVAL_SECONDS:-900}"
targets="${MEMORY_HUB_UPDATE_SERVICES:-}"
repo_url="${MEMORY_HUB_UPDATE_REPO_URL:-https://github.com/sgerner/memory-hub.git}"

log() {
  printf '%s\n' "$*"
}

rebuild_stack() {
  log "Pulling latest changes from ${repo_url} (${branch})..."
  git pull --ff-only "$repo_url" "$branch"

  if [ -n "$targets" ]; then
    # shellcheck disable=SC2086
    set -- $targets
    log "Rebuilding targeted services: $targets"
    docker compose up -d --build "$@"
  else
    targets="$(docker compose config --services | grep -v '^memory-hub-updater$' | tr '\n' ' ' | sed 's/[[:space:]]*$//')"
    if [ -z "$targets" ]; then
      log "No active compose services found to rebuild."
      return 0
    fi
    # shellcheck disable=SC2086
    set -- $targets
    log "Rebuilding active compose services: $targets"
    docker compose up -d --build "$@"
  fi
}

while :; do
  remote_sha="$(git ls-remote "$repo_url" "refs/heads/${branch}" | awk 'NR==1 { print $1 }')"
  local_sha="$(git rev-parse HEAD 2>/dev/null || true)"

  if [ -z "$remote_sha" ]; then
    log "Could not resolve origin/${branch}; retrying in ${interval}s."
  elif [ -z "$local_sha" ]; then
    log "Local checkout missing HEAD; rebuilding from origin/${branch}."
    rebuild_stack
    local_sha="$(git rev-parse HEAD 2>/dev/null || true)"
  elif [ "$remote_sha" != "$local_sha" ]; then
    log "Detected new commit: ${remote_sha} (local ${local_sha})."
    rebuild_stack
  else
    log "No update detected for ${branch} (${local_sha})."
  fi

  sleep "$interval"
done
