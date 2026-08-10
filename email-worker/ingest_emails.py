import os
import time
import json
import logging
import email
from email.header import decode_header
from imapclient import IMAPClient
from bs4 import BeautifulSoup
import html2text
import requests
import io
from pypdf import PdfReader
import docx2txt
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
AGENTMEMORY_URL = os.getenv("AGENTMEMORY_URL", "http://agentmemory:3111")
AGENTMEMORY_TOKEN = os.getenv("AGENTMEMORY_TOKEN")
DEFAULT_BATCH_SIZE = int(os.getenv("BATCH_SIZE", os.getenv("INGEST_BATCH_SIZE", "200")))
DEFAULT_SLEEP_INTERVAL = int(os.getenv("SLEEP_INTERVAL", os.getenv("INGEST_SLEEP_INTERVAL", "900")))
STATE_PATH = "/app/config/state.json"
ACCOUNTS_PATH = "/app/config/accounts.json"
SETTINGS_PATH = "/app/config/settings.json"
STATUS_PATH = os.getenv("STATUS_PATH", "/app/status/email-worker.json")
QUARANTINE_FLAGS = {'\\trash', '\\spam', '\\junk', '\\deleted'}
QUARANTINE_KEYWORDS = ['spam', 'junk', 'trash', 'deleted', 'bulk', 'low-priority']
DRAFT_FLAGS = {'\\drafts'}
DRAFT_KEYWORDS = ['draft']
HEADER_FETCH_ITEMS = ['RFC822.HEADER', 'INTERNALDATE']

session = requests.Session()
session.headers.update({"Authorization": f"Bearer {AGENTMEMORY_TOKEN}"})


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def parse_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "ssl", "ssl/tls"}:
        return True
    if text in {"0", "false", "no", "off", "plain", "starttls"}:
        return False
    return default


def save_status(status):
    os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
    temp_path = f"{STATUS_PATH}.tmp"
    with open(temp_path, 'w', encoding='utf-8') as f:
        json.dump(status, f)
    os.replace(temp_path, STATUS_PATH)

def load_settings():
    settings = {
        "batch_size": DEFAULT_BATCH_SIZE,
        "sleep_interval": DEFAULT_SLEEP_INTERVAL,
        "attachment_text_limit": 50000
    }
    try:
        with open(SETTINGS_PATH, 'r', encoding='utf-8') as f:
            configured = json.load(f)
        settings.update({key: int(configured[key]) for key in settings if key in configured})
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as e:
        logger.error(f"Could not load settings: {e}")
    return settings

def save_state(state):
    temp_path = f"{STATE_PATH}.tmp"
    with open(temp_path, 'w', encoding='utf-8') as f:
        json.dump(state, f)
    os.replace(temp_path, STATE_PATH)

def clean_text(html_content):
    try:
        h = html2text.HTML2Text()
        h.ignore_links = True
        h.ignore_images = True
        return h.handle(html_content)
    except:
        return html_content

def sanitize_str(val):
    if val is None:
        return ""
    # Postgres string literals cannot contain NUL (0x00) characters
    return str(val).replace('\x00', '')

def normalize_message_id(val):
    text = sanitize_str(val).strip()
    if text.startswith("<") and text.endswith(">") and len(text) > 2:
        text = text[1:-1].strip()
    return text


def decode_header_value(value):
    """Decode all RFC 2047 header fragments without downloading the message body."""
    if value is None:
        return ""
    decoded = []
    for fragment, encoding in decode_header(str(value)):
        if isinstance(fragment, bytes):
            decoded.append(fragment.decode(encoding or "utf-8", errors="replace"))
        else:
            decoded.append(str(fragment))
    return "".join(decoded)


def is_all_mail_folder(flags, folder_name):
    """Return whether a folder is the provider's canonical all-mail view."""
    norm_flags = {
        flag.decode('ascii', 'ignore').lower() if isinstance(flag, bytes) else str(flag).lower()
        for flag in flags
    }
    normalized_name = sanitize_str(folder_name).strip().lower()
    return "\\all" in norm_flags or normalized_name in {
        "all mail",
        "[gmail]/all mail",
        "[google mail]/all mail",
    }


def parse_message_headers(uid, msg_data):
    """Extract the fields needed for deduplication from RFC822 headers only."""
    raw_headers = msg_data.get(b'RFC822.HEADER') or msg_data.get('RFC822.HEADER') or b''
    msg = email.message_from_bytes(raw_headers)
    return {
        "uid": uid,
        "subject": decode_header_value(msg.get("Subject", "No Subject")),
        "from": sanitize_str(msg.get("From")),
        "to": sanitize_str(msg.get("To")),
        "date": str(msg_data.get(b'INTERNALDATE') or msg_data.get('INTERNALDATE') or ""),
        "message_id": normalize_message_id(msg.get("Message-ID")),
    }


def fetch_message_headers(client, uids):
    """Fetch small headers for a group of messages, never their bodies or attachments."""
    if not uids:
        return {}
    fetched = client.fetch(uids, HEADER_FETCH_ITEMS)
    return {
        uid: parse_message_headers(uid, msg_data)
        for uid, msg_data in fetched.items()
    }


def message_dedupe_key(summary):
    """Use Message-ID only; missing IDs must not cause unrelated mail to be merged."""
    message_id = normalize_message_id(summary.get("message_id"))
    return message_id or None

def classify_folder(flags, folder_name):
    norm_flags = [f.decode('ascii', 'ignore').lower() if isinstance(f, bytes) else str(f).lower() for f in flags]
    folder_lower = sanitize_str(folder_name).lower()
    if any(flag in DRAFT_FLAGS for flag in norm_flags) or any(keyword in folder_lower for keyword in DRAFT_KEYWORDS):
        return "draft"
    if any(flag in QUARANTINE_FLAGS for flag in norm_flags) or any(keyword in folder_lower for keyword in QUARANTINE_KEYWORDS):
        return "quarantine"
    return "normal"

def push_to_memory(email_data):
    try:
        # Construct content
        content = f"Subject: {sanitize_str(email_data['subject'])}\n"
        content += f"From: {sanitize_str(email_data['from'])}\n"
        content += f"Date: {sanitize_str(email_data['date'])}\n\n"
        
        body_clean = sanitize_str(email_data['body'])
        content += f"Body:\n{body_clean}"

        payload = {
            "content": content,
            "category": "emails",
            "metadata": {
                "subject": sanitize_str(email_data['subject']),
                "sender": sanitize_str(email_data['from']),
                "receiver": sanitize_str(email_data['to']),
                "date": sanitize_str(email_data['date']),
                "account": sanitize_str(email_data['account_name']),
                "uid": sanitize_str(email_data['uid']),
                "message_id": normalize_message_id(email_data.get('message_id')),
                "needs_enrichment": "True", # Store as string for metadata filter reliability
                "source": "email",
                "folder": sanitize_str(email_data.get('folder', 'unknown'))
            }
        }

        resp = session.post(f"{AGENTMEMORY_URL}/remember", json=payload, timeout=35)
        if resp.status_code not in [200, 201]:
            logger.error(f"Agentmemory error {resp.status_code}: {resp.text}")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to push to memory: {e}")
        return False

def delete_from_memory(email_data):
    try:
        payload = {
            "account": sanitize_str(email_data['account_name']),
            "folder": sanitize_str(email_data.get('folder', '')),
            "uid": sanitize_str(email_data.get('uid', '')),
            "message_id": normalize_message_id(email_data.get('message_id')),
            "subject": sanitize_str(email_data.get('subject')),
            "sender": sanitize_str(email_data.get('from')),
            "receiver": sanitize_str(email_data.get('to')),
            "date": sanitize_str(email_data.get('date')),
            "reason": sanitize_str(email_data.get('reason', 'quarantine folder')),
        }
        resp = session.post(f"{AGENTMEMORY_URL}/delete-email", json=payload, timeout=35)
        if resp.status_code not in [200, 201, 204]:
            logger.error(f"Agentmemory delete error {resp.status_code}: {resp.text}")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to delete memory: {e}")
        return False

def save_account_cursor(state, account_name, account_state, folder_name, uid):
    account_state[folder_name] = uid
    state[account_name] = account_state
    save_state(state)


def deferred_status(account_name, started_at, folders_seen, items_processed, items_total, deduplicated):
    save_status({
        "service": "email-worker",
        "status": "deferred",
        "current_account": account_name,
        "last_cycle_started_at": started_at,
        "last_cycle_finished_at": utc_now(),
        "last_error": "Memory backend is unavailable; remaining email messages were deferred.",
        "items_processed": items_processed,
        "items_total": items_total,
        "details": {
            "folders_seen": folders_seen,
            "headers_fetched": items_total,
            "deduplicated": deduplicated,
        },
        "updated_at": utc_now(),
    })


def process_account(account, settings):
    name = account['name']
    host = account['host']
    port = int(account.get('port') or 993)
    use_ssl = parse_bool(account.get('ssl'), True)
    user = account['user']
    password = account['password']

    logger.info(f"Processing account: {name} ({host}:{port}, ssl={use_ssl})")
    started_at = utc_now()
    messages_processed = 0
    folders_seen = 0
    headers_fetched = 0
    deduplicated = 0

    save_status({
        "service": "email-worker",
        "status": "running",
        "current_account": name,
        "last_cycle_started_at": started_at,
        "updated_at": started_at,
    })

    state = {}
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, 'r') as f:
                state = json.load(f)
        except (OSError, ValueError, TypeError):
            state = {}

    account_state = state.get(name, {})
    if not isinstance(account_state, dict):
        account_state = {}

    try:
        with IMAPClient(host, port=port, ssl=use_ssl) as client:
            client.login(user, password)
            folders = client.list_folders()
            all_mail_folder = next(
                (
                    folder_name
                    for flags, _delimiter, folder_name in folders
                    if b'\\Noselect' not in flags and is_all_mail_folder(flags, folder_name)
                ),
                None,
            )
            if all_mail_folder:
                logger.info(
                    "Using %s as the canonical normal-mail folder; other normal folders will only advance their cursors.",
                    all_mail_folder,
                )

            candidates = []
            for flags, _delimiter, folder_name in folders:
                if b'\\Noselect' in flags:
                    continue

                folder_kind = classify_folder(flags, folder_name)
                folders_seen += 1
                try:
                    client.select_folder(folder_name, readonly=True)
                    last_uid = int(account_state.get(folder_name, 0) or 0)
                    uids = sorted(client.search(['UID', f'{last_uid + 1}:*']))
                except Exception as error:
                    logger.warning("Could not scan folder %s: %s", folder_name, error)
                    continue

                if not uids:
                    continue

                # Drafts are intentionally ignored. With a canonical All Mail folder,
                # every other normal folder is also redundant for ingestion. Advancing
                # those cursors prevents an expensive repeat search on every cycle.
                if folder_kind == "draft" or (
                    folder_kind == "normal" and all_mail_folder and folder_name != all_mail_folder
                ):
                    save_account_cursor(state, name, account_state, folder_name, uids[-1])
                    logger.info("Skipped %s pending messages from redundant folder %s", len(uids), folder_name)
                    continue

                uids_to_process = uids[:settings["batch_size"]]
                logger.info(
                    "%s %s messages from %s using header-first deduplication",
                    "Purging" if folder_kind == "quarantine" else "Reviewing",
                    len(uids_to_process),
                    folder_name,
                )
                try:
                    header_map = fetch_message_headers(client, uids_to_process)
                except Exception as error:
                    logger.warning("Could not fetch headers from folder %s: %s", folder_name, error)
                    continue

                headers_fetched += len(header_map)
                for uid in uids_to_process:
                    summary = header_map.get(uid)
                    if summary is not None:
                        candidates.append({
                            "folder": folder_name,
                            "kind": folder_kind,
                            "summary": summary,
                        })

            quarantine_keys = {
                message_dedupe_key(candidate["summary"])
                for candidate in candidates
                if candidate["kind"] == "quarantine" and message_dedupe_key(candidate["summary"])
            }
            seen_message_ids = set()
            purged_message_ids = set()
            selected_folder = None

            # Process quarantine headers first so a message that exists in both a
            # quarantine folder and a normal folder is not re-added to memory.
            ordered_candidates = sorted(
                candidates,
                key=lambda candidate: candidate["kind"] != "quarantine",
            )
            for candidate in ordered_candidates:
                folder_name = candidate["folder"]
                folder_kind = candidate["kind"]
                summary = candidate["summary"]
                uid = summary["uid"]
                key = message_dedupe_key(summary)

                if folder_kind == "quarantine":
                    if key and key in purged_message_ids:
                        save_account_cursor(state, name, account_state, folder_name, uid)
                        deduplicated += 1
                        continue
                    if delete_from_memory({
                        "account_name": name,
                        "uid": uid,
                        "subject": summary["subject"],
                        "from": summary["from"],
                        "to": summary["to"],
                        "date": summary["date"],
                        "folder": folder_name,
                        "message_id": summary["message_id"],
                        "reason": "quarantine folder",
                    }):
                        save_account_cursor(state, name, account_state, folder_name, uid)
                        if key:
                            purged_message_ids.add(key)
                        messages_processed += 1
                        continue

                    deferred_status(name, started_at, folders_seen, messages_processed, headers_fetched, deduplicated)
                    return True

                if key and (key in seen_message_ids or key in quarantine_keys):
                    save_account_cursor(state, name, account_state, folder_name, uid)
                    deduplicated += 1
                    continue

                if selected_folder != folder_name:
                    client.select_folder(folder_name, readonly=True)
                    selected_folder = folder_name

                try:
                    msg_data = client.fetch([uid], ['RFC822', 'INTERNALDATE'])[uid]
                    raw_email = msg_data[b'RFC822']
                    msg = email.message_from_bytes(raw_email)
                    subject = decode_header_value(msg.get("Subject", "No Subject"))
                    from_ = msg.get("From")
                    to_ = msg.get("To")
                    date_ = str(msg_data[b'INTERNALDATE'])
                    message_id = normalize_message_id(msg.get("Message-ID"))

                    body = ""
                    attachments = []
                    if msg.is_multipart():
                        for part in msg.walk():
                            content_disposition = str(part.get("Content-Disposition", ""))
                            if "attachment" in content_disposition or part.get_filename():
                                filename = part.get_filename()
                                if filename:
                                    filename_str = decode_header_value(filename)
                                    attachments.append(filename_str)

                                    payload_bytes = part.get_payload(decode=True)
                                    if payload_bytes:
                                        ext = filename_str.lower().split('.')[-1]
                                        extracted_text = ""
                                        try:
                                            if ext == 'txt':
                                                extracted_text = payload_bytes.decode(errors='ignore')
                                            elif ext == 'pdf':
                                                pdf_file = io.BytesIO(payload_bytes)
                                                reader = PdfReader(pdf_file)
                                                extracted_text = "\n".join(
                                                    page.extract_text() or "" for page in reader.pages
                                                )
                                            elif ext == 'docx':
                                                docx_file = io.BytesIO(payload_bytes)
                                                extracted_text = docx2txt.process(docx_file)
                                        except Exception:
                                            pass

                                        if extracted_text.strip():
                                            body += f"\n\n--- Attachment Content: {filename_str} ---\n"
                                            body += extracted_text[:settings["attachment_text_limit"]]
                                            body += "\n--- End Attachment ---"
                                continue

                            if part.get_content_type() == "text/plain" and not body:
                                try:
                                    body = part.get_payload(decode=True).decode(errors='ignore')
                                except Exception:
                                    pass
                            elif part.get_content_type() == "text/html" and not body:
                                try:
                                    html_body = part.get_payload(decode=True).decode(errors='ignore')
                                    body = clean_text(html_body)
                                except Exception:
                                    pass
                    else:
                        try:
                            body = msg.get_payload(decode=True).decode(errors='ignore')
                        except Exception:
                            pass

                    if attachments:
                        body += "\n\nAttachments: " + ", ".join(attachments)

                    if push_to_memory({
                        "account_name": name,
                        "uid": uid,
                        "subject": subject,
                        "from": from_,
                        "to": to_,
                        "date": date_,
                        "body": body,
                        "folder": folder_name,
                        "message_id": message_id,
                    }):
                        save_account_cursor(state, name, account_state, folder_name, uid)
                        if key or message_id:
                            seen_message_ids.add(key or message_id)
                        messages_processed += 1
                    else:
                        deferred_status(name, started_at, folders_seen, messages_processed, headers_fetched, deduplicated)
                        return True
                except Exception as error:
                    logger.error("Error processing email UID %s in %s: %s", uid, folder_name, error)

    except Exception as error:
        error_str = str(error)
        if "AUTHENTICATIONFAILED" in error_str or "Invalid credentials" in error_str:
            human_error = f"Invalid password for account: {name}"
        else:
            human_error = error_str

        logger.error(f"Error connecting to account {name}: {error_str}")
        save_status({
            "service": "email-worker",
            "status": "error",
            "current_account": name,
            "last_cycle_started_at": started_at,
            "last_cycle_finished_at": utc_now(),
            "last_error": human_error,
            "items_processed": messages_processed,
            "details": {
                "folders_seen": folders_seen,
                "headers_fetched": headers_fetched,
                "deduplicated": deduplicated,
            },
            "updated_at": utc_now(),
        })
        return False

    save_status({
        "service": "email-worker",
        "status": "idle",
        "current_account": name,
        "last_cycle_started_at": started_at,
        "last_cycle_finished_at": utc_now(),
        "last_success_at": utc_now(),
        "items_processed": messages_processed,
        "details": {
            "folders_seen": folders_seen,
            "headers_fetched": headers_fetched,
            "deduplicated": deduplicated,
        },
        "updated_at": utc_now(),
    })
    return True

def main():
    while True:
        settings = load_settings()
        if not os.path.exists(ACCOUNTS_PATH):
            logger.error(f"Accounts file not found at {ACCOUNTS_PATH}")
            save_status({
                "service": "email-worker",
                "status": "waiting",
                "last_cycle_started_at": utc_now(),
                "last_cycle_finished_at": utc_now(),
                "last_error": f"Missing accounts file: {ACCOUNTS_PATH}",
                "updated_at": utc_now(),
            })
            time.sleep(settings["sleep_interval"])
            continue

        cycle_started_at = utc_now()
        failed_accounts = []

        with open(ACCOUNTS_PATH, 'r') as f:
            accounts = json.load(f)
            for account in accounts:
                if not process_account(account, settings):
                    failed_accounts.append(str(account.get("name", "unknown")))
                    continue

        if failed_accounts:
            save_status({
                "service": "email-worker",
                "status": "error",
                "current_account": failed_accounts[-1],
                "last_cycle_started_at": cycle_started_at,
                "last_cycle_finished_at": utc_now(),
                "last_error": f"{len(failed_accounts)} mailbox(es) failed: {', '.join(failed_accounts)}",
                "details": {
                    "failed_accounts": failed_accounts,
                },
                "updated_at": utc_now(),
            })

        logger.info(f"Local ingest cycle finished. Sleeping for {settings['sleep_interval']} seconds...")
        time.sleep(settings["sleep_interval"])

if __name__ == "__main__":
    main()
