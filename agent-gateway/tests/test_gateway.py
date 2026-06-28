import importlib

from fastapi.testclient import TestClient


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def post(self, path: str, payload: dict) -> dict:
        self.calls.append((path, payload))
        if path == "/remember":
            return {
                "memory": {
                    "id": "new-1",
                    "document": payload["content"],
                    "metadata": payload["metadata"],
                }
            }
        if path == "/search":
            return {
                "results": [
                    {"id": "active-1", "document": "active", "metadata": {}, "distance": 0.2},
                    {
                        "id": "hidden-1",
                        "document": "hidden",
                        "metadata": {"lifecycle_status": "forgotten"},
                        "distance": 0.1,
                    },
                ]
            }
        if path == "/search-multi":
            return {
                "results": [
                    {
                        "id": "active-1",
                        "category": "agent",
                        "document": "active",
                        "metadata": {},
                        "distance": 0.2,
                    },
                    {
                        "id": "hidden-1",
                        "category": "agent",
                        "document": "hidden",
                        "metadata": {"lifecycle_status": "forgotten"},
                        "distance": 0.1,
                    },
                ]
            }
        return {"success": True}

    async def get(self, path: str, params: dict | None = None) -> dict:
        self.calls.append((path, params or {}))
        if path == "/memories/agent/recent-1":
            return {
                "memory": {
                    "id": "recent-1",
                    "document": "recent details",
                    "metadata": {"lifecycle_status": "active"},
                }
            }
        return {
            "memories": [
                {"id": "recent-1", "document": "recent", "metadata": {}},
                {
                    "id": "archived-1",
                    "document": "old",
                    "metadata": {"lifecycle_status": "archived"},
                },
            ]
        }


def app(monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND_TOKEN", "backend-test")
    monkeypatch.setenv("MEMORY_GATEWAY_TOKEN", "gateway-test")
    monkeypatch.setenv("MEMORY_ADMIN_TOKEN", "admin-test")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "testserver")

    import main

    module = importlib.reload(main)
    module.service.backend = FakeBackend()
    return module


def test_rest_lifecycle_and_auth(monkeypatch):
    module = app(monkeypatch)
    headers = {"Authorization": "Bearer gateway-test"}

    with TestClient(module.app) as client:
        assert client.post("/v1/memories", json={"content": "x"}).status_code == 401

        stored = client.post(
            "/v1/memories",
            headers=headers,
            json={"content": "remember this", "source_agent": "test"},
        ).json()
        assert stored["metadata"]["lifecycle_status"] == "active"
        assert stored["metadata"]["created_by"] == "test"

        recalled = client.post(
            "/v1/recall",
            headers=headers,
            json={"query": "x", "categories": ["agent"]},
        ).json()
        assert [result["id"] for result in recalled["results"]] == ["active-1"]

        invalid = client.patch(
            "/v1/memories/Bad/id",
            headers=headers,
            json={"content": "x"},
        )
        assert invalid.status_code == 422

        overview = client.get("/v1/overview?sample_limit=2", headers=headers).json()
        assert overview["sample_limit"] == 2
        assert overview["loaded_statuses"]["archived"] == 5

        listed = client.get(
            "/v1/memories/agent?limit=10&offset=0&include_inactive=false", headers=headers
        ).json()
        assert [memory["id"] for memory in listed["memories"]] == ["recent-1"]
        assert listed["offset"] == 0

        fetched = client.get("/v1/memories/agent/recent-1", headers=headers).json()
        assert fetched["id"] == "recent-1"
        assert fetched["category"] == "agent"
        assert fetched["document"] == "recent details"


def test_streamable_http_mcp_lists_memory_tools(monkeypatch):
    module = app(monkeypatch)

    with TestClient(module.app) as client:
        assert client.post("/mcp", json={}).status_code == 401
        headers = {
            "Authorization": "Bearer gateway-test",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        initialized = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke", "version": "1"},
                },
            },
        )
        assert initialized.status_code == 200
        tools = client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert tools.status_code == 200
        assert "memory_recall" in tools.text
        assert "memory_store" in tools.text
        assert "memory_list" in tools.text
        assert "memory_get" in tools.text
        assert "memory_overview" in tools.text
        assert "memory_queue_status" in tools.text
        assert "memory_forget" in tools.text
