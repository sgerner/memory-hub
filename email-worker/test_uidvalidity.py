import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location("worker_under_test", Path(__file__).with_name("ingest_emails.py"))
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

class EpochTests(unittest.TestCase):
    def test_changed_epoch_and_legacy_cursor_rescan_uid_one(self):
        for cursor, validity, expected in [
            ({"uid": 48211, "uidvalidity": "10"}, 11, "1:*"),
            (48211, 11, "1:*"),
            ({"uid": 1, "uidvalidity": "11"}, 11, "2:*"),
        ]:
            with self.subTest(cursor=cursor), tempfile.TemporaryDirectory() as directory:
                state_path = Path(directory) / "state.json"
                state_path.write_text(json.dumps({"mine": {"INBOX": cursor}}))
                client = MagicMock()
                client.list_folders.return_value = [([], b"/", "INBOX")]
                client.select_folder.return_value = {b"UIDVALIDITY": validity}
                client.search.return_value = [1]
                client.fetch.return_value = {1: {b"RFC822": b"Subject: hi\r\n\r\nbody", b"INTERNALDATE": "today"}}
                summary = {1: {"uid": 1, "subject": "hi", "from": "a", "to": "b", "date": "today", "message_id": ""}}
                with patch.object(worker, "STATE_PATH", str(state_path)), patch.object(worker, "save_status"), patch.object(worker, "IMAPClient") as factory, patch.object(worker, "fetch_message_headers", return_value=summary), patch.object(worker, "push_to_memory", return_value=True) as push:
                    factory.return_value.__enter__.return_value = client
                    worker.process_account(dict(name="mine", host="imap", user="me", password="test"), {"batch_size": 10, "attachment_text_limit": 100})
                    client.search.assert_called_once_with(["UID", expected])
                    if expected == "1:*":
                        self.assertEqual(push.call_args.args[0]["uidvalidity"], "11")
                        self.assertEqual(json.loads(state_path.read_text())["mine"]["INBOX"], {"uid": 1, "uidvalidity": "11"})
                    else:
                        push.assert_not_called()

    def test_epoch_change_during_header_scan_defers_without_advancing_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            client = MagicMock()
            client.list_folders.return_value = [([], b"/", "INBOX")]
            client.select_folder.side_effect = [
                {b"UIDVALIDITY": 10},
                {b"UIDVALIDITY": 11},
            ]
            client.search.return_value = [1]
            summary = {1: {"uid": 1, "subject": "hi", "from": "a", "to": "b", "date": "today", "message_id": ""}}
            statuses = []

            with patch.object(worker, "STATE_PATH", str(state_path)), \
                 patch.object(worker, "save_status", side_effect=statuses.append), \
                 patch.object(worker, "IMAPClient") as factory, \
                 patch.object(worker, "fetch_message_headers", return_value=summary), \
                 patch.object(worker, "push_to_memory", return_value=True) as push:
                factory.return_value.__enter__.return_value = client
                worker.process_account(
                    dict(name="mine", host="imap", user="me", password="test"),
                    {"batch_size": 10, "attachment_text_limit": 100},
                )

            push.assert_not_called()
            self.assertFalse(state_path.exists())
            self.assertEqual(statuses[-1]["status"], "deferred")
            self.assertIn("UIDVALIDITY changed", statuses[-1]["last_error"])

if __name__ == "__main__":
    unittest.main()
