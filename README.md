# Personal Memory Hub

Personal Memory Hub is the stack I use to ingest, enrich, browse, and modify long-lived personal memory for agents. It is built around an existing Memorex Postgres/vector backend and adds:

- source ingestion workers for email, documents, Obsidian, and GitHub
- a remote enrichment worker that summarizes and augments records
- a gateway that exposes agent-facing REST and MCP endpoints
- a Svelte 5 dashboard for operator control
- a small CLI for local and agent use

This repository is intended to be shareable on GitHub. It contains source, compose files, and example environment files. It does not contain live secrets or runtime data.

## What is in this stack

| Component | Purpose | Main path |
| --- | --- | --- |
| `agent-gateway` | Agent-facing REST and Streamable HTTP MCP server | `agent-gateway/` |
| `dashboard` | SvelteKit operator UI | `dashboard/` |
| `docs-worker` | Filesystem document ingestion | `docs-worker/` |
| `email-worker` | IMAP ingestion and attachment extraction | `email-worker/` |
| `obsidian-worker` | Obsidian vault ingestion | `obsidian-worker/` |
| `github-worker` | GitHub ingestion | `github-worker/` |
| `enricher-worker` | Summary/enrichment worker that calls remote LLMs and re-saves into Memorex | `enricher-worker/` |
| `memorex-cli` | Dependency-free Node CLI for the gateway | `memorex-cli/` |

The workers feed the existing Memorex backend at `agentmemory:3111`. The gateway and dashboard are separate layers on top of that backend.

## Opinionated assumptions

This stack makes a few deliberate assumptions. They are important because they shape the design and the deployment model.

1. Single operator, trusted network

   This is built for one operator controlling personal and coding agents. It is not a multi-tenant SaaS and it does not try to be one. Shared tokens are acceptable inside the trusted internal network, but not for broad public exposure.

2. Memorex backend is the source of truth

   The existing backend service is the system of record for records, vectors, and lifecycle state. The gateway and dashboard do not replace the database or embedder. They sit on top of it.

3. Browsers never receive backend credentials

   The dashboard server talks to the gateway. The browser only talks to the dashboard. The browser never needs the backend token or the gateway token.

4. Source workers are separate from agent operations

   Ingestion workers are intentionally not folded into the gateway yet. They keep running as simple polling or sync processes that write to the backend.

5. Embedding and enrichment are separate

   Embeddings are generated locally by the Memorex backend through Ollama. Enrichment uses a remote LLM and then updates the record, which causes a fresh local embedding to be generated.

6. Configuration is file-backed

   Worker settings, secrets, status snapshots, and backups are stored as JSON files under the shared app data tree. That keeps the system simple and easy to inspect.

7. Known secrets only

   The dashboard only exposes the secrets we know the stack needs. There is no arbitrary secret editor. That is deliberate.

8. Runtime data stays out of git

   Live `.env` files, caches, build output, and generated state files are not committed. The repo only carries examples and source.

9. Document sources are mounted under the ingest tree

   The docs worker scans subdirectories under `/data/ingest`. The current configured source paths are `gdrive` and `docs`. In this stack, `docs` is the mounted tree that corresponds to the OneDrive-backed document source.

## Technical requirements

You need the following before this stack will behave correctly:

- Docker Engine with Compose v2
- a working internal Docker network named `memory-internal`
- a proxy network named `proxy`
- the Memorex backend reachable as `http://agentmemory:3111` on the internal network
- Ollama reachable from the backend for local embeddings
- Caddy and Authentik already wired for `agentmemory.stevengerner.com`
- host mounts for the runtime data tree and ingest tree
- Node 22 for the dashboard build image
- Python 3.11 or 3.12 inside the worker containers

Host paths used by this stack:

- `/home/skynet/opt/appdata/memory-hub` for settings, status, worker state, and backups
- `/home/skynet/data/ingest` for mounted document sources

## Repository layout

```text
memory-hub/
  agent-gateway/      Gateway service, tests, and Compose definition
  dashboard/          SvelteKit dashboard
  docs-worker/        Document worker
  email-worker/       Email worker
  enricher-worker/    Enrichment worker
  github-worker/      GitHub worker
  obsidian-worker/    Obsidian worker
  memorex-cli/        CLI client
```

## Runtime data layout

The stack reads and writes a shared data tree at `/home/skynet/opt/appdata/memory-hub`. Inside the running containers that is mounted at `/app/data/memory-hub`.

Important files and folders:

| Path | Purpose |
| --- | --- |
| `settings/documents.json` | Documents worker settings, including `source_paths` |
| `settings/email.json` | Email worker settings |
| `settings/obsidian.json` | Obsidian worker settings |
| `settings/github.json` | GitHub worker settings |
| `settings/enrichment.json` | Enrichment worker settings |
| `settings/secrets.json` | Known secret values used by workers and the dashboard |
| `status/*.json` | Live worker and backup status snapshots |
| `backups/` | Kopia-side archives and manifest |
| `docs-worker/state.json` | Documents worker file state |
| `email-worker/state.json` | Email worker cursor/state |
| `email-worker/accounts.json` | IMAP account list |
| `obsidian-worker/state.json` | Obsidian worker state |
| `github-worker/state.json` | GitHub worker state |
| `enricher-worker/` | Enrichment worker local state |

Do not commit the live contents of these files. They are machine-specific.

## Environment files

Every service directory that needs secrets has an `.env.example` file. Copy it to `.env` locally and fill in your values. The live `.env` files are ignored by git.

| File | Variables |
| --- | --- |
| `agent-gateway/.env.example` | `MEMORY_BACKEND_TOKEN`, `MEMORY_GATEWAY_TOKEN`, `MEMORY_ADMIN_TOKEN`, `MCP_ALLOWED_HOSTS`, `MCP_ALLOWED_ORIGINS` |
| `docs-worker/.env.example` | `AGENTMEMORY_TOKEN` |
| `email-worker/.env.example` | `AGENTMEMORY_TOKEN` |
| `enricher-worker/.env.example` | `AGENTMEMORY_TOKEN`, `LLM_API_KEY` |
| `github-worker/.env.example` | `AGENTMEMORY_TOKEN`, `GITHUB_TOKEN` |
| `obsidian-worker/.env.example` | `AGENTMEMORY_TOKEN` |

Notes:

- `MEMORY_BACKEND_TOKEN` is the token the gateway uses to authenticate to the Memorex backend.
- `MEMORY_GATEWAY_TOKEN` is the token used by the dashboard, CLI, and MCP clients against the gateway.
- `MEMORY_ADMIN_TOKEN` is only for irreversible deletions.
- `LLM_API_KEY` is the remote provider token used by enrichment.
- `GITHUB_TOKEN` is the GitHub access token used by GitHub ingestion.

## Services and data flow

### Ingestion workers

The workers are intentionally simple:

- `docs-worker` scans mounted document sources and pushes records into the backend.
- `email-worker` polls IMAP, extracts message content and attachments, and stores records.
- `obsidian-worker` walks the vault tree and stores notes.
- `github-worker` syncs repository and discussion data.

These workers do not talk to agents directly. They write to the backend and keep their own state in JSON files.

### Enrichment worker

The enrichment worker:

1. reads pending items from the backend
2. calls the remote LLM for summary/enrichment
3. updates the record back through the backend
4. causes the backend to regenerate the local embedding with Ollama

The remote LLM is not the vector source of record. It is only used for enrichment text and structured metadata.

### Gateway

The gateway exposes the memory stack to agents. It provides:

- REST recall and browse endpoints
- memory store/update/archive/forget operations
- a Streamable HTTP MCP endpoint
- separate normal and admin auth tokens

The dashboard uses the gateway, not the backend, so browsers never need backend credentials.

### Dashboard

The dashboard is a SvelteKit app built with Skeleton UI. It is meant to be served behind Authentik and accessed by the operator. It provides:

- overview and runtime observability
- memory recall and memory store
- lifecycle management
- worker tuning
- known secret management
- email account management
- Obsidian vault configuration
- document source management
- backup manifest visibility

## Current source assumptions

The current document source paths are:

- `gdrive`
- `docs`

Those paths map to directories under `/home/skynet/data/ingest`. The docs worker mounts the ingest root and reads `settings/documents.json` as its configuration file. If you change the source paths, update that JSON file or use the dashboard.

## Authentication model

The stack uses three layers of auth:

1. Authentik protects the dashboard route.
2. The gateway requires bearer tokens for its REST and MCP endpoints.
3. The backend token stays inside the internal network and is not sent to browsers or MCP clients.

This is the right tradeoff for a personal stack. It is not meant to be exposed to arbitrary third parties.

## Dashboard settings model

The dashboard settings page is intentionally conservative:

- only known secrets are exposed
- worker settings are grouped by task
- email accounts live with the email worker controls
- GitHub and document source settings live under source/integration controls
- Obsidian has its own section because its config shape is different

The stack avoids a free-form secret editor on purpose. If a secret is not explicitly known to the stack, it should not show up in the UI.

## Backup model

Kopia is the backup mechanism used for this stack. The backup job records a manifest under `backups/manifest.json` and stores both the database backup and settings backup artifacts in the app data tree.

What gets backed up:

- the database dump
- the shared settings tree
- the runtime metadata required to understand the backup set

## Deployment

### Dashboard and gateway

```bash
cd /home/skynet/opt/stacks/memory-hub/agent-gateway
docker compose up -d --build
```

This builds and starts:

- `memory-agent-gateway`
- `memory-dashboard`

### Individual workers

Each worker directory has its own `compose.yml`. Start them the same way from that directory:

```bash
cd /home/skynet/opt/stacks/memory-hub/docs-worker
docker compose up -d --build
```

Repeat for `email-worker`, `obsidian-worker`, `github-worker`, and `enricher-worker`.

## Local validation

Useful checks for day-to-day work:

```bash
cd /home/skynet/opt/stacks/memory-hub/dashboard
npx svelte-check --tsconfig ./tsconfig.json
npm run build
```

```bash
cd /home/skynet/opt/stacks/memory-hub/agent-gateway
python3 -m pip install -r requirements-dev.txt
pytest -q
```

## CLI

`memorex-cli` is a small Node.js wrapper around the gateway.

Example:

```bash
export MEMOREX_URL=https://agentmemory.stevengerner.com
export MEMOREX_TOKEN=replace-with-agent-gateway-token

memorex recall "What database migration decisions were made?"
memorex store "Prefer migration scripts to manual ALTER TABLE changes." \
  --kind preference --retention durable --agent codex
```

Use `npm pack` before publishing to verify the package contents. Pick an available npm package name before making it public.

## Operational notes

- The dashboard is intentionally simple and operator-focused, not a feature-heavy admin suite.
- Runtime state will change under `opt/appdata/memory-hub`; that is expected.
- If document source counts show zero, check `settings/documents.json` first.
- If enrichment is rate limited, the worker will defer rather than hammer the provider.
- The backend embedding dimension is treated as a stable migration boundary. Do not change it casually.

## Security notes

- Never commit live `.env` files.
- Never commit live tokens from `settings/secrets.json`.
- If you expose this repo publicly, rotate any credentials that existed on disk before the repo was created.
- Keep the gateway and dashboard behind the existing proxy and auth layers.

## Notes on the existing stack

This repository is built on top of a working deployment. It assumes the following services already exist in the larger homelab:

- Caddy
- Authentik
- Cloudflare DDNS
- Ollama
- the Memorex backend/database stack

The Memory Hub repository does not replace those services. It integrates with them.

## References

- `agentmemory` lifecycle ideas: https://github.com/rohitg00/agentmemory
- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- Skeleton UI: https://www.skeleton.dev/
