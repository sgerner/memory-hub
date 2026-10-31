#!/bin/sh
set -eu

BACKUP_ROOT="${BACKUP_ROOT:-/backups}"
DB_BACKUP_DIR="${DB_BACKUP_DIR:-$BACKUP_ROOT/agentmemory-db}"
SETTINGS_SOURCE="${SETTINGS_SOURCE:-/settings}"
SETTINGS_ARCHIVE="${SETTINGS_ARCHIVE:-$BACKUP_ROOT/memory-hub-settings.tar.gz}"
STATUS_PATH="${STATUS_PATH:-/app/status/backup.json}"
MANIFEST_PATH="${MANIFEST_PATH:-$BACKUP_ROOT/manifest.json}"
INTERVAL_SECONDS="${BACKUP_INTERVAL_SECONDS:-86400}"
DB_READY_TIMEOUT_SECONDS="${BACKUP_DB_READY_TIMEOUT_SECONDS:-300}"
DB_DUMP_JOBS="${BACKUP_DB_DUMP_JOBS:-1}"
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

case "$DB_READY_TIMEOUT_SECONDS" in
  ''|*[!0-9]*)
    DB_READY_TIMEOUT_SECONDS=300
    ;;
esac

case "$DB_DUMP_JOBS" in
  ''|*[!0-9]*|0)
    DB_DUMP_JOBS=1
    ;;
esac

mkdir -p "$BACKUP_ROOT" "$(dirname "$STATUS_PATH")"

tmp_db_dir=""
tmp_settings_file=""
tmp_error_log=""
old_db_dir=""

cleanup() {
  [ -z "$tmp_db_dir" ] || rm -rf "$tmp_db_dir"
  [ -z "$tmp_settings_file" ] || rm -f "$tmp_settings_file"
  [ -z "$tmp_error_log" ] || rm -f "$tmp_error_log"
}

trap cleanup EXIT INT TERM

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
  "last_success_at": $last_success_at,
  "last_error": $last_error,
  "updated_at": "$finished_at",
  "details": {
    "database_dump": $db_dump,
    "database_dump_format": "directory",
    "settings_dump": $settings_dump,
    "backup_root": "$BACKUP_ROOT"
  }
}
EOF
  mv "$tmp_status" "$STATUS_PATH"
}

json_string() {
  escaped=$(printf '%s' "$1" | tr '\n' ' ' | sed 's/\\/\\\\/g; s/"/\\"/g')
  printf '"%s"' "$escaped"
}

wait_for_database() {
  elapsed=0

  while ! pg_isready --host "$PGHOST" --port "$PGPORT" --dbname "$PGDATABASE" --username "$PGUSER" >/dev/null 2>&1; do
    if [ "$elapsed" -ge "$DB_READY_TIMEOUT_SECONDS" ]; then
      printf 'Timed out waiting for PostgreSQL at %s:%s/%s\n' "$PGHOST" "$PGPORT" "$PGDATABASE" >&2
      return 1
    fi
    sleep 5
    elapsed=$((elapsed + 5))
  done
}

publish_database_dump() {
  new_dir="$1"
  old_db_dir="$BACKUP_ROOT/.agentmemory-db.previous.$$.$(date +%s)"

  if [ -e "$DB_BACKUP_DIR" ]; then
    if ! mv "$DB_BACKUP_DIR" "$old_db_dir"; then
      old_db_dir=""
      return 1
    fi
  fi

  if ! mv "$new_dir" "$DB_BACKUP_DIR"; then
    if [ -e "$old_db_dir" ] && [ ! -e "$DB_BACKUP_DIR" ]; then
      if mv "$old_db_dir" "$DB_BACKUP_DIR"; then
        old_db_dir=""
      fi
    fi
    return 1
  fi

  tmp_db_dir=""
  rm -rf "$old_db_dir" || true
  old_db_dir=""
}

publish_settings_archive() {
  new_file="$1"

  if ! mv "$new_file" "$SETTINGS_ARCHIVE"; then
    return 1
  fi

  tmp_settings_file=""
}

run_backup_cycle() {
  started_at="$1"
  db_name_json=$(json_string "$(basename "$DB_BACKUP_DIR")")
  settings_name_json=$(json_string "$(basename "$SETTINGS_ARCHIVE")")
  last_error=null
  last_success_at=null
  tmp_db_dir="$BACKUP_ROOT/.agentmemory-db.$$.tmp"
  tmp_settings_file="$BACKUP_ROOT/.memory-hub-settings.$$.tar.gz.tmp"
  tmp_error_log="$BACKUP_ROOT/.agentmemory-db.$$.log"

  rm -rf "$tmp_db_dir" "$tmp_settings_file" "$tmp_error_log"

  if ! wait_for_database; then
    last_error=$(json_string "PostgreSQL did not become ready within ${DB_READY_TIMEOUT_SECONDS}s")
  elif ! pg_dump \
    --host "$PGHOST" \
    --port "$PGPORT" \
    --username "$PGUSER" \
    --dbname "$PGDATABASE" \
    --format=directory \
    --file "$tmp_db_dir" \
    --jobs "$DB_DUMP_JOBS" \
    --compress=9 \
    --clean \
    --if-exists \
    --no-owner \
    --no-privileges >"$tmp_error_log" 2>&1; then
    cat "$tmp_error_log" >&2 || true
    dump_error=$(tr '\n' ' ' < "$tmp_error_log" | sed 's/[[:space:]][[:space:]]*/ /g')
    last_error=$(json_string "pg_dump failed: ${dump_error:-unknown error}; the previous backup was retained")
  elif ! pg_restore --list "$tmp_db_dir" >/dev/null 2>&1; then
    last_error=$(json_string "pg_restore validation failed; the previous backup was retained")
  elif ! tar -czf "$tmp_settings_file" -C "$SETTINGS_SOURCE" .; then
    last_error=$(json_string "Failed to archive settings source $SETTINGS_SOURCE; the previous backup was retained")
  elif ! publish_database_dump "$tmp_db_dir"; then
    last_error=$(json_string "Failed to publish the database backup; the previous backup was retained")
  elif ! publish_settings_archive "$tmp_settings_file"; then
    last_error=$(json_string "Failed to publish the settings backup")
  else
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
    "dump": "$(basename "$DB_BACKUP_DIR")",
    "format": "directory"
  },
  "settings_snapshot": "$(basename "$SETTINGS_ARCHIVE")",
  "backup_root": "$BACKUP_ROOT"
}
EOF
    if ! mv "$manifest_tmp" "$MANIFEST_PATH"; then
      rm -f "$manifest_tmp"
      last_error=$(json_string "Failed to publish backup manifest")
    else
      last_success_at="$finished_json"
      write_status "idle" "$started_at" "$finished_at" "$last_success_at" null "$db_name_json" "$settings_name_json"
      rm -f "$tmp_error_log"
      tmp_error_log=""
      return 0
    fi
  fi

  finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  write_status "error" "$started_at" "$finished_at" "$last_success_at" "$last_error" "$db_name_json" "$settings_name_json"
  rm -f "$tmp_error_log"
  tmp_error_log=""
  return 1
}

while true; do
  started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  if run_backup_cycle "$started_at"; then
    sleep "$INTERVAL_SECONDS"
  else
    sleep 300
  fi
done
