# Memory Hub

Use Memory Hub to keep agents consistent across turns.

## When to use it

- Call `memory_recall` before answering when prior decisions, preferences, or project context may matter.
- Call `memory_get` for a specific recalled `category` and `id` only when the compact recall snippet is relevant but insufficient.
- Call `memory_store` after a fact, preference, decision, or procedure is confirmed and should persist.
- Use `memory_patch`, `memory_archive`, `memory_forget`, and `memory_supersede` for lifecycle updates.
- Use `memory_overview` and `memory_queue_status` when backlog health affects the task.

## Behavior

- Prefer durable facts over re-deriving the same context repeatedly.
- Treat automatic recall as a token-efficient index, not a full transcript; fetch details selectively.
- Keep stored memories short, specific, and attributable.
- Avoid storing speculative content unless the user explicitly asks.
