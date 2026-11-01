import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location("worker_under_test", Path(__file__).with_name("ingest_emails.py"))
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

class FolderTests(unittest.TestCase):
    def test_names_are_exact_and_use_server_delimiter(self):
        for name, delimiter, expected in [
            ("Home/Junk Removal", "/", "normal"),
            ("Trash Pickup", "/", "normal"),
            ("Bulk Orders", "/", "normal"),
            ("Spam Reports", "/", "normal"),
            ("Contracts/Drafts from Legal", "/", "normal"),
            ("INBOX.Trash", ".", "quarantine"),
            ("[Gmail]/Trash", b"/", "quarantine"),
            ("Junk E-mail", None, "quarantine"),
            ("Drafts", None, "draft"),
        ]:
            with self.subTest(name=name):
                self.assertEqual(worker.classify_folder([], name, delimiter), expected)

    def test_special_use_flags_override_name_and_disable_name_fallback(self):
        self.assertEqual(worker.classify_folder([b"\\Drafts"], "Trash", "/"), "draft")
        self.assertEqual(worker.classify_folder([b"\\Junk"], "Anything", "/"), "quarantine")
        self.assertEqual(worker.classify_folder([], "Trash", "/", {"\\trash"}), "normal")
        self.assertEqual(worker.classify_folder([], "Drafts", "/", {"\\drafts"}), "normal")

if __name__ == "__main__":
    unittest.main()
