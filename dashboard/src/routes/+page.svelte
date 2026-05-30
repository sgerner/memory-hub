<script lang="ts">
	import { enhance } from '$app/forms';
	import { fade, fly } from 'svelte/transition';
	import { flip } from 'svelte/animate';

	let { data, form } = $props();

	let pendingAction = $state<string | null>(null);
	const loadingRows = [0, 1, 2];

	const makeEnhancer = (action: string) => {
		return () => {
			pendingAction = action;
			return async ({ update }: { update: () => Promise<void> }) => {
				try {
					await update();
				} finally {
					pendingAction = null;
				}
			};
		};
	};

	const statusTone = (status: string) =>
		status === 'active'
			? 'preset-filled-success-500'
			: status === 'forgotten'
				? 'preset-filled-error-500'
				: 'preset-filled-warning-500';

	const lifecycle = (memory: { metadata?: Record<string, unknown> }) =>
		String(memory.metadata?.lifecycle_status ?? 'active');

	const dateLabel = (memory: { metadata?: Record<string, unknown> }) => {
		const value = memory.metadata?.recorded_at ?? memory.metadata?.updated_at ?? memory.metadata?.created_at;
		if (!value) return 'legacy record';
		const asNumber = Number(value);
		const date = Number.isFinite(asNumber) ? new Date(asNumber * 1000) : new Date(String(value));
		return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleDateString();
	};

	const actionBusy = (...actions: string[]) => actions.includes(pendingAction ?? '');

	const runtimeMessage = (entry: {
		data?: Record<string, unknown> | null;
	}) => {
		const messages: string[] = [];
		if (entry.data?.last_error) messages.push(String(entry.data.last_error));
		if ((entry.data as Record<string, unknown> | undefined)?.primary_cooldown_active) {
			messages.push(
				`Primary cooldown until ${String((entry.data as Record<string, unknown>).primary_cooldown_until ?? 'unknown')}`
			);
		}
		return messages.join(' • ');
	};

	const shorten = (value: string, max = 84) => {
		const clean = value.replace(/\s+/g, ' ').trim();
		if (clean.length <= max) return clean;
		return `${clean.slice(0, max - 1)}…`;
	};

	const runtimeDotTone = (status: string) => {
		if (status === 'running' || status === 'healthy' || status === 'ok' || status === 'busy') return 'bg-success-400';
		if (status === 'degraded' || status === 'queued' || status === 'deferred') return 'bg-warning-400';
		if (status === 'idle' || status === 'stalled' || status === 'unknown') return 'bg-surface-400';
		return 'bg-error-400';
	};

	const runtimeReason = (entry: {
		data?: Record<string, unknown> | null;
	}) => {
		const rawStatus = String(entry.data?.status ?? 'unknown');
		if (rawStatus === 'idle' || rawStatus === 'running' || rawStatus === 'healthy' || rawStatus === 'ok' || rawStatus === 'busy') {
			return '';
		}
		const message = runtimeMessage(entry);
		if (message) return message;
		if (rawStatus === 'deferred' || rawStatus === 'queued') return 'Waiting for the next cycle.';
		if (rawStatus === 'degraded') return 'Running, but degraded.';
		if (rawStatus === 'stalled') return 'Stalled and needs attention.';
		if (rawStatus === 'unknown') return 'Status unavailable.';
		return `Status: ${rawStatus}`;
	};

	const runtimeStatusTone = (status: string) => {
		if (status === 'running' || status === 'healthy' || status === 'ok' || status === 'busy') return 'preset-tonal-success';
		if (status === 'deferred' || status === 'queued' || status === 'degraded') return 'preset-tonal-warning';
		if (status === 'idle' || status === 'unknown') return 'preset-tonal-surface';
		return 'preset-tonal-error';
	};
</script>

<svelte:head>
	<title>Memory Hub | Personal agents</title>
</svelte:head>

<main class="dashboard-shell grid gap-6 py-6 md:py-8">
	{#if data.backendError}
		<div class="glass-panel border border-warning-500/30 px-4 py-3 text-sm text-warning-100" transition:fade>
			{data.backendError}
		</div>
	{/if}

	{#if form?.message}
		<div class="glass-panel border border-primary-500/30 px-4 py-3 text-sm text-primary-100" transition:fade>
			{form.message}
		</div>
	{/if}

	<section class="glass-panel p-4 md:p-5" transition:fade>
		<div class="grid gap-2 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-7">
			{#if data.observability.length === 0}
				<div class="chip preset-tonal-surface">No worker signals yet</div>
			{:else}
				{#each data.observability as entry (entry.label)}
					<article class="border border-white/10 bg-black/20 p-3 shadow-[0_0_0_1px_rgba(255,255,255,0.03)_inset]" transition:fly={{ y: 8, duration: 180 }}>
						<div class="flex flex-wrap items-center gap-x-3 gap-y-2">
							<span
								class={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${runtimeDotTone(entry.data?.status ?? 'unknown')}`}
								aria-hidden="true"
							></span>
							<p class="min-w-0 flex-1 text-sm font-medium text-surface-100">{entry.label.replace(/\s*worker$/i, '')}</p>
							<span class={`badge ${runtimeStatusTone(String(entry.data?.status ?? 'unknown'))} shrink-0 text-[10px] uppercase tracking-[0.18em]`}>
								{String(entry.data?.status ?? 'unknown')}
							</span>
						</div>
						{#if runtimeReason(entry)}
							<p class="mt-2 text-[11px] leading-tight text-surface-300">{shorten(runtimeReason(entry))}</p>
						{/if}
					</article>
				{/each}
			{/if}
		</div>
	</section>

	<section class="grid gap-4 xl:grid-cols-2">
		<form
			method="POST"
			action="?/recall"
			use:enhance={makeEnhancer('recall')}
			class="glass-panel grid gap-4 p-5 md:p-6"
			aria-busy={actionBusy('recall')}
		>
			<div class="flex items-start justify-between gap-3">
				<div>
					<p class="section-kicker">Ask</p>
					<h2 class="section-title mt-1">Semantic recall</h2>
				</div>
				{#if actionBusy('recall')}
					<span class="badge preset-tonal-primary">
						<span class="loading-dot mr-2"></span>
						Searching
					</span>
				{/if}
			</div>
			<textarea
				class="textarea preset-outlined-surface-200-800 min-h-32"
				name="query"
				rows="4"
				placeholder="What decisions did I make about authentication?"
			>{form?.operation === 'recall' ? form.query : ''}</textarea>
			<div class="flex flex-col gap-3 sm:flex-row sm:items-end">
				<label class="label grow">
					<span class="label-text">Category</span>
						<select class="select preset-outlined-surface-200-800" name="category">
						<option value="">All categories</option>
						{#each data.categories as category}
							<option value={category}>{category}</option>
						{/each}
					</select>
				</label>
				<button class="btn preset-filled-primary-500" type="submit" disabled={actionBusy('recall')}>
					{#if actionBusy('recall')}
						<span class="loading-dot mr-2"></span>
						Working
					{:else}
						Recall
					{/if}
				</button>
			</div>
		</form>

		<form
			method="POST"
			action="?/store"
			use:enhance={makeEnhancer('store')}
			class="glass-panel grid gap-4 p-5 md:p-6"
			aria-busy={actionBusy('store')}
		>
			<div class="flex items-start justify-between gap-3">
				<div>
					<p class="section-kicker">Add</p>
					<h2 class="section-title mt-1">Record memory</h2>
				</div>
				{#if actionBusy('store')}
					<span class="badge preset-tonal-primary">
						<span class="loading-dot mr-2"></span>
						Saving
					</span>
				{/if}
			</div>
			<textarea
				class="textarea preset-outlined-surface-200-800 min-h-32"
				name="content"
				rows="4"
				placeholder="Prefer Authentik forward auth for dashboard routes."
			></textarea>
			<div class="grid gap-3 sm:grid-cols-3">
				<select class="select preset-outlined-surface-200-800" name="kind">
					{#each ['fact', 'preference', 'decision', 'procedure', 'observation', 'episode'] as kind}
						<option value={kind}>{kind}</option>
					{/each}
				</select>
				<select class="select preset-outlined-surface-200-800" name="retention">
					<option value="normal">normal</option>
					<option value="durable">durable</option>
					<option value="ephemeral">ephemeral</option>
				</select>
				<button class="btn preset-filled-primary-500" type="submit" disabled={actionBusy('store')}>
					{#if actionBusy('store')}
						<span class="loading-dot mr-2"></span>
						Saving
					{:else}
						Store
					{/if}
				</button>
			</div>
			<input type="hidden" name="category" value="agent" />
			<input type="hidden" name="importance" value="0.5" />
			<input type="hidden" name="confidence" value="0.8" />
		</form>
	</section>

	<section class="glass-panel p-5 md:p-6" transition:fade>
		<div class="flex items-center justify-between gap-3">
			<div>
				<p class="section-kicker">Results</p>
				<h2 class="section-title mt-1">Recall matches</h2>
			</div>
			{#if form?.recallResults}
				<span class="badge preset-tonal-primary">{form.recallResults.length} matches</span>
			{:else if actionBusy('recall')}
				<span class="badge preset-tonal-surface">
					<span class="loading-dot mr-2"></span>
					Loading
				</span>
			{/if}
		</div>

		<div class="mt-4 grid gap-3">
			{#if actionBusy('recall') && !form?.recallResults}
				{#each loadingRows as row}
					<div class="loading-shimmer p-4" style={`min-height: ${row === 0 ? '7rem' : '5rem'}`}></div>
				{/each}
			{:else if form?.recallResults}
				<div class="grid gap-3">
					{#each form.recallResults as memory (memory.id)}
						<article class="glass-panel p-4" transition:fly={{ y: 10, duration: 180 }}>
							<div class="mb-2 flex flex-wrap gap-2 text-xs">
								<span class="badge preset-tonal-primary">{memory.category}</span>
								<span class={`badge ${statusTone(lifecycle(memory))}`}>{lifecycle(memory)}</span>
								{#if memory.distance !== undefined}
									<span class="text-surface-400">distance {memory.distance.toFixed(4)}</span>
								{/if}
							</div>
							<p class="memory-body text-sm text-surface-200">{memory.document}</p>
						</article>
					{/each}
				</div>
			{:else}
				<p class="py-10 text-center text-sm text-surface-400">Run a recall query to see matches here.</p>
			{/if}
		</div>
	</section>

	<section id="records" class="glass-panel overflow-hidden" transition:fade>
		<div class="flex flex-col gap-4 border-b border-white/10 p-5 md:flex-row md:items-center md:justify-between md:p-6">
			<div>
				<p class="section-kicker">Records</p>
				<h2 class="section-title mt-1">Recent records</h2>
			</div>
			<nav class="flex flex-wrap gap-2">
				{#each data.categories as category}
					<a
						class={`btn btn-sm ${
							data.category === category ? 'preset-filled-primary-500' : 'preset-tonal-surface'
						}`}
						href={`/?category=${category}&inactive=${data.includeInactive}`}
					>
						{category}
					</a>
				{/each}
				<a class="btn btn-sm preset-tonal-surface" href={`/?category=${data.category}&inactive=${!data.includeInactive}`}>
					{data.includeInactive ? 'Hide inactive' : 'Include inactive'}
				</a>
			</nav>
		</div>

		<div class="grid gap-3 p-5 md:p-6">
			{#if pendingAction && pendingAction !== 'recall' && pendingAction !== 'store'}
				<div class="loading-shimmer p-4 text-sm text-surface-300">
					Updating records...
				</div>
			{/if}

			{#if data.memories.length === 0}
				<p class="py-12 text-center text-sm text-surface-400">No records available in this view.</p>
			{/if}

			{#each data.memories as memory (memory.id)}
				<article class="glass-panel p-4 md:p-5" transition:fly={{ y: 10, duration: 180 }}>
					<div class="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
						<div class="min-w-0 flex-1">
							<div class="mb-2 flex flex-wrap items-center gap-2">
								<span class={`badge ${statusTone(lifecycle(memory))}`}>{lifecycle(memory)}</span>
								<span class="font-mono text-xs text-surface-400">#{memory.id}</span>
								<span class="text-xs text-surface-500">{dateLabel(memory)}</span>
							</div>
							<p class="memory-body text-sm text-surface-200">{memory.document}</p>
						</div>
						{#if lifecycle(memory) === 'active'}
							<div class="flex gap-2">
								<form method="POST" action="?/archive" use:enhance={makeEnhancer(`archive-${memory.id}`)}>
									<input type="hidden" name="category" value={memory.category} />
									<input type="hidden" name="id" value={memory.id} />
									<button class="btn btn-sm preset-tonal-warning" type="submit" disabled={actionBusy(`archive-${memory.id}`)}>
										{#if actionBusy(`archive-${memory.id}`)}
											<span class="loading-dot mr-2"></span>
											Archiving
										{:else}
											Archive
										{/if}
									</button>
								</form>
								<form method="POST" action="?/forget" use:enhance={makeEnhancer(`forget-${memory.id}`)}>
									<input type="hidden" name="category" value={memory.category} />
									<input type="hidden" name="id" value={memory.id} />
									<button class="btn btn-sm preset-tonal-error" type="submit" disabled={actionBusy(`forget-${memory.id}`)}>
										{#if actionBusy(`forget-${memory.id}`)}
											<span class="loading-dot mr-2"></span>
											Forgetting
										{:else}
											Forget
										{/if}
									</button>
								</form>
							</div>
						{/if}
					</div>
				</article>
			{/each}
		</div>
	</section>

</main>
