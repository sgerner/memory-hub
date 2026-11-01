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

class PurgeTests(unittest.TestCase):
    def test_missing_message_id_purges_across_folders_and_keeps_other_accounts(self):
        rows = [
            dict(id=1, account="mine", folder="All Mail", uid="9001", subject="Letter", sender="sender", receiver="me", date="today"),
            dict(id=2, account="other", folder="All Mail", uid="9001", subject="Letter", sender="sender", receiver="me", date="today"),
        ]
        cursor = MagicMock()
        def execute(sql, values):
            fields = [part.split(" = ")[0] for part in sql.split(" WHERE ")[1].split(" RETURNING")[0].split(" AND ")]
            deleted = [row for row in rows if all(row.get(key) == value for key, value in zip(fields, values))]
            cursor.fetchall.return_value = [{"id": row["id"]} for row in deleted]
            for row in deleted:
                rows.remove(row)
        cursor.execute.side_effect = execute
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        with patch.object(api, "get_db_connection") as db, patch.object(api, "existing_columns", return_value=set(rows[0])), patch.object(api, "invalidate_search_cache"):
            db.return_value.__enter__.return_value = conn
            result = api.delete_email(api.EmailDelete(account="mine", folder="Trash", uid="312", subject="Letter", sender="sender", receiver="me", date="today"))
        self.assertEqual(result["deleted_ids"], [1])
        self.assertEqual([r["id"] for r in rows], [2])

    def test_one_fallback_field_is_not_enough(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        with patch.object(api, "get_db_connection") as db, patch.object(api, "existing_columns", return_value={"account", "folder", "uid", "subject"}), patch.object(api, "invalidate_search_cache"):
            db.return_value.__enter__.return_value = conn
            api.delete_email(api.EmailDelete(account="mine", folder="Trash", uid="312", subject="Letter"))
        self.assertEqual(cursor.execute.call_count, 1)

if __name__ == "__main__":
    unittest.main()
