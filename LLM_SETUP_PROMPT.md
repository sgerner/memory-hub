# Memory Hub setup prompt

Use this prompt with an LLM that is being asked to set up, restore, or validate this repository on a server.

```text
You are setting up Memory Hub, a personal memory stack for agents.

Read these files first:
- README.md
- .env.example
- compose.yml
- memorex-api/compose.yml
- defaults/

Goals:
1. Install or restore the full memory feature stack.
2. Do not hardcode a domain or assume a specific hostname.
3. Reuse existing Postgres, Ollama, or Memorex services if they already exist, unless the user explicitly wants local copies.
4. Keep secrets out of git.
5. Preserve existing data if present.

Core stack components:
- Memorex backend API
- Postgres
- Ollama
- ingestion workers for documents, email, Obsidian, and GitHub
- enrichment worker
- gateway
- dashboard
- CLI

Operational assumptions:
- The backend is the source of truth.
- Embeddings stay local through Ollama.
- Enrichment uses a remote LLM and then re-saves through the backend.
- The dashboard talks to the gateway, not directly to the backend.

Deployment rules:
- If the user wants a full local stack, create a .env from .env.example, run `make init`, then `make up`.
- If Postgres/Ollama/Memorex already exist, disable the local backend profiles and point the repo at the existing services.
- Never overwrite existing settings or worker state unless the user explicitly asks.
- Do not change embedding dimensions or vector schema unless the user asks.

Restore rules:
- If restoring from backup, restore the copied settings directory first.
- Restore the PostgreSQL dump into the backend database.
- Restore any backed-up worker state and email account files if they exist.
- If local document or Obsidian source trees are part of the backup set, restore them before starting the workers.
- If external sources are remote, reconnect credentials and let the workers resync.

Edge services:
- Caddy, Authentik, DNS, and DDNS are external integration points, not required repo-managed services.
- If the user wants a public origin, wire it in through environment variables and reverse-proxy configuration outside this repo.

Validation:
- Check docker compose config.
- Verify the backend health endpoint.
- Verify worker status snapshots.
- Verify the dashboard build.
- Confirm that no live secrets were committed.
```
