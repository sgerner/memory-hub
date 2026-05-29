#!/bin/sh
set -eu

BACKUP_ROOT="${BACKUP_ROOT:-/backups}"
SETTINGS_SOURCE="${SETTINGS_SOURCE:-/settings}"
STATUS_PATH="${STATUS_PATH:-/app/status/backup.json}"
MANIFEST_PATH="${MANIFEST_PATH:-$BACKUP_ROOT/manifest.json}"
INTERVAL_SECONDS="${BACKUP_INTERVAL_SECONDS:-86400}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
PGHOST="${PGHOST:-memory-db}"
PGPORT="${PGPORT:-5432}"
PGDATABASE="${PGDATABASE:-agentmemory}"
PGUSER="${PGUSER:-admin}"

export PGPASSWORD="${PGPASSWORD:?PGPASSWORD is required}"

case "$INTERVAL_SECONDS" in
  ''|*[!0-9]*)
    INTERVAL_SECONDS=86400
    ;;
esac

[ "$INTERVAL_SECONDS" -lt 86400 ] && INTERVAL_SECONDS=86400

mkdir -p "$BACKUP_ROOT" "$(dirname "$STATUS_PATH")"

write_status() {
  status="$1"
  started_at="$2"
  finished_at="$3"
  last_success_at="$4"
  last_error="$5"
  db_dump="$6"
  settings_dump="$7"
  tmp_status="$STATUS_PATH.tmp"
  cat > "$tmp_status" <<EOF
{
  "service": "backup-stager",
  "status": "$status",
  "last_cycle_started_at": "$started_at",
  "last_cycle_finished_at": "$finished_at",
  "last_success_at": ${last_success_at},
  "last_error": ${last_error},
  "updated_at": "$finished_at",
  "details": {
    "database_dump": ${db_dump},
    "settings_dump": ${settings_dump},
    "backup_root": "$BACKUP_ROOT"
  }
}
EOF
  mv "$tmp_status" "$STATUS_PATH"
}

json_string() {
  printf '"%s"' "$1"
}

timestamp_from_backup_name() {
  name="$1"
  case "$name" in
    agentmemory-db-*.sql.gz)
      ts="${name#agentmemory-db-}"
      printf '%s\n' "${ts%.sql.gz}"
      ;;
    memory-hub-settings-*.tar.gz)
      ts="${name#memory-hub-settings-}"
      printf '%s\n' "${ts%.tar.gz}"
      ;;
  esac
}

prune_backups() {
  [ "$RETENTION_DAYS" -gt 0 ] || return 0

  db_list="$(mktemp "$BACKUP_ROOT/.backup-db-list.XXXXXX")"
  keep_list="$(mktemp "$BACKUP_ROOT/.backup-keep-list.XXXXXX")"
  all_list="$(mktemp "$BACKUP_ROOT/.backup-all-list.XXXXXX")"
  keep_list_tmp="$keep_list.tmp"
  trap 'rm -f "$db_list" "$keep_list" "$keep_list_tmp" "$all_list"' EXIT INT TERM

  find "$BACKUP_ROOT" -maxdepth 1 -type f -name 'agentmemory-db-*.sql.gz' -print | sort > "$db_list"

  : > "$keep_list"
  current_day=""
  current_ts=""

  while IFS= read -r db_file; do
    base="${db_file##*/}"
    ts="$(timestamp_from_backup_name "$base")" || continue
    [ -n "$ts" ] || continue
    day="${ts%%T*}"
    settings_file="$BACKUP_ROOT/memory-hub-settings-$ts.tar.gz"

    [ -f "$settings_file" ] || continue

    if [ "$day" != "$current_day" ] && [ -n "$current_ts" ]; then
      printf '%s\n' "$current_ts" >> "$keep_list"
    fi
    current_day="$day"
    current_ts="$ts"
  done < "$db_list"

  [ -n "$current_ts" ] && printf '%s\n' "$current_ts" >> "$keep_list"
  sort -u "$keep_list" | tail -n "$RETENTION_DAYS" > "$keep_list_tmp"
  mv "$keep_list_tmp" "$keep_list"

  find "$BACKUP_ROOT" -maxdepth 1 -type f \( -name 'agentmemory-db-*.sql.gz' -o -name 'memory-hub-settings-*.tar.gz' \) -print | sort > "$all_list"

  while IFS= read -r file; do
    base="${file##*/}"
    ts="$(timestamp_from_backup_name "$base")" || continue
    [ -n "$ts" ] || continue
    if ! grep -Fxq "$ts" "$keep_list"; then
      rm -f "$BACKUP_ROOT/agentmemory-db-$ts.sql.gz" "$BACKUP_ROOT/memory-hub-settings-$ts.tar.gz"
    fi
  done < "$all_list"

  rm -f "$db_list" "$keep_list" "$keep_list_tmp" "$all_list"
  trap - EXIT INT TERM
}

while true; do
  started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  dump_file="$BACKUP_ROOT/agentmemory-db-$timestamp.sql.gz"
  settings_file="$BACKUP_ROOT/memory-hub-settings-$timestamp.tar.gz"
  db_name_json=$(json_string "$(basename "$dump_file")")
  settings_name_json=$(json_string "$(basename "$settings_file")")
  started_json=$(json_string "$started_at")
  last_error=null
  last_success_at=null

  if pg_dump --host "$PGHOST" --port "$PGPORT" --username "$PGUSER" --dbname "$PGDATABASE" --clean --if-exists --no-owner --no-privileges | gzip > "$dump_file"; then
    if tar -czf "$settings_file" -C "$SETTINGS_SOURCE" .; then
      finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      finished_json=$(json_string "$finished_at")
      manifest_tmp="$MANIFEST_PATH.tmp"
      cat > "$manifest_tmp" <<EOF
{
  "generated_at": "$finished_at",
  "database": {
    "host": "$PGHOST",
    "port": "$PGPORT",
    "name": "$PGDATABASE",
    "dump": $(json_string "$(basename "$dump_file")")
  },
  "settings_snapshot": $(json_string "$(basename "$settings_file")"),
  "backup_root": "$BACKUP_ROOT"
}
EOF
      mv "$manifest_tmp" "$MANIFEST_PATH"
      last_success_at=$(json_string "$finished_at")
      write_status "idle" "$started_at" "$finished_at" "$last_success_at" null "$db_name_json" "$settings_name_json"
      prune_backups
      sleep "$INTERVAL_SECONDS"
      continue
    fi
    last_error=$(json_string "Failed to archive settings source $SETTINGS_SOURCE")
  else
    last_error=$(json_string "Failed to dump database from $PGHOST:$PGPORT/$PGDATABASE")
  fi

  finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  write_status "error" "$started_at" "$finished_at" "$last_success_at" "$last_error" "$db_name_json" "$settings_name_json"
  sleep 300
done
