# Memory Hub

Memory Hub is the full memory feature stack for personal and coding agents. It includes the backend, database, local embedding path, enrichment workers, ingestion workers, gateway, dashboard, and CLI in one repository.

The repo is designed to support two real deployment modes:

1. Self-host everything locally.
2. Attach the workers and gateway to backend services that already exist elsewhere.

It does **not** hardcode a domain. Set your own public origin if you put a reverse proxy in front of it.

## What is included

| Component | Purpose | Path |
| --- | --- | --- |
| `memorex-api` | Memorex backend API, vector search, migrations, backup staging | `memorex-api/` |
| `agent-gateway` | Agent-facing REST and Streamable HTTP MCP gateway | `agent-gateway/` |
| `dashboard` | Svelte 5 / Skeleton operator UI | `dashboard/` |
| `docs-worker` | Documents ingestion from mounted source trees | `docs-worker/` |
| `email-worker` | IMAP ingestion and attachment extraction | `email-worker/` |
| `obsidian-worker` | Obsidian vault synchronization | `obsidian-worker/` |
| `github-worker` | GitHub ingestion | `github-worker/` |
| `enricher-worker` | Remote summarization + local re-embedding | `enricher-worker/` |
| `memorex-cli` | Small CLI wrapper around the gateway | `memorex-cli/` |

## What is not included

These are treated as edge infrastructure, not core memory logic:

- Caddy or any other reverse proxy
- Authentik or any other SSO provider
- Cloudflare DDNS

You can front the dashboard and gateway with any edge stack you already run. The repo exposes the services on ports so that wiring is straightforward.

## Opinionated assumptions

This stack is intentionally opinionated.

1. The backend is the source of truth

   Memorex owns the database, lifecycle state, and vector search. The gateway and dashboard are thin control layers over it.

2. Embeddings stay local

   The backend generates embeddings through Ollama. Enrichment uses a remote LLM for metadata and summaries, then writes back through the backend so the local embedding is refreshed.

3. Secrets are explicit and known

   The dashboard only exposes the secret keys the stack actually uses. There is no arbitrary secret editor.

4. Runtime state is file-backed

   Worker settings, state, secrets, statuses, and backups live under a shared host directory. That keeps the system inspectable and easy to back up.

5. Ingestion workers are independent

   Documents, email, Obsidian, GitHub, and enrichment all run as separate workers. They can be pointed at an external backend or at the local backend in this repo.

6. The public hostname is configurable

   The repo never assumes a fixed production hostname. Set your own origin if you want one.

7. Existing services can be reused

   If you already have a Memorex backend elsewhere, leave the local backend profile off and point `MEMORY_BACKEND_URL` at it. The local backend profile in this repo owns its own Postgres and Ollama pair.

## Technical requirements

- Docker Engine with Compose v2
- Node 22 for the dashboard build
- Python 3.11 or 3.12 inside the worker and backend images
- A writable runtime data directory
- A writable ingest directory for documents and Obsidian

Recommended host directories are configured through environment variables:

- `MEMORY_DATA_DIR` for settings, worker state, backups, and persistent backend volumes
- `MEMORY_INGEST_DIR` for document source mounts
- `MEMORY_OBSIDIAN_DIR` for the Obsidian vault source

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

## Deploy

The default target brings up the full local stack:

```bash
make up
```

By default this enables:

- local Postgres
- local Ollama
- local Memorex backend
- all workers
- gateway
- dashboard

If you already have a Memorex backend elsewhere, disable the local backend profile and point the repo at it:

```bash
LOCAL_BACKEND=0 LOCAL_DB=0 LOCAL_OLLAMA=0 make up
```

In attach mode, set `MEMORY_BACKEND_URL` to the backend you already run.

## Compose model

The root `compose.yml` is the canonical deployment file.

Profiles:

- `local-db` starts Postgres
- `local-ollama` starts Ollama
- `local-backend` starts the Memorex API, migration worker, and backup stager

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

The default settings templates in `defaults/` are copied into this tree by `make init`.

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

The gateway also supports MCP host/origin allowlists for browser-based clients.

## Backup

The included backup stager captures:

- a PostgreSQL dump
- a snapshot of the settings directory
- a manifest JSON with filenames and timestamps

The backup output lands under `MEMORY_DATA_DIR/backups`.
It runs on a daily cadence, keeps only the newest complete backup for each day, and prunes to a 7-day retention window by default.

## Restore

Repo source plus Kopia backups are enough to restore the core service state if the backup repository is still reachable and the secrets/settings snapshot is intact.

That is not the whole disaster-recovery story yet. You still need:

- the backup repository itself, stored off the failed host
- the live `.env` values or an equivalent secrets restore path
- any reverse-proxy, SSO, DNS, or DDNS configuration you used outside this repo
- any local source trees under `MEMORY_INGEST_DIR` or `MEMORY_OBSIDIAN_DIR` if those are not re-created from remote systems
- any worker state files you want to preserve for a clean resume, especially IMAP cursors and file state

If your sources are remote, like Gmail, GitHub, or Google Drive, the repo plus the backups are usually enough to get the service back on its feet and let the workers resync. If your documents or Obsidian vault are only local, those trees need to be part of your backup plan as well.

## Where to look first

- `compose.yml` for the overall stack shape
- `defaults/` for bootstrap JSON
- `memorex-api/main.py` for the backend and vector logic
- `dashboard/src/routes/settings/+page.svelte` for operator controls
- `agent-gateway/main.py` for the agent API and MCP layer

## CLI

`memorex-cli` is a thin wrapper around the gateway REST API:

```bash
export MEMOREX_URL=https://your-memory-domain.example
export MEMOREX_TOKEN=replace-with-agent-gateway-token

memorex recall "What decisions did I make about authentication?"
memorex store "Prefer migration scripts to manual schema edits." --kind preference --retention durable
```

## Validation

Useful checks:

```bash
make ps
make logs
```

The repo is intended to be committed and shared as source. It should not contain live `.env` files or runtime data.
