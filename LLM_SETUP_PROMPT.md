# Memory Hub setup prompt

Use this prompt with an LLM that is being asked to set up, restore, validate, or extend this repository on a server.

```text
You are setting up Memory Hub, a personal memory stack for agents.

Read these files first:
- README.md
- .env.example
- compose.yml
- memorex-api/compose.yml
- defaults/
- dashboard/src/routes/settings/+page.server.ts
- dashboard/src/routes/+layout.svelte
- agent-gateway/main.py

Goals:
1. Install, restore, or validate the full memory feature stack.
2. Do not hardcode a domain or assume a specific hostname.
3. Reuse existing Postgres, Ollama, or Memorex services if they already exist.
4. Keep secrets out of git.
5. Preserve existing data and source trees.

Core stack components:
- Memorex backend API
- Postgres
- Ollama
- embedding worker
- ingestion workers for documents, email, Obsidian, and GitHub
- enrichment worker
- gateway
- dashboard
- CLI

Operational assumptions:
- The backend is the source of truth.
- The embedding worker drains a database-backed queue. New rows are written first, then embedded asynchronously.
- Embeddings stay local through Ollama by default. Do not change the vector schema unless the user explicitly asks.
- Enrichment uses a remote LLM and then re-saves through the backend so the final text can be re-embedded.
- The dashboard talks to the gateway, not directly to the backend.
- Runtime settings, secrets, worker state, and backups are file-backed under MEMORY_DATA_DIR.

Deployment rules:
- If the user wants a full local stack, create a .env from .env.example, run `make init`, then `make up`.
- If Postgres, Ollama, or Memorex already exist, do not recreate them unless the user explicitly wants local copies.
- For attach mode, set `LOCAL_BACKEND=0 LOCAL_DB=0 LOCAL_OLLAMA=0` and point `MEMORY_BACKEND_URL` at the existing backend.
- In attach mode, set `MEMORY_BACKEND_TOKEN` to the backend's bearer token and keep `MEMORY_GATEWAY_TOKEN` as the agent-facing token used by the dashboard and CLI.
- Never overwrite existing settings, worker state, or source trees unless the user explicitly asks.
- Do not change embedding dimensions or vector schema unless the user asks.
- If a reverse proxy or SSO already exists, keep it outside this repo and wire it in with environment variables.

Restore rules:
- Restore the runtime data tree before starting workers.
- Restore the PostgreSQL dump into the backend database if you are using the local backend.
- Restore `settings/`, `status/`, and `email-worker/accounts.json` if they exist.
- Restore `secrets.json` and any other worker-specific settings files before starting the workers.
- Restore any local document or Obsidian source trees before starting the workers.
- If external sources are remote, reconnect credentials and let the workers resync.
- If the backup repository is Kopia or another host-level backup target, make sure it includes MEMORY_DATA_DIR, MEMORY_INGEST_DIR, and MEMORY_OBSIDIAN_DIR.

Validation:
- Run `docker compose config` or `make up` and make sure the stack resolves cleanly.
- Verify `GET /health` on the backend at port 3111.
- Verify `GET /health` on the gateway at port 3112.
- Verify `GET /queue-status` through the gateway with the gateway token.
- Verify worker status snapshots in MEMORY_DATA_DIR/status.
- Verify the dashboard build with `npm run check` in dashboard/.
- Confirm that no live secrets were committed.

Operational checklist:
- If setting up from scratch, run `cp .env.example .env`, edit it, then `make init`.
- If you only need the attach mode, do not start local Postgres or Ollama.
- If the dashboard is deployed behind a reverse proxy, use MEMORY_PUBLIC_ORIGIN instead of hardcoding a domain.
- If the user asks for a future reindex or bulk embedding run, use the embedding worker rather than a one-off migration script.
```
