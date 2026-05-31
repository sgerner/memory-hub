# `memorex`

Command-line client for the Personal Memory Hub gateway REST API. Point `MEMOREX_URL`
at the gateway origin or public reverse-proxy origin, not directly at the backend.
Node.js 18 or newer is required; there are no runtime dependencies.

```bash
export MEMOREX_URL=https://your-memory-domain.example
export MEMOREX_TOKEN=replace-with-agent-gateway-token

memorex recall "What database migration decisions were made?"
memorex store "Prefer migration scripts to manual ALTER TABLE changes." \
  --kind preference --retention durable --agent codex
```

Use `npm pack` to test the distributable package, then change the package scope/name to an
available npm name before publishing.
