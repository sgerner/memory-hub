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
DEFAULT_BATCH_SIZE = int(os.getenv("BATCH_SIZE", os.getenv("INGEST_BATCH_SIZE", "2000")))
DEFAULT_SLEEP_INTERVAL = int(os.getenv("SLEEP_INTERVAL", os.getenv("INGEST_SLEEP_INTERVAL", "300")))
STATE_PATH = "/app/config/state.json"
ACCOUNTS_PATH = "/app/config/accounts.json"
SETTINGS_PATH = "/app/config/settings.json"
STATUS_PATH = os.getenv("STATUS_PATH", "/app/status/email-worker.json")

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
        except: state = {}
    
    account_state = state.get(name, {})

    try:
        with IMAPClient(host, port=port, ssl=use_ssl) as client:
            client.login(user, password)
            folders = client.list_folders()
            
            for (flags, delimiter, folder_name) in folders:
                if b'\\Noselect' in flags: continue
                
                # Intelligently identify and skip junk/spam/trash folders
                norm_flags = [f.decode('ascii', 'ignore').lower() if isinstance(f, bytes) else str(f).lower() for f in flags]
                skip_flags = {'\\trash', '\\spam', '\\junk', '\\drafts', '\\deleted'}
                if any(flag in skip_flags for flag in norm_flags): continue
                
                folder_lower = folder_name.lower()
                skip_keywords = ['spam', 'junk', 'trash', 'deleted', 'bulk', 'low-priority']
                if any(x in folder_lower for x in skip_keywords): continue

                logger.info(f"Scanning folder: {folder_name}")
                folders_seen += 1
                try:
                    client.select_folder(folder_name, readonly=True)
                except: continue
                
                last_uid = account_state.get(folder_name, 0)
                uids = client.search(['UID', f'{last_uid + 1}:*'])
                uids.sort()
                uids_to_process = uids[:settings["batch_size"]]
                
                if not uids_to_process: continue

                logger.info(f"Ingesting {len(uids_to_process)} emails from {folder_name}")

                for uid in uids_to_process:
                    try:
                        msg_data = client.fetch([uid], ['RFC822', 'INTERNALDATE'])
                        raw_email = msg_data[uid][b'RFC822']
                        msg = email.message_from_bytes(raw_email)
                        
                        subject_header = decode_header(msg.get("Subject", "No Subject"))[0]
                        subject = subject_header[0]
                        if isinstance(subject, bytes):
                            encoding = subject_header[1] or 'utf-8'
                            subject = subject.decode(encoding, errors='ignore')
                        
                        from_ = msg.get("From")
                        to_ = msg.get("To")
                        date_ = str(msg_data[uid][b'INTERNALDATE'])

                        body = ""
                        attachments = []
                        if msg.is_multipart():
                            for part in msg.walk():
                                content_disposition = str(part.get("Content-Disposition", ""))
                                if "attachment" in content_disposition or part.get_filename():
                                    filename = part.get_filename()
                                    if filename:
                                        decoded_filename = decode_header(filename)[0][0]
                                        if isinstance(decoded_filename, bytes):
                                            try: decoded_filename = decoded_filename.decode(errors='ignore')
                                            except: pass
                                        
                                        filename_str = str(decoded_filename)
                                        attachments.append(filename_str)
                                        
                                        payload_bytes = part.get_payload(decode=True)
                                        if payload_bytes:
                                            ext = filename_str.lower().split('.')[-1]
                                            extracted_text = ""
                                            try:
                                                if ext == 'txt': extracted_text = payload_bytes.decode(errors='ignore')
                                                elif ext == 'pdf':
                                                    pdf_file = io.BytesIO(payload_bytes)
                                                    reader = PdfReader(pdf_file)
                                                    extracted_text = "\n".join([page.extract_text() or "" for page in reader.pages])
                                                elif ext == 'docx':
                                                    docx_file = io.BytesIO(payload_bytes)
                                                    extracted_text = docx2txt.process(docx_file)
                                            except: pass
                                                
                                            if extracted_text.strip():
                                                body += f"\n\n--- Attachment Content: {filename_str} ---\n"
                                                body += extracted_text[:settings["attachment_text_limit"]]
                                                body += "\n--- End Attachment ---"
                                    continue
                                    
                                if part.get_content_type() == "text/plain" and not body:
                                    try: body = part.get_payload(decode=True).decode(errors='ignore')
                                    except: pass
                                elif part.get_content_type() == "text/html" and not body:
                                    try:
                                        html_body = part.get_payload(decode=True).decode(errors='ignore')
                                        body = clean_text(html_body)
                                    except: pass
                        else:
                            try: body = msg.get_payload(decode=True).decode(errors='ignore')
                            except: pass
                            
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
                            "folder": folder_name
                        }):
                            account_state[folder_name] = uid
                            state[name] = account_state
                            save_state(state)
                            messages_processed += 1
                        else:
                            logger.warning("Memory backend is busy; deferring remaining email messages until the next cycle.")
                            save_status({
                                "service": "email-worker",
                                "status": "deferred",
                                "current_account": name,
                                "last_cycle_started_at": started_at,
                                "last_cycle_finished_at": utc_now(),
                                "items_processed": messages_processed,
                                "items_total": len(uids_to_process),
                                "details": {"folders_seen": folders_seen},
                                "updated_at": utc_now(),
                            })
                            return False
                    except Exception as e:
                        logger.error(f"Error processing email UID {uid}: {e}")
            
    except Exception as e:
        error_str = str(e)
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
            "details": {"folders_seen": folders_seen},
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
        "details": {"folders_seen": folders_seen},
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
