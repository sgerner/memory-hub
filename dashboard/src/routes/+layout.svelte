<script lang="ts">
	import { page } from '$app/state';
	import { fade } from 'svelte/transition';
	import '../app.css';

	const nav = [
		{ href: '/', label: 'Overview', hint: 'Memory activity and recent records' },
		{ href: '/access', label: 'Access', hint: 'CLI, MCP, and agent instructions' },
		{ href: '/settings', label: 'Settings', hint: 'Enrichment, sources, worker controls' }
	];

	function getWorkerSuggestion(label: string, error?: string): string {
		const err = (error ?? '').toLowerCase();
		const l = label.toLowerCase();
		if (l.includes('email')) {
			if (err.includes('password') || err.includes('auth') || err.includes('login') || err.includes('credential')) {
				return "Please check and update your IMAP password under 'Email Ingestion' in Settings.";
			}
			return "Check IMAP host, port, security credentials, or connection settings under 'Email Ingestion' in Settings.";
		}
		if (l.includes('github')) {
			return "Verify that your GitHub Personal Access Token is correct and active under 'File Ingestion' in Settings.";
		}
		if (l.includes('obsidian')) {
			return "Check that your Obsidian Vault directory path is correct and accessible on the local system.";
		}
		if (l.includes('docs') || l.includes('document')) {
			return "Ensure the directory paths listed under 'Documents Ingestion' exist on the host filesystem and are readable.";
		}
		if (l.includes('enrich')) {
			return "Check your primary/fallback API tokens under 'Enrichment' in Settings, or verify model endpoints.";
		}
		if (l.includes('backup')) {
			return "Ensure the backup destination directory is writable and the filesystem has sufficient space.";
		}
		return "Please verify the credentials, connection settings, or review the stack docker container logs.";
	}

	const formatBacklog = (value?: number | null) => {
		const count = Number(value ?? 0);
		if (!Number.isFinite(count)) return '0';
		if (count >= 1000) return `${(count / 1000).toFixed(count >= 100000 ? 0 : 1).replace(/\.0$/, '')}k`;
		return String(count);
	};
</script>

<svelte:head>
	<meta name="color-scheme" content="dark" />
</svelte:head>

<!-- Sticky header -->
<header class="sticky top-0 z-50">
	<!-- Nav bar -->
	<div class="flex flex-col md:flex-row md:items-center justify-between gap-4 md:gap-6 px-6 py-3 border-b border-white/[0.06] bg-[#030508]/90 backdrop-blur-xl">
		<div class="flex flex-col sm:flex-row sm:items-center gap-4 sm:gap-8">
			<div class="flex items-center gap-2.5">
				<div class="w-1.5 h-1.5 rounded-full bg-primary-400" style="box-shadow: 0 0 8px var(--color-primary-400)"></div>
				<span class="font-mono text-[0.6rem] font-bold tracking-[0.4em] uppercase text-surface-300">Memory Hub</span>
			</div>
			<nav class="flex items-center gap-1 overflow-x-auto no-scrollbar">
				{#each nav as item}
					<a
						href={item.href}
						class="font-mono text-[0.62rem] font-semibold tracking-[0.16em] uppercase px-3 py-1.5 transition-colors whitespace-nowrap {page.url.pathname === item.href ? 'text-primary-300 bg-primary-500/10' : 'text-surface-500 hover:text-surface-200'}"
					>
						{item.label}
					</a>
				{/each}
			</nav>
		</div>

		{#if page.data?.backendError}
			<span class="process-status error font-mono text-[0.58rem] self-start md:self-auto mt-1 md:mt-0">
				<span class="pulse-dot mr-1.5"></span>
				Backend offline
			</span>
		{:else if page.url.pathname === '/'}
			<div class="flex flex-wrap items-center gap-2 self-start md:self-auto mt-1 md:mt-0">
				<span class="process-status running font-mono text-[0.58rem]">
					<span class="pulse-dot mr-1.5"></span>
					Gateway online
				</span>
				{#if page.data?.queueStatus?.totals}
					<span class="process-status idle font-mono text-[0.58rem]">
						Embed {formatBacklog(page.data.queueStatus.totals.embedding_pending)}
					</span>
					<span class="process-status warn font-mono text-[0.58rem]">
						Enrich {formatBacklog(page.data.queueStatus.totals.enrichment_pending)}
					</span>
				{/if}
			</div>
		{/if}
	</div>

	<!-- Worker process bar -->
	<div class="process-bar no-scrollbar">
		{#if (page.data?.observability ?? []).length > 0}
			{#each (page.data?.observability ?? []) as entry}
				{@const status = String(entry.data?.status ?? 'unknown')}
				{@const dotClass = status === 'running' || status === 'healthy' || status === 'ok' || status === 'busy' ? 'running' : status === 'error' ? 'error' : status === 'deferred' || status === 'queued' || status === 'degraded' ? 'warn' : 'idle'}
				<div class="process-entry" title={entry.label}>
					<div class="process-dot {dotClass}"></div>
					<span class="process-name">{entry.label.replace(/\s*worker$/i, '')}</span>
					<span class="process-status {dotClass}">{status}</span>
				</div>
			{/each}
		{/if}
	</div>

	<!-- Worker error alerts -->
		{#if page.data?.observability}
			{#each page.data.observability as entry}
				{#if entry.data?.status === 'error'}
					<div class="border-b border-error-500/25 bg-error-950/20 px-6 py-3.5 flex flex-col md:flex-row md:items-center justify-between gap-4 font-mono text-xs" transition:fade>
						<div class="flex items-start gap-3 min-w-0">
							<span class="text-error-400 font-bold shrink-0 mt-0.5">[ERROR] {entry.label.toUpperCase()}{entry.data.current_account ? ` (${entry.data.current_account})` : ''}:</span>
							<div class="min-w-0">
								<p class="text-surface-100 font-medium break-words">{entry.data.last_error || 'An unexpected error was reported.'}</p>
								<p class="text-surface-400 text-[10px] mt-1"><span class="text-surface-500 font-bold">REMEDY:</span> {getWorkerSuggestion(entry.label, entry.data.last_error)}</p>
							</div>
					</div>
					<a href="/settings" class="ghost-btn danger shrink-0 self-start md:self-center text-center">Update settings</a>
				</div>
			{/if}
		{/each}
	{/if}
</header>

<slot />
