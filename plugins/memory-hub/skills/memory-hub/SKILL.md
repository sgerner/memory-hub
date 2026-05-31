---
name: memory-hub
description: Use Memory Hub for recall, storage, lifecycle updates, and queue awareness.
---

# Memory Hub

Use the Memory Hub tools directly when the task benefits from prior context or durable state.

## Tool usage

- Call `memory_recall` before answering when the task may depend on past decisions, preferences, or project context.
- Call `memory_store` after a fact, preference, decision, or procedure is confirmed and should persist.
- Call `memory_list` when you need to inspect recent records or confirm provenance.
- Call `memory_patch` to correct content or add non-lifecycle metadata.
- Call `memory_supersede` when a memory should be replaced by a newer or corrected one.
- Call `memory_archive` to hide stale information from normal recall without deleting history.
- Call `memory_forget` for soft deletion.
- Call `memory_overview` or `memory_queue_status` when you need operational context.
- Avoid storing secrets, temporary scratch work, or speculative notes.

## Behavior

- Prefer concise memory contents.
- Use explicit source metadata when it helps future auditing.
- Favor archive or supersede over delete unless a human explicitly asks for purge.
- Keep recall and storage scoped to the relevant categories instead of searching everything by default.
