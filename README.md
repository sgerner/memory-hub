# Memory Hub

Memory Hub is the full memory feature stack for personal and coding agents. It includes the backend, queue-based embedding worker, enrichment worker, ingestion workers, gateway, dashboard, CLI, and the local data layout needed to run and restore the system from one repository.

The repo supports two deployment modes:

1. Run everything locally.
2. Attach the gateway, dashboard, and workers to backend services that already exist elsewhere.

It does **not** hardcode a domain. Set your own public origin if you put a reverse proxy in front of it.

## What is included

| Component | Purpose | Path |
| --- | --- | --- |
| `memory-db` | Optional local Postgres database | `compose.yml` |
| `ollama` | Optional local embedding runtime | `compose.yml` |
| `agentmemory` | Memorex backend API, vector search, queue state, health endpoint, and backup staging hooks | `memorex-api/` |
| `embedding-worker` | Steady-state DB-backed embedding consumer and backfill worker | `compose.yml`, `memorex-api/migrate_vectors.py` |
| `backup-stager` | Daily PostgreSQL dump and settings snapshot writer | `compose.yml`, `memorex-api/backup.sh` |
| `memory-agent-gateway` | Agent-facing REST API and Streamable HTTP MCP gateway | `agent-gateway/` |
| `memory-dashboard` | Svelte 5 / Skeleton operator UI | `dashboard/` |
| `docs-worker` | Documents ingestion from mounted source trees | `docs-worker/` |
| `email-worker` | IMAP ingestion and attachment extraction | `email-worker/` |
| `obsidian-worker` | Obsidian vault synchronization | `obsidian-worker/` |
| `github-worker` | GitHub ingestion | `github-worker/` |
| `enricher-worker` | Remote summarization and metadata enrichment | `enricher-worker/` |
| `memorex-cli` | Thin CLI wrapper around the gateway | `memorex-cli/` |
| `plugins/` | Codex, Antigravity, and OpenCode plugin bundles | `plugins/`, `.opencode/` |

## What is not included

These are treated as edge infrastructure, not core memory logic:

- Caddy or any other reverse proxy
- Authentik or any other SSO provider
- Cloudflare DDNS or other DNS automation
- A managed secret store

You can front the dashboard and gateway with any edge stack you already run. The repo exposes the services on ports so that wiring is straightforward.

## Opinionated assumptions

This stack is intentionally opinionated.

1. The backend is the source of truth

   Memorex owns the database, lifecycle state, queue state, and vector search. The gateway and dashboard are thin control layers over it.

2. Embedding is queue-driven

   New records are written first and marked for embedding later. The embedding worker drains the database queue in the background so ingestion does not block on Ollama.

3. Embeddings stay local by default

   Ollama is the default embedding runtime. If you temporarily offload embeddings to a remote provider, treat that as an explicit runtime choice and do not change the vector schema unless you are ready to reindex.

4. Enrichment is separate from embedding

   Enrichment uses a remote LLM for summaries, metadata, and canonical text, then saves the result back through the backend so the final record can be re-embedded.

5. Secrets are explicit and known

   The dashboard only exposes the secret keys the stack actually uses. There is no arbitrary secret editor.

6. Runtime state is file-backed

   Worker settings, worker status, secrets, source selections, and backup outputs live under a shared host directory. That keeps the system inspectable and easy to back up.

7. Ingestion workers are independent

   Documents, email, Obsidian, GitHub, enrichment, and embedding all run as separate workers. They can be pointed at an external backend or at the local backend in this repo.

8. The public hostname is configurable

   The repo never assumes a fixed production hostname. Set your own origin if you want one.

9. Existing services can be reused

   If you already have Postgres, Ollama, or a Memorex backend elsewhere, leave the local backend profiles off and point the repo at those services instead of creating duplicates.

## Technical requirements

- Docker Engine with Compose v2
- Node 22 for the dashboard build
- Python 3.11 or 3.12 inside the worker and backend images
- A writable runtime data directory
- A writable ingest directory for documents and Obsidian

The host does not need Python or Node installed unless you want to run local tooling outside Docker.

Recommended host directories are configured through environment variables:

- `MEMORY_DATA_DIR` for settings, worker state, backups, and persistent backend volumes
- `MEMORY_INGEST_DIR` for document source mounts
- `MEMORY_OBSIDIAN_DIR` for the Obsidian vault source

## Configuration reference

The stack is driven by `.env`. The most important values are:

| Variable | Purpose |
| --- | --- |
| `MEMORY_DATA_DIR` | Root of runtime data: settings, status files, backups, database volume, and Ollama volume |
| `MEMORY_NETWORK_NAME` | Docker network used by Memory Hub services; defaults to `memory-internal` and is created by `make init` |
| `MEMORY_INGEST_DIR` | Root of document source mounts such as `gdrive/` and `docs/` |
| `MEMORY_OBSIDIAN_DIR` | Root of the Obsidian vault source |
| `MEMORY_PUBLIC_ORIGIN` | Optional public URL for the dashboard or gateway behind a reverse proxy |
| `AGENTMEMORY_TOKEN` | Backend bearer token used by workers and the gateway |
| `MEMORY_BACKEND_URL` | Backend URL used by the gateway and dashboard |
| `MEMORY_BACKEND_TOKEN` | Bearer token used by the gateway when calling the backend |
| `MEMORY_GATEWAY_TOKEN` | Bearer token used by agents and the dashboard when calling the gateway |
| `MEMORY_ADMIN_TOKEN` | Admin token used for privileged gateway operations |
| `POSTGRES_*` | Database name, user, password, host, and port for the backend |
| `OLLAMA_HOST` | Ollama endpoint used for local embeddings |
| `DEFAULT_MODEL` | Default local embedding model |
| `EMBEDDING_PROVIDER` | Embedding provider selector for the backend and embedding worker |
| `GEMINI_API_KEY` | Optional Gemini embedding key for temporary offload or migration work |
| `GEMINI_EMBED_MODEL` | Gemini embedding model name |
| `GEMINI_OUTPUT_DIMENSIONALITY` | Gemini output size, kept aligned with the vector schema when used |
| `LLM_BASE_URL` | Primary enrichment provider base URL |
| `LLM_FREE_BASE_URL` | Fallback enrichment provider base URL |
| `LLM_MODEL` | Primary enrichment model |
| `LLM_API_KEY` | Primary enrichment token |
| `LLM_FALLBACK_API_KEY` | Fallback enrichment token |
| `BACKUP_INTERVAL_SECONDS` | Backup cadence, daily by default |
| `BACKUP_RETENTION_DAYS` | How many days of backups to keep, 7 by default |

The default templates in `defaults/` are copied into the runtime tree by `make init`.

## Bootstrap

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
```

Then initialize the runtime tree:

```bash
make init
```

That creates the expected directory layout and writes default JSON settings if they are missing.

If you want an LLM to do the setup or restore work, start with [LLM_SETUP_PROMPT.md](./LLM_SETUP_PROMPT.md).

## Agent plugins

Install the plugin bundles for any machine that already has Codex, Antigravity, or OpenCode installed:

```bash
curl -fsSL https://raw.githubusercontent.com/sgerner/memory-hub/main/scripts/install-agent-plugins.sh | bash
```

That command clones the repo, stages the plugin bundles in a local data directory, and registers whichever CLIs it finds on the machine.

## Deploy

The default target brings up the full local stack:

```bash
make up
```

By default this enables:

- local Postgres
- local Ollama
- local Memorex backend
- embedding worker
- backup stager
- all ingestion workers
- gateway
- dashboard

If you already have Memorex, Postgres, or Ollama running elsewhere, disable the local services and point the repo at the existing backend:

```bash
LOCAL_BACKEND=0 LOCAL_DB=0 LOCAL_OLLAMA=0 make up
```

In attach mode, set `MEMORY_BACKEND_URL` to the backend you already run and make sure the gateway token matches what that backend expects.

## Compose model

The root `compose.yml` is the canonical deployment file.

Profiles:

- `local-db` starts Postgres
- `local-ollama` starts Ollama
- `local-backend` starts the Memorex API, embedding worker, and backup stager

The ingestion workers, gateway, and dashboard are always defined. They attach to either the local backend or your existing backend URL.

## Runtime data layout

The stack expects the following structure under `MEMORY_DATA_DIR`:

```text
settings/
  documents.json
  email.json
  obsidian.json
  github.json
  enrichment.json
  secrets.json
docs-worker/
email-worker/
obsidian-worker/
github-worker/
enricher-worker/
status/
backups/
postgres/
ollama/
```

The email worker also uses:

- `email-worker/accounts.json`

The status directory contains per-service snapshots such as:

- `docs-worker.json`
- `email-worker.json`
- `obsidian-worker.json`
- `github-worker.json`
- `enricher-worker.json`
- `embedding-worker.json`
- `backup.json`

## Default document sources

The default document settings ship with:

- `gdrive`
- `docs`

Those are relative source paths under `MEMORY_INGEST_DIR`.

Obsidian uses `MEMORY_OBSIDIAN_DIR` directly.

## Ports

The default exposed ports are:

- dashboard: `3000`
- gateway: `3112`
- backend: `3111`

These can be changed with environment variables if needed.

## Authentication

There are three distinct trust boundaries:

1. The dashboard talks to the gateway, not directly to the backend.
2. The gateway talks to the backend with its own bearer token.
3. The backend token never needs to reach the browser.

The gateway also supports MCP host and origin allowlists for browser-based clients.

## Backup

The included backup stager captures:

- a PostgreSQL dump
- a snapshot of the settings directory
- a manifest JSON with filenames and timestamps

The backup output lands under `MEMORY_DATA_DIR/backups`.
It runs on a daily cadence by default, keeps only the newest complete backup for each day, and prunes to a 7-day retention window.

If you use Kopia as host-level backup storage, include at least:

- `MEMORY_DATA_DIR`
- any local source subtrees under `MEMORY_INGEST_DIR` that are not recreated from remote mounts
- `/etc/docker/daemon.json`
- `/etc/fuse.conf` if you use FUSE-backed remote mounts such as rclone
- any edge configuration you keep outside the repo, such as reverse proxy or SSO files

The remote source-mount configs for `docs/` and `gdrive/` live under `MEMORY_DATA_DIR`, so the backup above already preserves the settings needed to remount them after a rebuild. The data behind those mounts, plus the Obsidian vault, are treated as external source data and are not part of this host backup.

The restore helper at [`../restore-stack.sh`](../restore-stack.sh) recreates the shared Docker networks, starts the source-mount stacks first, waits for the ingest mounts, and brings the active stacks back up in one pass.

## Restore

The repository plus the backup snapshots can restore the core memory stack if the backup repository itself is still reachable and the external inputs below are available.

What you still need outside the repo:

- the backup repository or storage target itself
- the live `.env` values or an equivalent secrets restore path
- any reverse proxy, SSO, DNS, or DDNS configuration you used outside this repo
- any local source trees under `MEMORY_INGEST_DIR` if those are not re-created from remote systems
- the Obsidian vault or its own upstream backup if you want that data restored separately
- any worker state files you want to preserve for a clean resume, especially IMAP cursors and file state

Restore order:

1. Restore the runtime data and any local source trees.
2. Restore or recreate `.env`.
3. Restore `/etc/docker/daemon.json` if you use a custom Docker daemon config.
4. Restore the PostgreSQL dump into the backend database if you are using the local backend.
5. Restore `settings/`, `status/`, and `email-worker/accounts.json`.
6. Restore or reconnect any remote source-mount services such as rclone or OneDrive, restore `/etc/fuse.conf` if you use FUSE-backed mounts, then run the restore helper to recreate the Docker networks and bring the stack up.
7. Confirm the backend, gateway, dashboard, and workers are healthy.

If your sources are remote, like Gmail, GitHub, or Google Drive, the repo plus the backups are usually enough to get the service back on its feet and let the workers resync. If your documents or Obsidian vault are only local, those trees need to be part of your backup plan as well.

## Where to look first

- `compose.yml` for the overall stack shape
- `defaults/` for bootstrap JSON
- `memorex-api/main.py` for the backend, embedding queue, and vector logic
- `dashboard/src/routes/settings/+page.svelte` for operator controls
- `dashboard/src/routes/+layout.svelte` for runtime observability
- `agent-gateway/main.py` for the agent API and MCP layer

## CLI

`memorex-cli` is a thin wrapper around the gateway REST API:

```bash
export MEMOREX_URL=https://your-memory-domain.example
export MEMOREX_TOKEN=replace-with-agent-gateway-token

memorex recall "What decisions did I make about authentication?"
memorex store "Prefer migration scripts to manual schema edits." --kind preference --retention durable
memorex list agent --limit 10 --inactive
memorex queue
memorex overview --limit 5
```

The Streamable HTTP MCP gateway exposes the same agent workflow through tools:
`memory_store`, `memory_recall`, `memory_list`, `memory_patch`, `memory_supersede`,
`memory_archive`, `memory_forget`, `memory_overview`, and `memory_queue_status`.

## Validation

Useful checks:

```bash
make ps
make logs
```

You can also verify the running services directly:

- `GET /health` on the backend at port `3111`
- `GET /health` on the gateway at port `3112`
- `GET /queue-status` through the gateway with the gateway token
- a successful `npm run check` in `dashboard/`

## Sharing this repo

The repo is intended to be committed and shared as source. It should not contain live `.env` files or runtime data.
