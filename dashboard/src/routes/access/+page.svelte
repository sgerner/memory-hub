<script lang="ts">
	import { fade, fly } from 'svelte/transition';

	let { data } = $props();
	let copiedId = $state<string | null>(null);
	let copyTimer: ReturnType<typeof setTimeout> | null = null;

	const copyToClipboard = async (text: string, id: string) => {
		await navigator.clipboard.writeText(text);
		copiedId = id;
		if (copyTimer) clearTimeout(copyTimer);
		copyTimer = setTimeout(() => {
			copiedId = null;
			copyTimer = null;
		}, 2000);
	};

	const cliInstall = () => `npm install -g memory-hub-cli
export MEMOREX_URL=${data.apiUrl || 'https://your-memory-domain.example/api'}
export MEMOREX_TOKEN=${data.gatewayToken || 'your_gateway_token'}

memorex recall "What decisions did I make about authentication?"
memorex store "Prefer migration scripts to manual schema edits." --kind preference --retention durable
memorex list agent --limit 10 --inactive
memorex queue`;

	const pluginInstall = `curl -fsSL https://raw.githubusercontent.com/sgerner/memory-hub/main/scripts/install-agent-plugins.sh | bash`;

	const mcpRemote = () => `{
  "mcpServers": {
    "memory-hub": {
      "url": "${data.mcpUrl || 'https://your-memory-domain.example/mcp'}",
      "headers": {
        "Authorization": "Bearer ${data.gatewayToken || 'your_gateway_token'}"
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

	const integrations = [
		{
			id: 'cli',
			num: '01',
			label: 'Operator CLI',
			badge: 'npm package',
			title: 'Use `memorex`',
			desc: 'Global command-line operator for querying, listing, and committing facts directly from your terminal.',
			code: () => cliInstall(),
			codeId: 'cli',
			accent: 'primary',
		},
		{
			id: 'plugin',
			num: '02',
			label: 'Agent Plugins',
			badge: 'one command',
			title: 'Automated Installer',
			desc: 'One-line bootstrap to configure Memory Hub integration scripts for Codex, Antigravity, and OpenCode.',
			code: () => pluginInstall,
			codeId: 'plugin',
			accent: 'secondary',
		},
		{
			id: 'mcp',
			num: '03',
			label: 'Remote MCP',
			badge: 'http transport',
			title: 'Connect Remote Clients',
			desc: 'Configure MCP clients (e.g. Claude Desktop) on other devices to discover local memory tools via the public `/mcp` endpoint.',
			code: () => mcpRemote(),
			codeId: 'mcp',
			accent: 'tertiary',
		},
	];

	const rules = [
		{ n: '01', head: 'Recall Context First', body: 'Always query relevant memories before formulating complex plans or answers.' },
		{ n: '02', head: 'Commit Confirmed Facts', body: 'Save durable preferences, key project structures, and confirmed facts during tasks.' },
		{ n: '03', head: 'Decay & Supersede', body: 'Proactively archive stale preferences, update obsoleted logic, and clean the backlog.' },
		{ n: '04', head: 'Gateway Focus', body: 'Route queries and commits via MCP or CLI layers instead of direct DB insertions.' },
	];
</script>

<svelte:head>
	<title>Access — Memory Hub</title>
</svelte:head>

<main class="shell pb-32 pt-10 md:pt-14 max-w-5xl" in:fade={{ duration: 180 }}>

	<!-- ── Page header ─────────────────────────────────────────────────── -->
	<div class="mb-14 flex flex-col md:flex-row md:items-end justify-between gap-6">
		<div>
			<span class="section-label">Access</span>
			<h1 class="text-4xl font-bold text-surface-50 mt-2 leading-tight tracking-tight">
				Connection &amp; Integration
			</h1>
			<p class="font-mono text-sm text-surface-500 mt-3 max-w-xl leading-relaxed">
				Operator quick-start and agent configuration parameters for CLI tools, MCP clients, and instructions.
			</p>
		</div>
		<a href="/settings" class="ghost-btn self-start md:self-center">Open settings ›</a>
	</div>

	<!-- ── Resolved origin ─────────────────────────────────────────────── -->
	<div class="access-origin-card mb-14" in:fly={{ y: 8, duration: 200, delay: 40 }}>
		<div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
			<div>
				<p class="section-label mb-2">Resolved Public Origin</p>
				<p class="text-lg text-surface-100 font-mono break-all font-medium">{data.publicOrigin}</p>
			</div>
			<div class="flex flex-wrap gap-2 shrink-0">
				<span class="status-pill active">API: {data.apiUrl}</span>
				<span class="status-pill running">MCP: {data.mcpUrl}</span>
			</div>
		</div>
	</div>

	<!-- ── Gateway token ───────────────────────────────────────────────── -->
	<section class="mb-16" in:fly={{ y: 8, duration: 200, delay: 80 }}>
		<div class="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-5">
			<div>
				<span class="section-label">Gateway Token</span>
				<h2 class="text-xl font-semibold text-surface-100 mt-1">Authentication Credentials</h2>
				<p class="font-mono text-sm text-surface-500 mt-1 max-w-xl leading-relaxed">
					Pass this bearer token via request authorization headers to access gateway endpoints from remote clients.
				</p>
			</div>
			<span class="status-pill {data.gatewayToken ? 'active' : 'forgotten'} self-start shrink-0">
				{data.gatewayToken ? 'active' : 'missing'}
			</span>
		</div>

		<div class="access-code-block relative group">
			<span class="access-code-label">GATEWAY_BEARER_TOKEN</span>
			<code class="text-surface-200 break-all select-all font-mono text-sm font-medium leading-relaxed block mt-1">
				{data.gatewayToken || 'Set MEMORY_GATEWAY_TOKEN in target system environments.'}
			</code>
			{#if data.gatewayToken}
				<button
					class="access-copy-btn"
					type="button"
					onclick={() => copyToClipboard(data.gatewayToken, 'token')}
					title="Copy to clipboard"
				>
					{#if copiedId === 'token'}
						<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="text-success-400"><polyline points="20 6 9 17 4 12"></polyline></svg>
						<span class="font-mono text-[0.6rem] tracking-wider text-success-400">COPIED</span>
					{:else}
						<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
					{/if}
				</button>
			{/if}
		</div>
	</section>

	<!-- ── Integration cards ───────────────────────────────────────────── -->
	<div class="mb-4">
		<span class="section-label">Integration Methods</span>
	</div>
	<div class="grid gap-6 md:grid-cols-3 mb-16">
		{#each integrations as intg, i}
			<div class="access-intg-card access-intg-{intg.accent}" in:fly={{ y: 10, duration: 200, delay: 100 + i * 50 }}>
				<div class="flex items-baseline justify-between mb-5">
					<span class="font-mono text-3xl font-bold text-white/[0.06] select-none leading-none">{intg.num}</span>
					<span class="status-pill {intg.accent === 'primary' ? 'active' : intg.accent === 'secondary' ? 'running' : 'archived'}">{intg.badge}</span>
				</div>
				<div class="mb-2">
					<span class="section-label">{intg.label}</span>
				</div>
				<h3 class="text-lg font-bold text-surface-50 mb-2">{intg.title}</h3>
				<p class="font-mono text-sm text-surface-500 leading-relaxed mb-5">{intg.desc}</p>
				<div class="relative group">
					<pre class="access-code-block text-sm !p-3 overflow-x-auto no-scrollbar"><code class="text-surface-200 font-mono text-xs leading-relaxed">{intg.code()}</code></pre>
					<button
						class="access-copy-btn"
						type="button"
						onclick={() => copyToClipboard(intg.code(), intg.codeId)}
						title="Copy"
					>
						{#if copiedId === intg.codeId}
							<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="text-success-400"><polyline points="20 6 9 17 4 12"></polyline></svg>
						{:else}
							<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
						{/if}
					</button>
				</div>
			</div>
		{/each}
	</div>

	<!-- ── System prompt + lifecycle rules ────────────────────────────── -->
	<div class="border-t border-white/[0.07] pt-12 grid gap-12 md:grid-cols-2" in:fly={{ y: 8, duration: 200, delay: 250 }}>

		<!-- System Prompt -->
		<div>
			<span class="section-label">System Instructions</span>
			<h3 class="text-xl font-bold text-surface-50 mt-1 mb-2">Inject into Agent Context</h3>
			<p class="font-mono text-sm text-surface-500 leading-relaxed mb-5">
				Add this snippet to your agent's system prompt or workspace context file to enable standard Memory Hub tool usage.
			</p>
			<div class="relative group">
				<pre class="access-code-block overflow-x-auto no-scrollbar max-h-80"><code class="text-surface-200 font-mono text-xs leading-relaxed">{agentSnippet}</code></pre>
				<button
					class="access-copy-btn"
					type="button"
					onclick={() => copyToClipboard(agentSnippet, 'instructions')}
					title="Copy"
				>
					{#if copiedId === 'instructions'}
						<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="text-success-400"><polyline points="20 6 9 17 4 12"></polyline></svg>
					{:else}
						<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
					{/if}
				</button>
			</div>
		</div>

		<!-- Memory lifecycle rules -->
		<div>
			<span class="section-label">Cognitive Flow</span>
			<h3 class="text-xl font-bold text-surface-50 mt-1 mb-2">Memory Lifecycle Rules</h3>
			<p class="font-mono text-sm text-surface-500 leading-relaxed mb-6">
				Standard operating instructions for agents managing system memories during tasks.
			</p>
			<ol class="relative space-y-0 border-l border-white/[0.07] ml-3">
				{#each rules as rule, i}
					<li class="pl-6 pb-6 relative last:pb-0">
						<!-- dot on the timeline -->
						<span class="absolute -left-[5px] top-1 w-[9px] h-[9px] rounded-full border border-white/20 bg-surface-900"></span>
						<span class="font-mono text-[0.65rem] font-bold tracking-[0.2em] text-primary-400 uppercase">{rule.n}</span>
						<p class="text-sm font-semibold text-surface-100 mt-0.5 mb-1">{rule.head}</p>
						<p class="font-mono text-sm text-surface-500 leading-relaxed">{rule.body}</p>
					</li>
				{/each}
			</ol>
		</div>
	</div>
</main>

<style>
	/* origin card */
	.access-origin-card {
		border: 1px solid rgba(255,255,255,0.09);
		background: rgba(255,255,255,0.03);
		padding: 1.4rem 1.6rem;
		position: relative;
		overflow: hidden;
	}
	.access-origin-card::before {
		content: '';
		position: absolute;
		inset: 0;
		background: linear-gradient(135deg, color-mix(in srgb, var(--color-primary-500) 6%, transparent), transparent 60%);
		pointer-events: none;
	}

	/* integration cards */
	.access-intg-card {
		border: 1px solid rgba(255,255,255,0.07);
		background: rgba(255,255,255,0.025);
		padding: 1.4rem;
		position: relative;
		overflow: hidden;
		transition: border-color 0.2s, background 0.2s;
	}
	.access-intg-card:hover {
		background: rgba(255,255,255,0.04);
	}
	.access-intg-card::before {
		content: '';
		position: absolute;
		top: 0; left: 0; right: 0;
		height: 2px;
	}
	.access-intg-primary::before {
		background: linear-gradient(90deg, var(--color-primary-500), transparent);
	}
	.access-intg-secondary::before {
		background: linear-gradient(90deg, var(--color-secondary-500), transparent);
	}
	.access-intg-tertiary::before {
		background: linear-gradient(90deg, var(--color-tertiary-500), transparent);
	}

	/* code block */
	.access-code-block {
		position: relative;
		background: rgba(3, 5, 8, 0.7);
		border: 1px solid rgba(255,255,255,0.06);
		padding: 1rem 1.2rem;
		font-family: var(--font-mono);
	}
	.access-code-label {
		font-family: var(--font-mono);
		font-size: 0.6rem;
		font-weight: 700;
		letter-spacing: 0.2em;
		text-transform: uppercase;
		color: var(--color-surface-500);
		display: block;
	}

	/* copy button */
	.access-copy-btn {
		position: absolute;
		top: 0.6rem;
		right: 0.6rem;
		display: flex;
		align-items: center;
		gap: 0.3rem;
		padding: 0.3rem 0.5rem;
		border: 1px solid rgba(255,255,255,0.08);
		background: rgba(255,255,255,0.04);
		color: var(--color-surface-400);
		cursor: pointer;
		transition: all 0.15s;
		opacity: 0;
		border-radius: 0;
	}
	:global(.group:hover) .access-copy-btn,
	.access-code-block:hover .access-copy-btn {
		opacity: 1;
	}
	.access-copy-btn:hover {
		background: rgba(255,255,255,0.09);
		border-color: rgba(255,255,255,0.16);
		color: var(--color-surface-100);
	}

	/* running pill (not defined globally, add here) */
	:global(.status-pill.running) {
		color: var(--color-secondary-400);
		border-color: color-mix(in srgb, var(--color-secondary-400) 35%, transparent);
	}
</style>
