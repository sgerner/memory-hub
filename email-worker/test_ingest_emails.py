import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ingest_emails as worker


MESSAGE_ID = "<message-1@example.test>"
HEADER = (
    b"Message-ID: <message-1@example.test>\r\n"
    b"Subject: Weekly update\r\n"
    b"From: sender@example.test\r\n"
    b"To: recipient@example.test\r\n"
    b"Date: Thu, 01 Jan 2026 00:00:00 +0000\r\n\r\n"
)
FULL_MESSAGE = HEADER + b"Content-Type: text/plain\r\n\r\nHello\r\n"


class FakeIMAPClient:
    def __init__(self, folders):
        self.folders = folders
        self.current_folder = None
        self.header_fetches = []
        self.full_fetches = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def login(self, _user, _password):
        return None

    def list_folders(self):
        return [(flags, b"/", name) for name, flags in self.folders]

    def select_folder(self, name, readonly=True):
        self.current_folder = name

    def search(self, _criteria):
        return [1]

    def fetch(self, uids, items):
        if items == worker.HEADER_FETCH_ITEMS:
            self.header_fetches.append((self.current_folder, list(uids)))
            return {
                uid: {
                    b"RFC822.HEADER": HEADER,
                    b"INTERNALDATE": "2026-01-01 00:00:00+00:00",
                }
                for uid in uids
            }

        self.full_fetches.append((self.current_folder, list(uids), list(items)))
        return {
            uid: {
                b"RFC822": FULL_MESSAGE,
                b"INTERNALDATE": "2026-01-01 00:00:00+00:00",
            }
            for uid in uids
        }


class EmailWorkerTests(unittest.TestCase):
    def test_all_mail_detection_and_header_parsing(self):
        self.assertTrue(worker.is_all_mail_folder([b"\\All"], "Archive"))
        self.assertTrue(worker.is_all_mail_folder([], "[Gmail]/All Mail"))
        self.assertFalse(worker.is_all_mail_folder([b"\\Inbox"], "Inbox"))

        summary = worker.parse_message_headers(
            7,
            {b"RFC822.HEADER": HEADER, b"INTERNALDATE": "internal-date"},
        )
        self.assertEqual(summary["uid"], 7)
        self.assertEqual(summary["message_id"], "message-1@example.test")
        self.assertEqual(summary["subject"], "Weekly update")
        self.assertEqual(worker.message_dedupe_key(summary), MESSAGE_ID[1:-1])

    def test_overlapping_non_canonical_folders_fetch_one_full_message(self):
        fake_client = FakeIMAPClient([
            ("Inbox", [b"\\Inbox"]),
            ("Archive", []),
        ])
        pushed = []
        statuses = []

        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            with patch.object(worker, "IMAPClient", return_value=fake_client), \
                 patch.object(worker, "STATE_PATH", str(state_path)), \
                 patch.object(worker, "save_status", side_effect=statuses.append), \
                 patch.object(worker, "push_to_memory", side_effect=lambda data: pushed.append(data) or True):
                self.assertTrue(worker.process_account(
                    {"name": "test", "host": "imap.example.test", "user": "u", "password": "p"},
                    {"batch_size": 200, "attachment_text_limit": 50000},
                ))

        self.assertEqual(len(pushed), 1)
        self.assertEqual(len(fake_client.full_fetches), 1)
        self.assertEqual(len(fake_client.header_fetches), 2)
        self.assertEqual(statuses[-1]["details"]["deduplicated"], 1)

    def test_all_mail_skips_redundant_label_without_fetching_headers(self):
        fake_client = FakeIMAPClient([
            ("[Gmail]/All Mail", [b"\\All"]),
            ("INBOX", [b"\\Inbox"]),
        ])
        pushed = []

        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            with patch.object(worker, "IMAPClient", return_value=fake_client), \
                 patch.object(worker, "STATE_PATH", str(state_path)), \
                 patch.object(worker, "save_status"), \
                 patch.object(worker, "push_to_memory", side_effect=lambda data: pushed.append(data) or True):
                self.assertTrue(worker.process_account(
                    {"name": "test", "host": "imap.example.test", "user": "u", "password": "p"},
                    {"batch_size": 200, "attachment_text_limit": 50000},
                ))

        self.assertEqual(len(pushed), 1)
        self.assertEqual(len(fake_client.full_fetches), 1)
        self.assertEqual(fake_client.header_fetches, [("[Gmail]/All Mail", [1])])


if __name__ == "__main__":
    unittest.main()
