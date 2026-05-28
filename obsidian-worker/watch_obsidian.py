import json
import logging
import os
import time
from datetime import datetime, timezone

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

OBSIDIAN_DIR = "/data/obsidian"
STATE_PATH = "/app/config/state.json"
SETTINGS_PATH = "/app/config/settings.json"
STATUS_PATH = os.getenv("STATUS_PATH", "/app/status/obsidian-worker.json")
AGENTMEMORY_URL = os.getenv("AGENTMEMORY_URL", "http://agentmemory:3111")
DEFAULT_SLEEP_INTERVAL = int(os.getenv("SLEEP_INTERVAL", "60"))
DEFAULT_CONTENT_LIMIT = 100000

session = requests.Session()
session.headers.update({"Authorization": f"Bearer {os.getenv('AGENTMEMORY_TOKEN', '')}"})


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_settings():
    settings = {"sleep_interval": DEFAULT_SLEEP_INTERVAL, "content_limit": DEFAULT_CONTENT_LIMIT, "vault_path": ""}
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
            configured = json.load(handle)
        for key in ("sleep_interval", "content_limit"):
            if key in configured:
                settings[key] = int(configured[key])
        if "vault_path" in configured:
            settings["vault_path"] = str(configured["vault_path"]).strip()
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.error("Could not load settings: %s", exc)
    return settings


def save_status(status):
    os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
    temp_path = f"{STATUS_PATH}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(status, handle)
    os.replace(temp_path, STATUS_PATH)


def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Could not load state: %s", exc)
        return {}


def save_state(state):
    temp_path = f"{STATE_PATH}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle)
    os.replace(temp_path, STATE_PATH)


def state_mtime(entry):
    return float(entry.get("mtime", 0)) if isinstance(entry, dict) else float(entry)


def state_id(entry):
    return entry.get("id") if isinstance(entry, dict) else None


def push_to_memory(file_path, content, mtime, content_limit, memory_id=None):
    filename = os.path.basename(file_path)
    title = filename.removesuffix(".md")
    payload = {
        "content": f"Title: {title}\n\n{content[:content_limit]}",
        "category": "obsidian",
        "metadata": {
            "title": title,
            "file_path": file_path,
            "mtime": mtime,
            "needs_enrichment": True,
            "source": "obsidian",
        },
    }
    try:
        endpoint = "/update" if memory_id else "/remember"
        if memory_id:
            payload["id"] = str(memory_id)
        response = session.post(f"{AGENTMEMORY_URL}{endpoint}", json=payload, timeout=35)
        response.raise_for_status()
        if memory_id:
            logger.info("Updated note %s in memory", filename)
            return str(memory_id)
        new_id = response.json()["memory"]["id"]
        logger.info("Stored note %s in memory", filename)
        return str(new_id)
    except Exception as exc:
        logger.error("Failed to save %s to memory: %s", filename, exc)
        return None


def delete_from_memory(file_path, memory_id=None):
    try:
        if memory_id:
            response = session.post(
                f"{AGENTMEMORY_URL}/delete",
                json={"category": "obsidian", "id": str(memory_id)},
                timeout=10,
            )
        else:
            response = session.post(
                f"{AGENTMEMORY_URL}/search",
                json={"query": "*", "category": "obsidian", "metadata": {"file_path": file_path}, "limit": 1},
                timeout=35,
            )
            response.raise_for_status()
            results = response.json().get("results", [])
            if not results:
                return True
            response = session.post(
                f"{AGENTMEMORY_URL}/delete",
                json={"category": "obsidian", "id": str(results[0]["id"])},
                timeout=10,
            )
        response.raise_for_status()
        logger.info("Deleted %s from memory", os.path.basename(file_path))
        return True
    except Exception as exc:
        logger.error("Failed to delete %s from memory: %s", file_path, exc)
        return False


def scan_directory(settings):
    vault_root = os.path.join(OBSIDIAN_DIR, settings["vault_path"]) if settings["vault_path"] else OBSIDIAN_DIR
    logger.info("Scanning Obsidian vault...")
    state = load_state()
    updated_count = 0
    current_files = set()
    if not os.path.exists(vault_root):
        logger.warning("Directory %s does not exist. Waiting...", vault_root)
        save_status(
            {
                "service": "obsidian-worker",
                "status": "waiting",
                "last_cycle_started_at": utc_now(),
                "last_cycle_finished_at": utc_now(),
                "last_error": f"Missing vault path: {vault_root}",
                "source": vault_root,
                "updated_at": utc_now(),
            }
        )
        return

    for root, _, files in os.walk(vault_root):
        if any(part.startswith(".") for part in root.split(os.sep)):
            continue
        for filename in files:
            if not filename.endswith(".md"):
                continue
            file_path = os.path.join(root, filename)
            current_files.add(file_path)
            try:
                mtime = os.path.getmtime(file_path)
                previous = state.get(file_path)
                if previous is not None and state_mtime(previous) >= mtime:
                    continue
                with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
                    content = handle.read()
                memory_id = push_to_memory(
                    file_path,
                    content,
                    mtime,
                    settings["content_limit"],
                    state_id(previous),
                )
                if memory_id:
                    state[file_path] = {"mtime": mtime, "id": memory_id}
                    updated_count += 1
                    if updated_count % 50 == 0:
                        save_state(state)
                else:
                    save_state(state)
                    logger.warning("Memory backend is busy; deferring remaining notes until the next scan.")
                    return
            except Exception as exc:
                logger.error("Error processing %s: %s", file_path, exc)

    deleted_count = 0
    for missing_file in set(state) - current_files:
        if delete_from_memory(missing_file, state_id(state[missing_file])):
            del state[missing_file]
            deleted_count += 1
    save_state(state)
    logger.info("Scan complete. %s notes updated. %s deleted.", updated_count, deleted_count)
    save_status(
        {
            "service": "obsidian-worker",
            "status": "idle",
            "last_cycle_started_at": utc_now(),
            "last_cycle_finished_at": utc_now(),
            "last_success_at": utc_now(),
            "items_processed": updated_count,
            "items_deleted": deleted_count,
            "source": vault_root,
            "updated_at": utc_now(),
        }
    )


def main():
    while True:
        settings = load_settings()
        scan_directory(settings)
        logger.info("Sleeping for %s seconds...", settings["sleep_interval"])
        time.sleep(settings["sleep_interval"])


if __name__ == "__main__":
    main()
