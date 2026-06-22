import importlib.util
import os
import sys
import unittest
from pathlib import Path


os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("AGENTMEMORY_TOKEN", "test")
os.environ.setdefault("REDIS_URL", "")
os.environ.setdefault("RERANKER_ENABLED", "false")

spec = importlib.util.spec_from_file_location("memorex_api_main", Path(__file__).with_name("main.py"))
main = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = main
spec.loader.exec_module(main)


class SearchPipelineTests(unittest.TestCase):
    def test_candidate_identity_includes_category(self):
        rows = [
            {"id": 7, "category": "agent", "distance": 0.1, "lexical_rank": 0, "created_at": None},
            {"id": 7, "category": "code", "distance": 0.2, "lexical_rank": 0, "created_at": None},
        ]
        results = main.combine_candidates("multi", rows, 10)
        self.assertEqual({row["category"] for row in results}, {"agent", "code"})

    def test_candidate_ranking_does_not_need_document_payload(self):
        rows = [{"id": 1, "distance": 0.2, "lexical_rank": 0, "created_at": None}]
        result = main.combine_candidates("code", rows, 1)[0]
        self.assertNotIn("document", result)
        self.assertNotIn("metadata", result)

    def test_metadata_projection_excludes_large_columns(self):
        projection = main.metadata_projection_for_columns(
            {"id", "document", "embedding", "embedding_status", "project", "source"}
        )
        self.assertIn("project", projection)
        self.assertIn("source", projection)
        self.assertNotIn("embedding'", projection)
        self.assertNotIn("document'", projection)


if __name__ == "__main__":
    unittest.main()
