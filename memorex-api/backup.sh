#!/bin/sh
set -eu

BACKUP_ROOT="${BACKUP_ROOT:-/backups}"
SETTINGS_SOURCE="${SETTINGS_SOURCE:-/settings}"
STATUS_PATH="${STATUS_PATH:-/app/status/backup.json}"
MANIFEST_PATH="${MANIFEST_PATH:-$BACKUP_ROOT/manifest.json}"
INTERVAL_SECONDS="${BACKUP_INTERVAL_SECONDS:-21600}"
PGHOST="${PGHOST:-memory-db}"
PGPORT="${PGPORT:-5432}"
PGDATABASE="${PGDATABASE:-agentmemory}"
PGUSER="${PGUSER:-admin}"

export PGPASSWORD="${PGPASSWORD:?PGPASSWORD is required}"

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
