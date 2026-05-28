<script lang="ts">
	import { page } from '$app/state';
	import '../app.css';

	const nav = [
		{ href: '/', label: 'Overview', hint: 'Memory activity and recent records' },
		{ href: '/settings', label: 'Settings', hint: 'Secrets, sources, worker controls' }
	];
</script>

<svelte:head>
	<meta name="color-scheme" content="dark" />
</svelte:head>

<div class="relative min-h-screen overflow-hidden">
	<div class="aurora aura-left"></div>
	<div class="aurora aura-right"></div>
	<div class="aurora aura-bottom"></div>

		<header class="sticky top-0 z-20 border-b border-white/10 bg-surface-950/70 backdrop-blur-xl">
			<div class="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-6 py-4">
				<div class="space-y-1">
					<p class="text-xs font-semibold uppercase tracking-[0.34em] text-primary-300">Memory Hub</p>
				</div>
				<div class="flex flex-wrap items-center gap-2">
					{#if page.data?.backendError}
						<span class="badge preset-tonal-warning">
							<span class="loading-dot mr-2"></span>
							Data unavailable
						</span>
					{:else if page.url.pathname === '/'}
						<span class="badge preset-tonal-success">
							<span class="loading-dot mr-2"></span>
							Gateway online
						</span>
					{/if}
					<nav class="flex flex-wrap gap-2">
						{#each nav as item}
							<a
								class={`btn btn-sm ${
									page.url.pathname === item.href ? 'preset-filled-primary-500' : 'preset-tonal-surface'
								}`}
								href={item.href}
								title={item.hint}
							>
								{item.label}
							</a>
						{/each}
					</nav>
				</div>
			</div>
		</header>

	<slot />
</div>
