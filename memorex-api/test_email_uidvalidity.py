import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("AGENTMEMORY_TOKEN", "test")
os.environ["RERANKER_ENABLED"] = "false"
os.environ["REDIS_URL"] = ""
spec = importlib.util.spec_from_file_location("api_under_test", Path(__file__).with_name("main.py"))
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
spec.loader.exec_module(api)

class EmailIdentityTests(unittest.TestCase):
    def test_uid_reuse_in_new_epoch_is_inserted(self):
        cursor = MagicMock()
        # No row for the new epoch, then the inserted row ID.
        cursor.fetchone.side_effect = [None, {"id": 2}]
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        with patch.object(api, "get_db_connection") as db, patch.object(api, "_ensure_table"), patch.object(api, "invalidate_search_cache"):
            db.return_value.__enter__.return_value = conn
            result = api.remember(api.MemoryCreate(content="new mail", category="emails", metadata=dict(account="mine", folder="INBOX", uid="1", uidvalidity="11")))
        query, values = cursor.execute.call_args_list[0].args
        self.assertIn("uidvalidity = %s", query)
        self.assertEqual(values, ("mine", "INBOX", "1", "11"))
        self.assertFalse(result["memory"].get("deduplicated", False))

    def test_current_epoch_still_deduplicates(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"id": 1}
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        with patch.object(api, "get_db_connection") as db, patch.object(api, "_ensure_table"):
            db.return_value.__enter__.return_value = conn
            result = api.remember(api.MemoryCreate(content="same mail", category="emails", metadata=dict(account="mine", folder="INBOX", uid="1", uidvalidity="11")))
        self.assertTrue(result["memory"]["deduplicated"])
        self.assertEqual(cursor.execute.call_count, 1)

    def test_message_id_deduplicates_across_uidvalidity_epochs(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"id": 7}
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        with patch.object(api, "get_db_connection") as db, patch.object(api, "_ensure_table"):
            db.return_value.__enter__.return_value = conn
            result = api.remember(api.MemoryCreate(
                content="same mail",
                category="emails",
                metadata=dict(
                    account="mine", folder="INBOX", uid="1", uidvalidity="12",
                    message_id="message-1@example.test",
                ),
            ))

        query, values = cursor.execute.call_args.args
        self.assertIn("account = %s AND message_id = %s", query)
        self.assertEqual(values, ("mine", "message-1@example.test"))
        self.assertTrue(result["memory"]["deduplicated"])
        self.assertEqual(cursor.execute.call_count, 1)

    def test_legacy_client_only_matches_rows_without_uidvalidity(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"id": 8}
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        with patch.object(api, "get_db_connection") as db, \
             patch.object(api, "_ensure_table"), \
             patch.object(api, "existing_columns", return_value={"uidvalidity"}):
            db.return_value.__enter__.return_value = conn
            result = api.remember(api.MemoryCreate(
                content="legacy mail",
                category="emails",
                metadata=dict(account="mine", folder="INBOX", uid="1"),
            ))

        query, values = cursor.execute.call_args.args
        self.assertIn("uidvalidity IS NULL", query)
        self.assertEqual(values, ("mine", "INBOX", "1"))
        self.assertTrue(result["memory"]["deduplicated"])

    def test_delete_by_uid_is_scoped_to_uidvalidity(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [{"id": 7}]
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        with patch.object(api, "get_db_connection") as db, \
             patch.object(api, "existing_columns", return_value={"uidvalidity"}), \
             patch.object(api, "invalidate_search_cache"):
            db.return_value.__enter__.return_value = conn
            result = api.delete_email(api.EmailDelete(
                account="mine", folder="INBOX", uid="1", uidvalidity="12",
            ))

        query, values = cursor.execute.call_args.args
        self.assertIn("account = %s AND folder = %s AND uid = %s AND uidvalidity = %s", query)
        self.assertEqual(values, ["mine", "INBOX", "1", "12"])
        self.assertEqual(result["deleted_ids"], [7])

    def test_delete_legacy_rows_can_use_crossfolder_metadata_fallback(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [{"id": 7}]
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        with patch.object(api, "get_db_connection") as db, \
             patch.object(api, "existing_columns", return_value={"account", "folder", "uid", "subject", "sender"}), \
             patch.object(api, "invalidate_search_cache"):
            db.return_value.__enter__.return_value = conn
            result = api.delete_email(api.EmailDelete(
                account="mine", folder="Trash", uid="1", uidvalidity="12",
                subject="same subject", sender="sender@example.test",
            ))
        query, values = cursor.execute.call_args.args
        self.assertNotIn("uid =", query)
        self.assertEqual(values, ["mine", "same subject", "sender@example.test"])
        self.assertEqual(result["deleted_ids"], [7])

if __name__ == "__main__":
    unittest.main()
