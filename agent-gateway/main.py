import asyncio
import contextlib
import hmac
import os
import re
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


BACKEND_URL = os.getenv("MEMORY_BACKEND_URL", "http://agentmemory:3111").rstrip("/")
BACKEND_TOKEN = os.getenv("MEMORY_BACKEND_TOKEN", "")
GATEWAY_TOKEN = os.getenv("MEMORY_GATEWAY_TOKEN", "")
ADMIN_TOKEN = os.getenv("MEMORY_ADMIN_TOKEN", "")
DEFAULT_CATEGORIES = [
    value.strip()
    for value in os.getenv(
        "MEMORY_CATEGORIES", "agent,emails,obsidian,documents,code"
    ).split(",")
    if value.strip()
]
MCP_ALLOWED_HOSTS = [
    value.strip()
    for value in os.getenv(
        "MCP_ALLOWED_HOSTS", "127.0.0.1:*,localhost:*,memory-agent-gateway:*"
    ).split(",")
    if value.strip()
]
MCP_ALLOWED_ORIGINS = [
    value.strip()
    for value in os.getenv("MCP_ALLOWED_ORIGINS", "").split(",")
    if value.strip()
]
CATEGORY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
METADATA_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
MANAGED_METADATA = {
    "lifecycle_status",
    "memory_kind",
    "importance",
    "confidence",
    "retention",
    "recorded_at",
    "last_recalled_at",
    "created_by",
    "modified_by",
    "supersedes_id",
    "forget_reason",
    "archived_at",
    "forgotten_at",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def verify_configuration() -> None:
    missing = [
        name
        for name, value in {
            "MEMORY_BACKEND_TOKEN": BACKEND_TOKEN,
            "MEMORY_GATEWAY_TOKEN": GATEWAY_TOKEN,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"Required configuration is missing: {', '.join(missing)}")


def valid_token(token: str, expected: str) -> bool:
    return bool(expected) and hmac.compare_digest(token, expected)


def bearer_value(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        return ""
    return authorization.removeprefix("Bearer ").strip()


async def require_gateway_token(authorization: str | None = Header(default=None)) -> None:
    if not valid_token(bearer_value(authorization), GATEWAY_TOKEN):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


async def require_admin_token(authorization: str | None = Header(default=None)) -> None:
    if not valid_token(bearer_value(authorization), ADMIN_TOKEN):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def validate_category(category: str) -> str:
    if not CATEGORY_PATTERN.fullmatch(category):
        raise ValueError("Category must use lowercase letters, digits, and underscores")
    if category not in DEFAULT_CATEGORIES:
        raise ValueError(f"Category is not enabled: {category}")
    return category


def require_category(category: str) -> str:
    try:
        return validate_category(category)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


def validate_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        if not METADATA_KEY_PATTERN.fullmatch(key):
            raise ValueError(f"Invalid metadata key: {key}")
        if key in MANAGED_METADATA:
            raise ValueError(f"Metadata key is lifecycle-managed: {key}")
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            raise ValueError(f"Metadata value must be scalar: {key}")
        output[key] = value
    return output


class MemoryStore(BaseModel):
    content: str = Field(min_length=1, max_length=500_000)
    category: str = "agent"
    kind: Literal["observation", "fact", "preference", "decision", "procedure", "episode"] = "fact"
    importance: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=0.8, ge=0, le=1)
    retention: Literal["ephemeral", "normal", "durable"] = "normal"
    source_agent: str = Field(default="unknown", max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("category")
    @classmethod
    def category_is_valid(cls, value: str) -> str:
        return validate_category(value)

    @field_validator("metadata")
    @classmethod
    def metadata_is_valid(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_metadata(value)


class MemoryRecall(BaseModel):
    query: str = Field(min_length=1, max_length=10_000)
    categories: list[str] | None = None
    limit: int = Field(default=8, ge=1, le=50)
    include_inactive: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("categories")
    @classmethod
    def categories_are_valid(cls, value: list[str] | None) -> list[str] | None:
        if value is not None:
            for category in value:
                validate_category(category)
        return value

    @field_validator("metadata")
    @classmethod
    def metadata_is_valid(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_metadata(value)


class MemoryPatch(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=500_000)
    source_agent: str = Field(default="unknown", max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def metadata_is_valid(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_metadata(value)


class LifecycleReason(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    source_agent: str = Field(default="unknown", max_length=120)


class MemorySupersede(MemoryStore):
    previous_category: str
    previous_id: str
    reason: str = Field(default="Superseded by a corrected or newer memory", max_length=500)

    @field_validator("previous_category")
    @classmethod
    def previous_category_is_valid(cls, value: str) -> str:
        return validate_category(value)


class Backend:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            base_url=BACKEND_URL,
            timeout=httpx.Timeout(45),
            headers={"Authorization": f"Bearer {BACKEND_TOKEN}"},
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.post(path, json=payload)
        return self._response(response)

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await self.client.get(path, params=params)
        return self._response(response)

    @staticmethod
    def _response(response: httpx.Response) -> dict[str, Any]:
        if response.is_error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Memory backend error ({response.status_code})",
            )
        return response.json()


class MemoryService:
    def __init__(self, backend: Backend) -> None:
        self.backend = backend

    async def store(self, item: MemoryStore, supersedes_id: str | None = None) -> dict[str, Any]:
        metadata = {
            **item.metadata,
            "source": item.metadata.get("source", "agent"),
            "lifecycle_status": "active",
            "memory_kind": item.kind,
            "importance": item.importance,
            "confidence": item.confidence,
            "retention": item.retention,
            "recorded_at": utc_now(),
            "created_by": item.source_agent,
            "needs_enrichment": False,
        }
        if supersedes_id is not None:
            metadata["supersedes_id"] = supersedes_id
        result = await self.backend.post(
            "/remember",
            {"content": item.content, "category": item.category, "metadata": metadata},
        )
        return {"category": item.category, **result["memory"]}

    async def recall(self, request: MemoryRecall) -> dict[str, Any]:
        categories = request.categories or DEFAULT_CATEGORIES
        candidate_limit = min(100, request.limit * 3)
        combined: list[dict[str, Any]] = []

        try:
            result = await self.backend.post(
                "/search-multi",
                {
                    "query": request.query,
                    "categories": categories,
                    "limit": candidate_limit,
                    "metadata": request.metadata or None,
                },
            )
            for memory in result.get("results", []):
                lifecycle = memory.get("metadata", {}).get("lifecycle_status", "active")
                if request.include_inactive or lifecycle == "active":
                    combined.append(memory)
        except HTTPException:
            results = await asyncio.gather(
                *[
                    self.backend.post(
                        "/search",
                        {
                            "query": request.query,
                            "category": category,
                            "limit": candidate_limit,
                            "metadata": request.metadata or None,
                        },
                    )
                    for category in categories
                ]
            )
            for category, result in zip(categories, results):
                for memory in result.get("results", []):
                    lifecycle = memory.get("metadata", {}).get("lifecycle_status", "active")
                    if request.include_inactive or lifecycle == "active":
                        combined.append({"category": category, **memory})

        combined.sort(
            key=lambda row: (
                -float(row.get("score") or 0),
                float(row.get("distance") or 99),
                -float(row.get("lexical_rank") or 0),
            )
        )
        return {"results": combined[: request.limit], "searched_categories": categories}

    async def list_memories(
        self, category: str, limit: int = 25, include_inactive: bool = False, offset: int = 0
    ) -> dict[str, Any]:
        result = await self.backend.get(f"/memories/{category}", {"limit": limit, "offset": offset})
        memories = []
        for memory in result.get("memories", []):
            lifecycle = memory.get("metadata", {}).get("lifecycle_status", "active")
            if include_inactive or lifecycle == "active":
                memories.append({"category": category, **memory})
        return {
            "category": category,
            "memories": memories,
            "requested_limit": limit,
            "offset": offset,
            "has_more": len(result.get("memories", [])) == limit,
        }

    async def overview(self, sample_limit: int = 20) -> dict[str, Any]:
        batches = await asyncio.gather(
            *[self.list_memories(category, sample_limit, True) for category in DEFAULT_CATEGORIES]
        )
        statuses = {"active": 0, "archived": 0, "forgotten": 0}
        categories = []
        latest = []
        for batch in batches:
            memories = batch["memories"]
            active = 0
            for memory in memories:
                lifecycle = memory.get("metadata", {}).get("lifecycle_status", "active")
                statuses[lifecycle] = statuses.get(lifecycle, 0) + 1
                active += lifecycle == "active"
                latest.append(memory)
            categories.append(
                {
                    "category": batch["category"],
                    "loaded": len(memories),
                    "active": active,
                    "sample_limit": sample_limit,
                }
            )
        latest.sort(
            key=lambda memory: str(
                memory.get("metadata", {}).get("updated_at")
                or memory.get("metadata", {}).get("created_at")
                or ""
            ),
            reverse=True,
        )
        return {
            "categories": categories,
            "loaded_statuses": statuses,
            "recent": latest[:10],
            "sample_limit": sample_limit,
            "generated_at": utc_now(),
        }

    async def queue_status(self) -> dict[str, Any]:
        return await self.backend.get("/queue-status")

    async def patch(self, category: str, memory_id: str, patch: MemoryPatch) -> dict[str, Any]:
        metadata = {**patch.metadata, "modified_by": patch.source_agent}
        await self.backend.post(
            "/update",
            {"category": category, "id": memory_id, "content": patch.content, "metadata": metadata},
        )
        return {"success": True, "category": category, "id": memory_id}

    async def archive(self, category: str, memory_id: str, request: LifecycleReason) -> dict[str, Any]:
        await self.backend.post(
            "/update",
            {
                "category": category,
                "id": memory_id,
                "metadata": {
                    "lifecycle_status": "archived",
                    "archived_at": utc_now(),
                    "forget_reason": request.reason,
                    "modified_by": request.source_agent,
                },
            },
        )
        return {"success": True, "category": category, "id": memory_id, "status": "archived"}

    async def forget(self, category: str, memory_id: str, request: LifecycleReason) -> dict[str, Any]:
        await self.backend.post(
            "/update",
            {
                "category": category,
                "id": memory_id,
                "metadata": {
                    "lifecycle_status": "forgotten",
                    "forgotten_at": utc_now(),
                    "forget_reason": request.reason,
                    "modified_by": request.source_agent,
                },
            },
        )
        return {"success": True, "category": category, "id": memory_id, "status": "forgotten"}

    async def supersede(self, request: MemorySupersede) -> dict[str, Any]:
        created = await self.store(request, supersedes_id=request.previous_id)
        await self.archive(
            request.previous_category,
            request.previous_id,
            LifecycleReason(reason=request.reason, source_agent=request.source_agent),
        )
        return {"success": True, "new_memory": created, "superseded_id": request.previous_id}


backend = Backend()
service = MemoryService(backend)
mcp = FastMCP(
    "Personal Memory Hub",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=MCP_ALLOWED_HOSTS,
        allowed_origins=MCP_ALLOWED_ORIGINS,
    ),
)


@mcp.tool()
async def memory_recall(
    query: str,
    categories: list[str] | None = None,
    limit: int = 3,
    include_inactive: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Semantically search personal memories. Archived and forgotten items are hidden by default."""
    return await service.recall(
        MemoryRecall(
            query=query,
            categories=categories,
            limit=limit,
            include_inactive=include_inactive,
            metadata=metadata or {},
        )
    )


@mcp.tool()
async def memory_store(
    content: str,
    category: str = "agent",
    kind: str = "fact",
    importance: float = 0.5,
    confidence: float = 0.8,
    retention: str = "normal",
    source_agent: str = "unknown",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store a durable agent memory with lifecycle and provenance metadata."""
    return await service.store(
        MemoryStore(
            content=content,
            category=category,
            kind=kind,
            importance=importance,
            confidence=confidence,
            retention=retention,
            source_agent=source_agent,
            metadata=metadata or {},
        )
    )


@mcp.tool()
async def memory_patch(
    category: str,
    memory_id: str,
    content: str | None = None,
    source_agent: str = "unknown",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Amend memory content or non-lifecycle metadata without replacing its identity."""
    require_category(category)
    return await service.patch(
        category,
        memory_id,
        MemoryPatch(content=content, source_agent=source_agent, metadata=metadata or {}),
    )


@mcp.tool()
async def memory_list(
    category: str = "agent",
    limit: int = 25,
    offset: int = 0,
    include_inactive: bool = False,
) -> dict[str, Any]:
    """List recent memories in a category with simple pagination for inspection workflows."""
    require_category(category)
    if limit < 1 or limit > 250:
        raise ValueError("limit must be between 1 and 250")
    if offset < 0:
        raise ValueError("offset must be zero or greater")
    return await service.list_memories(category, limit, include_inactive, offset)


@mcp.tool()
async def memory_overview(sample_limit: int = 10) -> dict[str, Any]:
    """Return a compact category overview and recent memory sample."""
    if sample_limit < 1 or sample_limit > 100:
        raise ValueError("sample_limit must be between 1 and 100")
    return await service.overview(sample_limit)


@mcp.tool()
async def memory_queue_status() -> dict[str, Any]:
    """Return embedding and enrichment backlog counts by category."""
    return await service.queue_status()


@mcp.tool()
async def memory_supersede(
    previous_category: str,
    previous_id: str,
    content: str,
    category: str = "agent",
    kind: str = "fact",
    source_agent: str = "unknown",
    reason: str = "Superseded by a corrected or newer memory",
) -> dict[str, Any]:
    """Replace an obsolete memory while preserving history and linking the new version."""
    return await service.supersede(
        MemorySupersede(
            previous_category=previous_category,
            previous_id=previous_id,
            content=content,
            category=category,
            kind=kind,
            source_agent=source_agent,
            reason=reason,
        )
    )


@mcp.tool()
async def memory_archive(
    category: str, memory_id: str, reason: str, source_agent: str = "unknown"
) -> dict[str, Any]:
    """Remove a stale memory from normal recall while retaining its audit history."""
    require_category(category)
    return await service.archive(
        category, memory_id, LifecycleReason(reason=reason, source_agent=source_agent)
    )


@mcp.tool()
async def memory_forget(
    category: str, memory_id: str, reason: str, source_agent: str = "unknown"
) -> dict[str, Any]:
    """Soft-delete a memory from normal recall; physical purging remains administrative."""
    require_category(category)
    return await service.forget(
        category, memory_id, LifecycleReason(reason=reason, source_agent=source_agent)
    )


class MCPBearerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Any:
        if not valid_token(bearer_value(request.headers.get("Authorization")), GATEWAY_TOKEN):
            return JSONResponse({"detail": "Unauthorized"}, status_code=status.HTTP_401_UNAUTHORIZED)
        return await call_next(request)


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    verify_configuration()
    async with mcp.session_manager.run():
        yield
    await backend.close()


app = FastAPI(title="Personal Memory Hub Gateway", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "memory-agent-gateway"}


@app.post("/v1/memories", dependencies=[Depends(require_gateway_token)])
async def store_memory(item: MemoryStore) -> dict[str, Any]:
    return await service.store(item)


@app.post("/v1/recall", dependencies=[Depends(require_gateway_token)])
async def recall_memory(request: MemoryRecall) -> dict[str, Any]:
    return await service.recall(request)


@app.get("/v1/overview", dependencies=[Depends(require_gateway_token)])
async def overview(sample_limit: int = 20) -> dict[str, Any]:
    if sample_limit < 1 or sample_limit > 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="sample_limit must be between 1 and 100",
        )
    return await service.overview(sample_limit)


@app.get("/v1/queue-status", dependencies=[Depends(require_gateway_token)])
async def queue_status() -> dict[str, Any]:
    return await service.queue_status()


@app.get("/v1/memories/{category}", dependencies=[Depends(require_gateway_token)])
async def list_memories(
    category: str, limit: int = 25, include_inactive: bool = False, offset: int = 0
) -> dict[str, Any]:
    require_category(category)
    if limit < 1 or limit > 250:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="limit must be between 1 and 250",
        )
    if offset < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="offset must be zero or greater",
        )
    return await service.list_memories(category, limit, include_inactive, offset)


@app.patch("/v1/memories/{category}/{memory_id}", dependencies=[Depends(require_gateway_token)])
async def patch_memory(category: str, memory_id: str, patch: MemoryPatch) -> dict[str, Any]:
    require_category(category)
    return await service.patch(category, memory_id, patch)


@app.post(
    "/v1/memories/{category}/{memory_id}/archive", dependencies=[Depends(require_gateway_token)]
)
async def archive_memory(
    category: str, memory_id: str, request: LifecycleReason
) -> dict[str, Any]:
    require_category(category)
    return await service.archive(category, memory_id, request)


@app.post(
    "/v1/memories/{category}/{memory_id}/forget", dependencies=[Depends(require_gateway_token)]
)
async def forget_memory(
    category: str, memory_id: str, request: LifecycleReason
) -> dict[str, Any]:
    require_category(category)
    return await service.forget(category, memory_id, request)


@app.post("/v1/memories/supersede", dependencies=[Depends(require_gateway_token)])
async def supersede_memory(request: MemorySupersede) -> dict[str, Any]:
    return await service.supersede(request)


@app.delete("/v1/memories/{category}/{memory_id}", dependencies=[Depends(require_admin_token)])
async def purge_memory(category: str, memory_id: str) -> dict[str, Any]:
    require_category(category)
    await backend.post("/delete", {"category": category, "id": memory_id})
    return {"success": True, "category": category, "id": memory_id, "status": "purged"}


# Registered HTTP routes match first; the catch-all serves Streamable HTTP at /mcp.
protected_mcp_app = MCPBearerMiddleware(mcp.streamable_http_app())
app.mount("/", protected_mcp_app)
