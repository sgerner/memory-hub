<script lang="ts">
	import { fade } from 'svelte/transition';

	let { data } = $props();
	let copied = $state(false);
	let copyTimer: ReturnType<typeof setTimeout> | null = null;

	const cliInstall = () => `npm install -g memory-hub-cli
export MEMOREX_URL=${data.gatewayUrl || 'https://your-memory-domain.example'}
export MEMOREX_TOKEN=${data.gatewayToken || 'your_gateway_token'}

memorex recall "What decisions did I make about authentication?"
memorex store "Prefer migration scripts to manual schema edits." --kind preference --retention durable
memorex list agent --limit 10 --inactive
memorex queue`;

	const pluginInstall = `curl -fsSL https://raw.githubusercontent.com/sgerner/memory-hub/main/scripts/install-agent-plugins.sh | bash`;

	const mcpRemote = () => `{
  "mcpServers": {
    "memory-hub": {
      "url": "${data.gatewayUrl || 'https://your-memory-domain.example'}/mcp",
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

	const copyToken = async () => {
		if (!data.gatewayToken) return;
		await navigator.clipboard.writeText(data.gatewayToken);
		copied = true;
		if (copyTimer) clearTimeout(copyTimer);
		copyTimer = setTimeout(() => {
			copied = false;
			copyTimer = null;
		}, 1500);
	};
</script>

<svelte:head>
	<title>Access — Memory Hub</title>
</svelte:head>

<main class="shell pb-24 pt-8 md:pt-12 max-w-5xl">
	<!-- Page Header -->
	<div class="mb-12 border-b border-white/10 pb-6 flex flex-col md:flex-row md:items-end justify-between gap-6">
		<div>
			<span class="section-label">Access</span>
			<h1 class="text-3xl font-bold text-surface-50 mt-1">Connection & Integration</h1>
			<p class="text-xs font-mono text-surface-500 mt-2 max-w-2xl">
				Operator quick-start and agent configuration parameters for CLI tools, MCP clients, and instructions.
			</p>
		</div>
		<a href="/settings" class="ghost-btn self-start md:self-center">Open settings</a>
	</div>

	<!-- Gateway Token Section -->
	<section class="border-b border-white/10 pb-8 mb-12" transition:fade={{ duration: 160 }}>
		<div class="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-6">
			<div>
				<p class="font-mono text-[0.62rem] font-bold tracking-[0.2em] uppercase text-primary-400">Gateway Token</p>
				<h2 class="text-base font-semibold text-surface-100 mt-1">Authentication Credentials</h2>
				<p class="font-mono text-[0.68rem] text-surface-500 mt-1 max-w-xl">
					Pass this bearer token via request authorization headers to access gateway endpoints from remote clients.
				</p>
			</div>
			<div class="flex items-center gap-3">
				<span class="status-pill {data.gatewayToken ? 'active' : 'forgotten'}">
					{data.gatewayToken ? 'active' : 'missing'}
				</span>
				<button class="btn-primary" type="button" onclick={copyToken} disabled={!data.gatewayToken}>
					{copied ? 'copied' : 'copy token'}
				</button>
			</div>
		</div>

		<div class="bg-[#030508]/50 border border-white/5 p-4 font-mono text-xs">
			<span class="text-surface-500 block mb-1 text-[0.55rem] tracking-wider">GATEWAY_BEARER_TOKEN</span>
			<code class="text-surface-200 break-all select-all font-mono font-medium">
				{data.gatewayToken || 'Set MEMORY_GATEWAY_TOKEN in target system environments.'}
			</code>
		</div>
	</section>

	<!-- Integration Grid -->
	<div class="grid gap-8 md:grid-cols-2 lg:grid-cols-3 mb-12">
		<!-- Operator CLI -->
		<div class="space-y-4">
			<div class="flex items-baseline justify-between border-b border-white/5 pb-2">
				<span class="section-label">Operator CLI</span>
				<span class="status-pill active">npm package</span>
			</div>
			<h3 class="text-lg font-bold text-surface-50 mt-2">Use `memorex`</h3>
			<p class="font-mono text-[0.68rem] text-surface-500 leading-normal">
				Global command line operator for querying, listing, and committing facts directly from your terminal.
			</p>
			<pre class="bg-[#030508]/50 border border-white/5 p-4 text-[0.68rem] font-mono leading-5 text-surface-200 overflow-x-auto no-scrollbar"><code>{cliInstall()}</code></pre>
		</div>

		<!-- Agent Plugins -->
		<div class="space-y-4">
			<div class="flex items-baseline justify-between border-b border-white/5 pb-2">
				<span class="section-label">Agent Plugins</span>
				<span class="status-pill active">one command</span>
			</div>
			<h3 class="text-lg font-bold text-surface-50 mt-2">Automated Installer</h3>
			<p class="font-mono text-[0.68rem] text-surface-500 leading-normal">
				One-line bootstrap command to configure Memory Hub integration scripts for Codex, Antigravity, and OpenCode.
			</p>
			<pre class="bg-[#030508]/50 border border-white/5 p-4 text-[0.68rem] font-mono leading-5 text-surface-200 overflow-x-auto no-scrollbar"><code>{pluginInstall}</code></pre>
		</div>

		<!-- Remote MCP -->
		<div class="space-y-4">
			<div class="flex items-baseline justify-between border-b border-white/5 pb-2">
				<span class="section-label">Remote MCP</span>
				<span class="status-pill running">http transport</span>
			</div>
			<h3 class="text-lg font-bold text-surface-50 mt-2">Connect Remote Clients</h3>
			<p class="font-mono text-[0.68rem] text-surface-500 leading-normal">
				Configure Model Context Protocol clients (e.g. Claude Desktop) on other devices to discover local memory tools.
			</p>
			<pre class="bg-[#030508]/50 border border-white/5 p-4 text-[0.68rem] font-mono leading-5 text-surface-200 overflow-x-auto no-scrollbar"><code>{mcpRemote()}</code></pre>
		</div>
	</div>

	<!-- System Prompt / cognitive guidelines -->
	<div class="border-t border-white/10 pt-8 grid gap-8 md:grid-cols-2">
		<!-- System Prompt Snippet -->
		<div class="space-y-4">
			<div class="flex items-baseline justify-between border-b border-white/5 pb-2">
				<span class="section-label">Instructions</span>
				<span class="status-pill archived">agents.md</span>
			</div>
			<h3 class="text-lg font-bold text-surface-50 mt-2">System Instructions</h3>
			<p class="font-mono text-[0.68rem] text-surface-500 leading-normal">
				Inject this snippet into your agent's system prompt or workspace context file to enable standard tool usage.
			</p>
			<pre class="bg-[#030508]/50 border border-white/5 p-4 text-[0.68rem] font-mono leading-5 text-surface-200 overflow-x-auto no-scrollbar max-h-96"><code>{agentSnippet}</code></pre>
		</div>

		<!-- Workflow guidelines -->
		<div class="space-y-4">
			<div class="flex items-baseline justify-between border-b border-white/5 pb-2">
				<span class="section-label">Cognitive Flow</span>
				<span class="status-pill active">best practices</span>
			</div>
			<h3 class="text-lg font-bold text-surface-50 mt-2">Memory Lifecycle Rules</h3>
			<p class="font-mono text-[0.68rem] text-surface-500 leading-normal">
				Standard operating instructions for agents managing system memories during tasks.
			</p>

			<div class="space-y-3.5 pt-2">
				<div class="flex gap-3">
					<span class="font-mono text-[0.7rem] text-primary-400">01 /</span>
					<p class="text-xs text-surface-200 font-mono leading-relaxed"><span class="text-surface-100 font-semibold font-sans">Recall Context First:</span> Always query relevant memories before formulating complex plans or answers.</p>
				</div>
				<div class="flex gap-3 border-t border-white/5 pt-3.5">
					<span class="font-mono text-[0.7rem] text-primary-400">02 /</span>
					<p class="text-xs text-surface-200 font-mono leading-relaxed"><span class="text-surface-100 font-semibold font-sans">Commit Confirmed Facts:</span> Save durable preferences, key project structures, and confirmed facts during steps.</p>
				</div>
				<div class="flex gap-3 border-t border-white/5 pt-3.5">
					<span class="font-mono text-[0.7rem] text-primary-400">03 /</span>
					<p class="text-xs text-surface-200 font-mono leading-relaxed"><span class="text-surface-100 font-semibold font-sans">Decay & Supersede:</span> Proactively archive stale preferences, update obsoleted logic, and clean the backlog.</p>
				</div>
				<div class="flex gap-3 border-t border-white/5 pt-3.5">
					<span class="font-mono text-[0.7rem] text-primary-400">04 /</span>
					<p class="text-xs text-surface-200 font-mono leading-relaxed"><span class="text-surface-100 font-semibold font-sans">Gateway Focus:</span> Route queries and commits via the Model Context Protocol (MCP) or CLI layers instead of direct DB insertions.</p>
				</div>
			</div>
		</div>
	</div>
</main>
