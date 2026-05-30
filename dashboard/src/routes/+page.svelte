<script lang="ts">
	import { enhance } from '$app/forms';
	import { fade, fly } from 'svelte/transition';

	let { data, form } = $props();

	let pendingAction = $state<string | null>(null);
	const loadingRows = [0, 1, 2];

	const makeEnhancer = (action: string) => {
		return () => {
			pendingAction = action;
			return async ({ update }: { update: () => Promise<void> }) => {
				try { await update(); } finally { pendingAction = null; }
			};
		};
	};

	const lifecycle = (memory: { metadata?: Record<string, unknown> }) =>
		String(memory.metadata?.lifecycle_status ?? 'active');

	const dateLabel = (memory: { metadata?: Record<string, unknown> }) => {
		const value = memory.metadata?.recorded_at ?? memory.metadata?.updated_at ?? memory.metadata?.created_at;
		if (!value) return null;
		const asNumber = Number(value);
		const date = Number.isFinite(asNumber) ? new Date(asNumber * 1000) : new Date(String(value));
		return Number.isNaN(date.valueOf()) ? null : date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
	};

	const actionBusy = (...actions: string[]) => actions.includes(pendingAction ?? '');

	const runtimeDotClass = (status: string) => {
		if (status === 'running' || status === 'healthy' || status === 'ok' || status === 'busy') return 'running';
		if (status === 'error') return 'error';
		if (status === 'deferred' || status === 'queued' || status === 'degraded') return 'warn';
		return 'idle';
	};

	const runtimeReason = (entry: { data?: Record<string, unknown> | null }) => {
		const rawStatus = String(entry.data?.status ?? 'unknown');
		if (['idle','running','healthy','ok','busy'].includes(rawStatus)) return '';
		if (entry.data?.last_error) return String(entry.data.last_error).slice(0, 60);
		if (rawStatus === 'deferred' || rawStatus === 'queued') return 'Waiting for next cycle';
		if (rawStatus === 'degraded') return 'Running degraded';
		if (rawStatus === 'stalled') return 'Stalled – needs attention';
		return '';
	};

	// Active view: 'query' | 'store' | 'records'
	let activeView = $state<'query' | 'store'>('query');

	const statusPillClass = (status: string) =>
		status === 'active' ? 'active' : status === 'forgotten' ? 'forgotten' : 'archived';
</script>

<svelte:head>
	<title>Memory Hub</title>
</svelte:head>

<main class="shell pb-24 pt-8 md:pt-12">

	<!-- Flash messages -->
	{#if data.backendError}
		<div class="font-mono text-xs text-error-400 border border-error-400/20 bg-error-900/20 px-4 py-3 mb-8" transition:fade>
			<span class="opacity-50 mr-2">!</span>{data.backendError}
		</div>
	{/if}
	{#if form?.message}
		<div class="font-mono text-xs text-primary-300 border border-primary-400/20 bg-primary-900/10 px-4 py-3 mb-8" transition:fade>
			<span class="opacity-50 mr-2">→</span>{form.message}
		</div>
	{/if}

	<!-- ══════════════════════════════════════════════════════════════════════
	     COMMAND INTERFACE
	     ══════════════════════════════════════════════════════════════════ -->
	<div class="max-w-3xl mx-auto mb-16 md:mb-20">

		<!-- Mode toggle -->
		<div class="flex items-center gap-6 mb-8">
			<button
				onclick={() => { activeView = 'query'; }}
				class="font-mono text-[0.65rem] font-bold tracking-[0.2em] uppercase pb-2 border-b-2 transition-all {activeView === 'query' ? 'text-primary-300 border-primary-400' : 'text-surface-600 border-transparent hover:text-surface-400'}"
			>
				Query
			</button>
			<button
				onclick={() => { activeView = 'store'; }}
				class="font-mono text-[0.65rem] font-bold tracking-[0.2em] uppercase pb-2 border-b-2 transition-all {activeView === 'store' ? 'text-primary-300 border-primary-400' : 'text-surface-600 border-transparent hover:text-surface-400'}"
			>
				Record
			</button>
		</div>

		<!-- ── QUERY FORM ── -->
		{#if activeView === 'query'}
			<form
				method="POST"
				action="?/recall"
				use:enhance={makeEnhancer('recall')}
				aria-busy={actionBusy('recall')}
				transition:fade={{ duration: 120 }}
			>
				<div class="command-prompt">
					<div class="command-input-wrap">
						<span class="command-cursor">›</span>
						<textarea
							class="command-textarea min-h-[3.5rem] max-h-48"
							name="query"
							rows="2"
							placeholder="What decisions did I make about authentication last month?"
							required
						>{form?.operation === 'recall' ? form.query : ''}</textarea>
					</div>
				</div>

				<div class="flex flex-wrap items-center gap-4 mt-5">
					<div class="flex-1 min-w-36">
						<select class="field-select" name="category">
							<option value="">All categories</option>
							{#each data.categories as cat}
								<option value={cat}>{cat}</option>
							{/each}
						</select>
					</div>
					<button class="btn-primary" type="submit" disabled={actionBusy('recall')}>
						{#if actionBusy('recall')}
							<span class="pulse-dot mr-2"></span>searching
						{:else}
							search memory
						{/if}
					</button>
				</div>
			</form>

		<!-- ── STORE FORM ── -->
		{:else}
			<form
				method="POST"
				action="?/store"
				use:enhance={makeEnhancer('store')}
				aria-busy={actionBusy('store')}
				transition:fade={{ duration: 120 }}
			>
				<div class="command-prompt">
					<div class="command-input-wrap" style="border-color: color-mix(in srgb, var(--color-secondary-500) 60%, transparent)">
						<span class="command-cursor" style="color: var(--color-secondary-400)">+</span>
						<textarea
							class="command-textarea min-h-[3.5rem] max-h-48"
							name="content"
							rows="2"
							placeholder="Prefer Authentik forward auth for all dashboard routes."
							required
						></textarea>
					</div>
				</div>

				<div class="flex flex-wrap items-center gap-4 mt-5">
					<div class="min-w-36">
						<select class="field-select" name="kind">
							{#each ['fact', 'preference', 'decision', 'procedure', 'observation', 'episode'] as k}
								<option value={k}>{k}</option>
							{/each}
						</select>
					</div>
					<div class="min-w-32">
						<select class="field-select" name="retention">
							<option value="normal">normal</option>
							<option value="durable">durable</option>
							<option value="ephemeral">ephemeral</option>
						</select>
					</div>
					<button class="btn-primary" style="background: var(--color-secondary-500)" type="submit" disabled={actionBusy('store')}>
						{#if actionBusy('store')}
							<span class="pulse-dot mr-2"></span>storing
						{:else}
							commit fact
						{/if}
					</button>
				</div>
				<input type="hidden" name="category" value="agent" />
				<input type="hidden" name="importance" value="0.5" />
				<input type="hidden" name="confidence" value="0.8" />
			</form>
		{/if}
	</div>

	<!-- ══════════════════════════════════════════════════════════════════════
	     RECALL RESULTS  (only shown when present)
	     ══════════════════════════════════════════════════════════════════ -->
	{#if form?.recallResults || (actionBusy('recall') && !form?.recallResults)}
		<section class="mb-16" transition:fly={{ y: 16, duration: 240 }}>
			<div class="flex items-center justify-between mb-6">
				<div class="flex items-center gap-3">
					<span class="section-label">Results</span>
					{#if form?.recallResults}
						<span class="font-mono text-[0.6rem] text-surface-500">
							{form.recallResults.length} match{form.recallResults.length === 1 ? '' : 'es'}
						</span>
					{/if}
				</div>
				{#if form?.recallResults}
					<a href="/" class="ghost-btn">dismiss</a>
				{/if}
			</div>

			{#if actionBusy('recall') && !form?.recallResults}
				<div class="space-y-px">
					{#each loadingRows as _}
						<div class="shimmer h-20"></div>
					{/each}
				</div>
			{:else if form?.recallResults}
				{#if form.recallResults.length === 0}
					<p class="font-mono text-sm text-surface-500 py-8">No matches found.</p>
				{:else}
					<div>
						{#each form.recallResults as memory (memory.id)}
							<div class="memory-row" transition:fly={{ y: 8, duration: 160 }}>
								<div class="flex flex-wrap items-baseline gap-x-4 gap-y-1 mb-2">
									<span class="status-pill {statusPillClass(lifecycle(memory))}">
										{lifecycle(memory)}
									</span>
									<span class="font-mono text-[0.6rem] text-surface-600">{memory.category}</span>
									{#if memory.distance !== undefined}
										<span class="font-mono text-[0.6rem] text-surface-600">
											sim {(1 - memory.distance).toFixed(3)}
										</span>
										<div class="dist-bar" style="width: {Math.max(8, (1 - memory.distance) * 100)}%"></div>
									{/if}
								</div>
								<p class="memory-body text-surface-200">{memory.document}</p>
							</div>
						{/each}
					</div>
				{/if}
			{/if}
		</section>
	{/if}

	<!-- ══════════════════════════════════════════════════════════════════════
	     RECORDS DATABASE
	     ══════════════════════════════════════════════════════════════════ -->
	<section id="records">
		<!-- Category tabs -->
		<div class="flex flex-wrap items-center justify-between gap-4 mb-6">
			<div class="cat-tabs overflow-x-auto no-scrollbar">
				{#each data.categories as cat}
					<a
						class="cat-tab {data.category === cat ? 'active' : ''}"
						href={`/?category=${cat}&inactive=${data.includeInactive}#records`}
					>
						{cat}
					</a>
				{/each}
			</div>
			<a
				class="ghost-btn {data.includeInactive ? 'warn' : ''}"
				href={`/?category=${data.category}&inactive=${!data.includeInactive}#records`}
			>
				{data.includeInactive ? '× inactive' : '+ inactive'}
			</a>
		</div>

		<!-- Records -->
		{#if pendingAction && !['recall','store'].includes(pendingAction)}
			<div class="shimmer h-14 mb-2"></div>
		{/if}

		{#if data.memories.length === 0}
			<p class="font-mono text-xs text-surface-600 py-16 text-center">
				No records in <em class="not-italic text-surface-500">{data.category}</em>
				{#if !data.includeInactive} — try enabling inactive{/if}
			</p>
		{:else}
			<div>
				{#each data.memories as memory (memory.id)}
					<div class="memory-row" transition:fly={{ y: 8, duration: 160 }}>
						<div class="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
							<!-- Left: meta + content -->
							<div class="min-w-0 flex-1">
								<div class="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-2.5">
									<span class="status-pill {statusPillClass(lifecycle(memory))}">
										{lifecycle(memory)}
									</span>
									<span class="font-mono text-[0.58rem] text-surface-600 tracking-wider">
										#{String(memory.id).slice(0, 12)}
									</span>
									{#if dateLabel(memory)}
										<span class="font-mono text-[0.58rem] text-surface-600">
											{dateLabel(memory)}
										</span>
									{/if}
								</div>
								<p class="memory-body text-surface-200">{memory.document}</p>
							</div>

							<!-- Right: actions (only for active) -->
							{#if lifecycle(memory) === 'active'}
								<div class="flex items-center gap-2 shrink-0 sm:pl-4">
									<form method="POST" action="?/archive" use:enhance={makeEnhancer(`archive-${memory.id}`)}>
										<input type="hidden" name="category" value={memory.category} />
										<input type="hidden" name="id" value={memory.id} />
										<button class="ghost-btn warn" type="submit" disabled={actionBusy(`archive-${memory.id}`)}>
											{actionBusy(`archive-${memory.id}`) ? '…' : 'archive'}
										</button>
									</form>
									<form method="POST" action="?/forget" use:enhance={makeEnhancer(`forget-${memory.id}`)}>
										<input type="hidden" name="category" value={memory.category} />
										<input type="hidden" name="id" value={memory.id} />
										<button class="ghost-btn danger" type="submit" disabled={actionBusy(`forget-${memory.id}`)}>
											{actionBusy(`forget-${memory.id}`) ? '…' : 'forget'}
										</button>
									</form>
								</div>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</section>

</main>
