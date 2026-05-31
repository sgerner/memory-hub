#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${MEMORY_HUB_REPO_URL:-https://github.com/sgerner/memory-hub.git}"
REPO_REF="${MEMORY_HUB_REPO_REF:-main}"
INSTALL_BASE="${MEMORY_HUB_INSTALL_BASE:-$HOME}"
INSTALL_DIR="$INSTALL_BASE/plugins"
OPENCODE_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
CODEX_MARKETPLACE_DIR="$HOME/.agents/plugins"
CODEX_MARKETPLACE_FILE="$CODEX_MARKETPLACE_DIR/marketplace.json"
CODEX_BUNDLE_DIR="$INSTALL_DIR/memory-hub"
ANTIGRAVITY_BUNDLE_DIR="$INSTALL_DIR/antigravity-memory-hub"
OPENCODE_BUNDLE_DIR="$HOME/.opencode/plugins"

log() {
  printf '%s\n' "$*"
}

have() {
  command -v "$1" >/dev/null 2>&1
}

repo_root_from_script() {
  local script_path="${BASH_SOURCE[0]}"
  if [[ -n "${script_path:-}" && -f "$script_path" ]]; then
    local script_dir
    script_dir="$(cd "$(dirname "$script_path")" && pwd)"
    if git -C "$script_dir/.." rev-parse --show-toplevel >/dev/null 2>&1; then
      git -C "$script_dir/.." rev-parse --show-toplevel
      return 0
    fi
  fi
  return 1
}

prepare_source_tree() {
  local source_root
  if source_root="$(repo_root_from_script)"; then
    printf '%s\n' "$source_root"
    return 0
  fi

  if ! have git; then
    log "git is required to bootstrap the plugin bundles."
    exit 1
  fi

  local tmp_dir
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "$tmp_dir"' EXIT
  git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$tmp_dir/repo" >/dev/null
  printf '%s\n' "$tmp_dir/repo"
}

copy_bundle() {
  local source_dir="$1"
  local target_dir="$2"
  rm -rf "$target_dir"
  mkdir -p "$(dirname "$target_dir")"
  cp -R "$source_dir" "$target_dir"
}

ensure_node_modules() {
  local bundle_dir="$1"
  if [[ -f "$bundle_dir/package.json" ]]; then
    (cd "$bundle_dir" && npm install >/dev/null)
  fi
}

upsert_codex_marketplace() {
  mkdir -p "$CODEX_MARKETPLACE_DIR"
  python3 - "$CODEX_MARKETPLACE_FILE" "$CODEX_BUNDLE_DIR" <<'PY'
import json, os, sys
path = sys.argv[1]
bundle = sys.argv[2]
entry = {
    "name": "memory-hub",
    "source": {
        "source": "local",
    "path": "./plugins/memory-hub",
    },
    "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    },
    "category": "Productivity",
}
data = {"name": "personal", "interface": {"displayName": "Personal"}, "plugins": []}
if os.path.exists(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        pass
data.setdefault("name", "personal")
data.setdefault("interface", {}).setdefault("displayName", "Personal")
plugins = list(data.get("plugins") or [])
plugins = [p for p in plugins if p.get("name") != "memory-hub"]
plugins.append(entry)
data["plugins"] = plugins
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
}

install_codex() {
  if ! have codex; then
    log "Codex not detected; skipping Codex plugin install."
    return
  fi

  upsert_codex_marketplace
  codex plugin add memory-hub@personal >/dev/null
  log "Codex plugin installed."
}

install_antigravity() {
  if ! have agy; then
    log "Antigravity CLI not detected; skipping Antigravity plugin install."
    return
  fi

  agy plugin install "$ANTIGRAVITY_BUNDLE_DIR" >/dev/null
  log "Antigravity plugin installed."
}

install_opencode() {
  if ! have opencode; then
    log "OpenCode not detected; skipping OpenCode plugin install."
    return
  fi

  mkdir -p "$OPENCODE_CONFIG_DIR"
  local opencode_jsonc="$OPENCODE_CONFIG_DIR/opencode.jsonc"
  local opencode_json="$OPENCODE_CONFIG_DIR/opencode.json"
  local target_config="$opencode_jsonc"
  if [[ ! -f "$target_config" && -f "$opencode_json" ]]; then
    target_config="$opencode_json"
  fi
  if [[ ! -f "$target_config" ]]; then
    target_config="$opencode_jsonc"
    printf '%s\n' '{ "$schema": "https://opencode.ai/config.json" }' > "$target_config"
  fi

  python3 - "$target_config" "$OPENCODE_BUNDLE_DIR" <<'PY'
import json, os, sys
path = sys.argv[1]
bundle = sys.argv[2]
plugin_path = os.path.join(bundle, "memory-hub.js")
try:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    data = {"$schema": "https://opencode.ai/config.json"}
plugins = list(data.get("plugin") or [])
if plugin_path not in plugins:
    plugins.append(plugin_path)
data["plugin"] = plugins
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
  log "OpenCode plugin configuration updated."
}

main() {
  local source_root
  source_root="$(prepare_source_tree)"

  mkdir -p "$INSTALL_DIR"
  copy_bundle "$source_root/plugins/memory-hub" "$CODEX_BUNDLE_DIR"
  copy_bundle "$source_root/plugins/antigravity-memory-hub" "$ANTIGRAVITY_BUNDLE_DIR"
  copy_bundle "$source_root/.opencode/plugins" "$OPENCODE_BUNDLE_DIR"

  ensure_node_modules "$CODEX_BUNDLE_DIR"
  ensure_node_modules "$ANTIGRAVITY_BUNDLE_DIR"

  install_codex
  install_antigravity
  install_opencode

  log "Memory Hub agent plugins are installed under $INSTALL_BASE."
}

main "$@"
