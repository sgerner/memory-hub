import json
import logging
import os
import time
from datetime import datetime, timezone

import docx2txt
import requests
from pypdf import PdfReader

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DOCS_DIR = "/data/ingest"
STATE_PATH = "/app/config/state.json"
SETTINGS_PATH = "/app/config/settings.json"
STATUS_PATH = os.getenv("STATUS_PATH", "/app/status/docs-worker.json")
AGENTMEMORY_URL = os.getenv("AGENTMEMORY_URL", "http://agentmemory:3111")
DEFAULT_SLEEP_INTERVAL = int(os.getenv("SLEEP_INTERVAL", "300"))
DEFAULT_CONTENT_LIMIT = 100000

session = requests.Session()
session.headers.update({"Authorization": f"Bearer {os.getenv('AGENTMEMORY_TOKEN', '')}"})


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_settings():
    settings = {
        "sleep_interval": DEFAULT_SLEEP_INTERVAL,
        "content_limit": DEFAULT_CONTENT_LIMIT,
        "source_paths": [],
    }
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
            configured = json.load(handle)
        settings.update({key: int(configured[key]) for key in ("sleep_interval", "content_limit") if key in configured})
        if "source_paths" in configured:
            value = configured["source_paths"]
            if isinstance(value, list):
                settings["source_paths"] = [str(entry).strip() for entry in value if str(entry).strip()]
            elif isinstance(value, str):
                settings["source_paths"] = [part.strip() for part in value.split(",") if part.strip()]
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.error("Could not load settings: %s", exc)
    return settings


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


def save_status(status):
    os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
    temp_path = f"{STATUS_PATH}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(status, handle)
    os.replace(temp_path, STATUS_PATH)


def state_mtime(entry):
    return float(entry.get("mtime", 0)) if isinstance(entry, dict) else float(entry)


def state_id(entry):
    return entry.get("id") if isinstance(entry, dict) else None


def extract_text(file_path):
    try:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".txt":
            with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
                return handle.read()
        if ext == ".pdf":
            return "\n".join(page.extract_text() or "" for page in PdfReader(file_path).pages)
        if ext == ".docx":
            return docx2txt.process(file_path)
        return None
    except Exception as exc:
        logger.error("Failed to extract text from %s: %s", file_path, exc)
        return None


def push_to_memory(file_path, content, mtime, content_limit, memory_id=None):
    filename = os.path.basename(file_path)
    title = os.path.splitext(filename)[0]
    payload = {
        "content": f"Title: {title}\n\n{content[:content_limit]}",
        "category": "documents",
        "metadata": {
            "title": title,
            "file_path": file_path,
            "mtime": mtime,
            "needs_enrichment": True,
            "source": "onedrive",
        },
    }
    try:
        endpoint = "/update" if memory_id else "/remember"
        if memory_id:
            payload["id"] = str(memory_id)
        response = session.post(f"{AGENTMEMORY_URL}{endpoint}", json=payload, timeout=35)
        response.raise_for_status()
        if memory_id:
            logger.info("Updated document %s in memory", filename)
            return str(memory_id)
        new_id = response.json()["memory"]["id"]
        logger.info("Stored document %s in memory", filename)
        return str(new_id)
    except Exception as exc:
        logger.error("Failed to save %s to memory: %s", filename, exc)
        return None


def delete_from_memory(file_path, memory_id=None):
    try:
        if memory_id:
            response = session.post(
                f"{AGENTMEMORY_URL}/delete",
                json={"category": "documents", "id": str(memory_id)},
                timeout=10,
            )
        else:
            response = session.post(
                f"{AGENTMEMORY_URL}/search",
                json={"query": "*", "category": "documents", "metadata": {"file_path": file_path}, "limit": 1},
                timeout=35,
            )
            response.raise_for_status()
            results = response.json().get("results", [])
            if not results:
                return True
            response = session.post(
                f"{AGENTMEMORY_URL}/delete",
                json={"category": "documents", "id": str(results[0]["id"])},
                timeout=10,
            )
        response.raise_for_status()
        logger.info("Deleted %s from memory", os.path.basename(file_path))
        return True
    except Exception as exc:
        logger.error("Failed to delete %s from memory: %s", file_path, exc)
        return False


def scan_directory(settings):
    logger.info("Scanning Documents folder...")
    state = load_state()
    current_files = set()
    updated_count = 0
    supported_extensions = {".txt", ".pdf", ".docx", ".xls", ".xlsx"}

    source_paths = settings["source_paths"] or [""]
    for source_path in source_paths:
        docs_root = os.path.join(DOCS_DIR, source_path) if source_path else DOCS_DIR
        if not os.path.exists(docs_root):
            logger.warning("Document source %s does not exist. Skipping...", docs_root)
            continue
        for root, _, files in os.walk(docs_root):
            if any(part.startswith(".") for part in root.split(os.sep)):
                continue
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in supported_extensions:
                    continue
                file_path = os.path.join(root, filename)
                current_files.add(file_path)
                try:
                    mtime = os.path.getmtime(file_path)
                    previous = state.get(file_path)
                    if previous is not None and state_mtime(previous) >= mtime:
                        continue
                    content = (
                        f"Spreadsheet Document: {filename}"
                        if ext in {".xls", ".xlsx"}
                        else extract_text(file_path)
                    )
                    if not content or not content.strip():
                        state[file_path] = {"mtime": mtime, "id": state_id(previous)}
                        continue
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
                        logger.warning(
                            "Memory backend is busy; deferring remaining documents until the next scan."
                        )
                        save_status(
                            {
                                "service": "docs-worker",
                                "status": "deferred",
                                "last_cycle_started_at": utc_now(),
                                "last_cycle_finished_at": utc_now(),
                                "items_processed": updated_count,
                                "source_paths": source_paths,
                                "updated_at": utc_now(),
                            }
                        )
                        return
                except Exception as exc:
                    logger.error("Error processing %s: %s", file_path, exc)

    deleted_count = 0
    for missing_file in set(state) - current_files:
        if delete_from_memory(missing_file, state_id(state[missing_file])):
            del state[missing_file]
            deleted_count += 1
    save_state(state)
    logger.info("Scan complete. %s documents updated. %s deleted.", updated_count, deleted_count)
    save_status(
        {
            "service": "docs-worker",
            "status": "idle",
            "last_cycle_started_at": utc_now(),
            "last_cycle_finished_at": utc_now(),
            "last_success_at": utc_now(),
            "items_processed": updated_count,
            "items_deleted": deleted_count,
            "source_paths": source_paths,
            "updated_at": utc_now(),
        }
    )


def main():
    while True:
        settings = load_settings()
        if os.path.exists(DOCS_DIR):
            scan_directory(settings)
        else:
            logger.warning("Directory %s does not exist. Waiting...", DOCS_DIR)
            save_status(
                {
                    "service": "docs-worker",
                    "status": "waiting",
                    "last_error": f"Directory {DOCS_DIR} does not exist.",
                    "updated_at": utc_now(),
                }
            )
        logger.info("Sleeping for %s seconds...", settings["sleep_interval"])
        time.sleep(settings["sleep_interval"])


if __name__ == "__main__":
    main()
