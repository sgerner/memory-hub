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

class TokenTests(unittest.TestCase):
    def test_valid_token(self):
        with patch.object(api, "AUTH_TOKEN", "secret"):
            self.assertEqual(api.verify_token("Bearer secret"), "secret")

    def test_rejects_missing_or_malformed_authorization(self):
        with patch.object(api, "AUTH_TOKEN", "secret"):
            for value in [None, "", "Basic secret", "Bearer"]:
                with self.subTest(value=value), self.assertRaises(api.HTTPException) as error:
                    api.verify_token(value)
                self.assertEqual(error.exception.status_code, 401)

    def test_invalid_bearer_token_preserves_forbidden_status(self):
        with patch.object(api, "AUTH_TOKEN", "secret"):
            for value in ["Bearer ", "Bearer wrong", "Bearer secret extra", "Bearer sécret"]:
                with self.subTest(value=value), self.assertRaises(api.HTTPException) as error:
                    api.verify_token(value)
                self.assertEqual(error.exception.status_code, 403)

    def test_uses_constant_time_comparison(self):
        with patch.object(api.hmac, "compare_digest", return_value=False) as compare:
            with self.assertRaises(api.HTTPException):
                api.verify_token("Bearer candidate")
            compare.assert_called_once_with(b"candidate", api.AUTH_TOKEN.encode("utf-8"))

if __name__ == "__main__":
    unittest.main()
