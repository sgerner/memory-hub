<script lang="ts">
	import { fade, fly } from 'svelte/transition';

	const cliInstall = `npm install -g memory-hub-cli
export MEMOREX_URL=https://your-memory-domain.example
export MEMOREX_TOKEN=your_gateway_token

memorex recall "What decisions did I make about authentication?"
memorex store "Prefer migration scripts to manual schema edits." --kind preference --retention durable
memorex list agent --limit 10 --inactive
memorex queue`;

	const pluginInstall = `curl -fsSL https://raw.githubusercontent.com/sgerner/memory-hub/main/scripts/install-agent-plugins.sh | bash`;

	const mcpRemote = `{
  "mcpServers": {
    "memory-hub": {
      "url": "https://your-memory-domain.example/mcp",
      "headers": {
        "Authorization": "Bearer your_gateway_token"
      }
    }
  }
}`;

	const agentSnippet = `# Memory Hub

Before answering, search Memory Hub for relevant context.
Store durable preferences, decisions, procedures, and project facts after they are confirmed.
Use semantic recall first, then list or inspect records when you need provenance.
Prefer archive/forget over deletion unless a human explicitly requests purging.

Available tools:
- memory_recall
- memory_store
- memory_list
- memory_patch
- memory_supersede
- memory_archive
- memory_forget
- memory_overview
- memory_queue_status`;
</script>

<svelte:head>
	<title>Access — Memory Hub</title>
</svelte:head>

<main class="shell pb-24 pt-8 md:pt-12 max-w-5xl">
	<div class="mb-8 md:mb-10 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
		<div>
			<p class="section-label mb-1">Access</p>
			<h1 class="text-3xl md:text-4xl font-bold text-surface-50">CLI, MCP, and agent instructions</h1>
			<p class="mt-3 max-w-2xl text-sm md:text-base text-surface-400">
				Use this page as the quick start for agents and operators that need to connect to the memory hub from the terminal, from remote devices, or from an agents.md file.
			</p>
		</div>
		<a href="/settings" class="ghost-btn self-start">Open settings</a>
	</div>

	<div class="grid gap-4 lg:grid-cols-3">
		<section class="border border-white/10 bg-white/[0.03] p-6 md:p-7" transition:fade={{ duration: 160 }}>
			<div class="flex items-center justify-between gap-4 mb-5">
				<div>
					<p class="section-label">CLI</p>
					<h2 class="mt-2 text-xl font-semibold text-surface-50">Install and use `memorex`</h2>
				</div>
				<span class="status-pill active">npm package</span>
			</div>
			<p class="text-sm text-surface-400 mb-4">
				Publish the CLI once, then install it anywhere with npm. Point it at the gateway, not the backend.
			</p>
			<pre class="overflow-x-auto border border-white/10 bg-black/30 p-4 text-[0.72rem] leading-6 text-surface-200 no-scrollbar" transition:fly={{ y: 8, duration: 140 }}><code>{cliInstall}</code></pre>
		</section>

		<section class="border border-white/10 bg-white/[0.03] p-6 md:p-7" transition:fade={{ duration: 160 }}>
			<div class="flex items-center justify-between gap-4 mb-5">
				<div>
					<p class="section-label">Plugins</p>
					<h2 class="mt-2 text-xl font-semibold text-surface-50">Install agent plugins</h2>
				</div>
				<span class="status-pill active">one command</span>
			</div>
			<p class="text-sm text-surface-400 mb-4">
				Runs the supported installer for Codex, Antigravity, and OpenCode on any machine that has those CLIs installed.
			</p>
			<pre class="overflow-x-auto border border-white/10 bg-black/30 p-4 text-[0.72rem] leading-6 text-surface-200 no-scrollbar" transition:fly={{ y: 8, duration: 140 }}><code>{pluginInstall}</code></pre>
		</section>

		<section class="border border-white/10 bg-white/[0.03] p-6 md:p-7" transition:fade={{ duration: 160 }}>
			<div class="flex items-center justify-between gap-4 mb-5">
				<div>
					<p class="section-label">Remote MCP</p>
					<h2 class="mt-2 text-xl font-semibold text-surface-50">Connect from other devices</h2>
				</div>
				<span class="status-pill running">streamable http</span>
			</div>
			<ul class="space-y-3 text-sm text-surface-400">
				<li>Use the public gateway origin plus `/mcp`.</li>
				<li>Send `Authorization: Bearer <code>&lt;gateway token&gt;</code>` on every request.</li>
				<li>Expose the route through your reverse proxy and keep auth headers intact.</li>
			</ul>
			<pre class="mt-5 overflow-x-auto border border-white/10 bg-black/30 p-4 text-[0.72rem] leading-6 text-surface-200 no-scrollbar" transition:fly={{ y: 8, duration: 140 }}><code>{mcpRemote}</code></pre>
		</section>
	</div>

	<div class="grid gap-4 lg:grid-cols-2 mt-4">
		<section class="border border-white/10 bg-white/[0.03] p-6 md:p-7" transition:fade={{ duration: 160 }}>
			<div class="flex items-center justify-between gap-4 mb-5">
				<div>
					<p class="section-label">Agents</p>
					<h2 class="mt-2 text-xl font-semibold text-surface-50">Prompt snippet for `agents.md`</h2>
				</div>
				<span class="status-pill warn">drop-in</span>
			</div>
			<p class="text-sm text-surface-400 mb-4">
				This is short enough to paste into an agent instructions file, while still telling the agent how to use the memory layer.
			</p>
			<pre class="overflow-x-auto border border-white/10 bg-black/30 p-4 text-[0.72rem] leading-6 text-surface-200 no-scrollbar" transition:fly={{ y: 8, duration: 140 }}><code>{agentSnippet}</code></pre>
		</section>

		<section class="border border-white/10 bg-white/[0.03] p-6 md:p-7" transition:fade={{ duration: 160 }}>
			<div class="flex items-center justify-between gap-4 mb-5">
				<div>
					<p class="section-label">Agent Flow</p>
					<h2 class="mt-2 text-xl font-semibold text-surface-50">What agents should do</h2>
				</div>
				<span class="status-pill idle">workflow</span>
			</div>
			<div class="space-y-4 text-sm text-surface-300 leading-7">
				<p>1. Recall relevant memories before answering or planning work.</p>
				<p>2. Store durable facts, preferences, decisions, and procedures after they are confirmed.</p>
				<p>3. Use `memory_list` for direct inspection, `memory_archive` for stale items, and `memory_queue_status` for backlog awareness.</p>
				<p>4. Prefer the gateway and MCP tools over direct database access.</p>
			</div>
		</section>
	</div>
</main>
