# Personal Memory Hub

This directory contains source ingestion workers and an agent-facing gateway over the
existing Memorex Postgres/vector API.

## Agent gateway

`agent-gateway` is a separate container so the ingestion workers remain unchanged. It
exposes:

- `POST /mcp`: Streamable HTTP MCP server for agents.
- `POST /v1/recall`: semantic recall across enabled memory categories.
- `GET /v1/overview`: bounded recent-record summary for the dashboard.
- `GET /v1/memories/{category}`: browse recent records and lifecycle state.
- `POST /v1/memories`: store an agent-authored memory.
- `PATCH /v1/memories/{category}/{id}`: amend content or ordinary metadata.
- `POST /v1/memories/supersede`: store a corrected memory and archive the old record.
- `POST /v1/memories/{category}/{id}/archive`: remove stale content from normal recall.
- `POST /v1/memories/{category}/{id}/forget`: soft-delete from normal recall.
- `DELETE /v1/memories/{category}/{id}`: irreversible purge, admin token only.

MCP tools mirror the ordinary operations: `memory_recall`, `memory_store`,
`memory_patch`, `memory_supersede`, `memory_archive`, and `memory_forget`.

`dashboard` is a SvelteKit/Svelte 5 application styled with Skeleton v4. It is
intended to be exposed only behind Authentik and calls the gateway from its Node server,
so the agent bearer token is not delivered to browsers.

## Lifecycle

The existing database stores metadata as per-category columns. The gateway therefore
uses a small metadata lifecycle rather than migrating or replacing the existing
database:

| Field | Values / purpose |
| --- | --- |
| `lifecycle_status` | `active`, `archived`, or `forgotten`; recall hides inactive rows |
| `memory_kind` | `observation`, `fact`, `preference`, `decision`, `procedure`, or `episode` |
| `confidence` / `importance` | Agent-provided values from `0` to `1` |
| `retention` | `ephemeral`, `normal`, or `durable` |
| `recorded_at`, `created_by`, `modified_by` | Provenance |
| `supersedes_id` | Previous record identifier for corrected memories |

Legacy ingested data without `lifecycle_status` remains recallable as active. Source
workers can be moved to the gateway later if their records also need lifecycle fields.
This deliberately omits automatic decay and LLM consolidation initially: the current
enricher already summarizes source records, and automated forgetting is a bad default
for personal archives.

## Authentication

The gateway uses separate bearer tokens:

- `MEMORY_GATEWAY_TOKEN` is for MCP and normal REST reads/writes.
- `MEMORY_ADMIN_TOKEN` is only for permanent deletion.
- `MEMORY_BACKEND_TOKEN` stays inside the gateway and authenticates it to the current
  internal API.

This is appropriate for personal agents controlled by one operator. If untrusted users
or third-party hosted agents need access, replace the shared agent token with OAuth
resource-server validation through Authentik and issue scoped client credentials.

The internal API bearer token has been rotated, compose credentials have been moved
to permission-restricted `.env` files, and the old `agentmemory:3111` service is no
longer publicly proxied or published on a host port. Reissue externally managed
GitHub, Cloudflare, and enrichment-provider credentials separately if they were
previously exposed in plaintext configuration.

## Deployment

Before starting any worker stack, copy the matching `.env.example` file to `.env`
in that service directory and fill in the tokens for your environment. The live
`.env` files are ignored by git so this repository stays safe to share.

The dashboard and gateway are deployed from:

```bash
cd /home/skynet/opt/stacks/memory-hub/agent-gateway
docker compose up -d --build
```

The deployed Caddy routes are:

```caddyfile
agentmemory.{$DOMAIN} {
    handle /mcp* {
        reverse_proxy memory-agent-gateway:3112
    }
    handle_path /api/* {
        reverse_proxy memory-agent-gateway:3112
    }
    handle /outpost.goauthentik.io/* {
        reverse_proxy authentik-server-1:9000
    }
    handle {
        import auth_strict
        reverse_proxy memory-dashboard:3000
    }
}
```

Configure an MCP client with `https://agentmemory.stevengerner.com/mcp` and an
`Authorization: Bearer <MEMORY_GATEWAY_TOKEN>` header. Include the externally used
hostname in `MCP_ALLOWED_HOSTS`; the MCP transport keeps DNS-rebinding protection
enabled and rejects unknown `Host` headers.

## CLI

`memorex-cli` is a dependency-free Node.js client ready for local packaging. Select an
available npm package name before publication:

```bash
cd /home/skynet/opt/stacks/memory-hub/memorex-cli
npm pack
export MEMOREX_URL=https://memory.example.com
export MEMOREX_TOKEN=replace-with-agent-gateway-token
memorex recall "recent architecture decisions" --category code
```

Run gateway tests in a Python environment with development dependencies installed:

```bash
cd /home/skynet/opt/stacks/memory-hub/agent-gateway
python3 -m pip install -r requirements-dev.txt
pytest -q
```

## References

- agentmemory lifecycle and MCP concepts: https://github.com/rohitg00/agentmemory
- Official MCP Python SDK Streamable HTTP and auth documentation:
  https://github.com/modelcontextprotocol/python-sdk
