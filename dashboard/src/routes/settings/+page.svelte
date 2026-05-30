<script lang="ts">
	import { enhance } from '$app/forms';
	import { Accordion } from '@skeletonlabs/skeleton-svelte';
	import { fade } from 'svelte/transition';

	let { data, form } = $props();
	let pendingAction = $state<string | null>(null);

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

	const actionBusy = (...actions: string[]) => actions.includes(pendingAction ?? '');
	const workerById = (id: string) => data.workerSettings.find((worker: { id: string }) => worker.id === id);
	const configuredSecrets = () =>
		data.enrichmentSecretDefinitions.filter((secret: { configured: boolean }) => secret.configured).length;
	const openClass = '[&::-webkit-details-marker]:hidden';
</script>

<svelte:head>
	<title>Memory Hub Settings</title>
</svelte:head>

<main class="dashboard-shell mx-auto flex max-w-4xl flex-col gap-4 px-4 py-6 sm:px-6 md:py-8 lg:px-0">
	<header class="space-y-1">
		<p class="section-kicker">Memory Hub</p>
		<h1 class="section-title text-surface-50">Settings</h1>
	</header>

	{#if form?.message}
		<p class="text-sm text-surface-300" transition:fade>{form.message}</p>
	{/if}

	<Accordion multiple collapsible defaultValue={[]} class="w-full">
		<Accordion.Item value="enrichment" class="glass-panel overflow-hidden border border-white/10 bg-surface-950/35">
			<Accordion.ItemTrigger class="flex w-full items-center justify-between gap-4 px-5 py-4 text-left">
				<div class="min-w-0">
					<p class="text-xs uppercase tracking-[0.24em] text-surface-400">Enrichment</p>
					<h2 class="text-lg font-semibold text-surface-50">Tokens and model routing</h2>
					<p class="text-sm text-surface-400">
						{configuredSecrets()} of {data.enrichmentSecretDefinitions.length} tokens configured
					</p>
				</div>
				<span class="text-lg leading-none text-surface-400">⌄</span>
			</Accordion.ItemTrigger>

			<Accordion.ItemContent class="px-5 pb-5">
				<div class="grid gap-6 rounded-none border border-white/10 bg-white/5 p-4" transition:fade={{ duration: 160 }}>
					<section class="grid gap-3">
						{#each data.enrichmentSecretDefinitions as secret}
							<div class="rounded-none border border-white/10 bg-black/15 p-3">
								<div class="flex flex-wrap items-center justify-between gap-3">
									<div>
										<p class="font-medium text-surface-50">{secret.label}</p>
										<p class="text-xs text-surface-400">
											{secret.configured ? 'Present in live secrets' : 'Required for enrichment routing'}
										</p>
									</div>
									<span class={`badge ${secret.configured ? 'preset-tonal-success' : 'preset-tonal-warning'}`}>
										{secret.configured ? 'configured' : 'missing'}
									</span>
								</div>

								<form
									method="POST"
									action="?/secret"
									use:enhance={makeEnhancer(`secret-${secret.key}`)}
									class="mt-3 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_auto] md:items-end"
									aria-busy={actionBusy(`secret-${secret.key}`)}
								>
									<input type="hidden" name="key" value={secret.key} />
									<label class="label gap-2 md:min-w-0">
										<span class="label-text">Value</span>
										<input
											class="input preset-outlined-surface-200-800"
											type="password"
											name="value"
											autocomplete="new-password"
											placeholder={secret.configured ? 'Leave blank to keep the current value' : 'Enter value'}
										/>
									</label>

									<button class="btn preset-filled-primary-500" type="submit" disabled={actionBusy(`secret-${secret.key}`)}>
										{#if actionBusy(`secret-${secret.key}`)}
											<span class="loading-dot mr-2"></span>
											Saving
										{:else}
											Save
										{/if}
									</button>

									<button
										class="btn preset-tonal-error"
										type="submit"
										name="secret_action"
										value="delete"
										formnovalidate
										disabled={actionBusy(`secret-${secret.key}`)}
									>
										{#if actionBusy(`secret-${secret.key}`)}
											<span class="loading-dot mr-2"></span>
											Clearing
										{:else}
											Clear
										{/if}
									</button>
								</form>
							</div>
						{/each}
					</section>

					<section class="grid gap-3">
						<div class="flex items-center justify-between gap-3">
							<p class="font-medium text-surface-50">Enrichment tuning</p>
							<span class="badge preset-tonal-surface">{workerById('enrichment')?.fields.length ?? 0} settings</span>
						</div>

						{#if workerById('enrichment')}
							{@const enrichmentWorker = workerById('enrichment')!}
							<form
								method="POST"
								action="?/worker_settings"
								use:enhance={makeEnhancer('worker-enrichment')}
								class="grid gap-2 rounded-none border border-white/10 bg-black/15 p-3 sm:p-4"
								aria-busy={actionBusy('worker-enrichment')}
							>
								<input type="hidden" name="worker" value={enrichmentWorker.id} />
								{#each enrichmentWorker.fields as field}
									<div class="grid gap-2 border-t border-white/10 py-3 first:border-t-0 first:pt-0 sm:grid-cols-[minmax(0,1.2fr)_minmax(9rem,0.8fr)] sm:items-center sm:gap-4">
										<div class="min-w-0">
											<div class="flex flex-wrap items-center gap-2">
												<span class="label-text text-sm font-medium text-surface-50">{field.label}</span>
												<span class="badge preset-tonal-surface text-[10px] uppercase tracking-[0.18em]">
													{field.type === 'number' ? 'number' : 'choice'}
												</span>
											</div>
											<p class="text-xs text-surface-400">{field.description}</p>
										</div>
										<div class="justify-self-start sm:justify-self-end">
											{#if field.type === 'number'}
												<input
													class="input preset-outlined-surface-200-800 w-full max-w-32"
													type="number"
													name={field.key}
													value={enrichmentWorker.values[field.key]}
													min={field.min}
													max={field.max}
													required
												/>
											{:else}
												<select class="select preset-outlined-surface-200-800 w-full max-w-44" name={field.key}>
													{#each field.options ?? [] as option}
														<option value={option} selected={option === enrichmentWorker.values[field.key]}>{option}</option>
													{/each}
												</select>
											{/if}
										</div>
									</div>
								{/each}
								<div class="pt-1">
									<button class="btn preset-filled-primary-500" type="submit" disabled={actionBusy('worker-enrichment')}>
										{#if actionBusy('worker-enrichment')}
											<span class="loading-dot mr-2"></span>
											Saving
										{:else}
											Save enrichment
										{/if}
									</button>
								</div>
							</form>
						{/if}
					</section>
				</div>
			</Accordion.ItemContent>
		</Accordion.Item>

		<Accordion.Item value="email" class="glass-panel overflow-hidden border border-white/10 bg-surface-950/35">
			<Accordion.ItemTrigger class="flex w-full items-center justify-between gap-4 px-5 py-4 text-left">
				<div class="min-w-0">
					<p class="text-xs uppercase tracking-[0.24em] text-surface-400">Email</p>
					<h2 class="text-lg font-semibold text-surface-50">IMAP accounts</h2>
					<p class="text-sm text-surface-400">
						{data.emailAccounts.length} account{data.emailAccounts.length === 1 ? '' : 's'}
					</p>
				</div>
				<span class="text-lg leading-none text-surface-400">⌄</span>
			</Accordion.ItemTrigger>

			<Accordion.ItemContent class="px-5 pb-5">
				<div class="grid gap-3 rounded-none border border-white/10 bg-white/5 p-4" transition:fade={{ duration: 160 }}>
					<section class="grid gap-3">
						<p class="font-medium text-surface-50">Accounts</p>

						{#each data.emailAccounts as account}
							<details class="border-t border-white/10 pt-4 first:border-t-0 first:pt-0">
								<summary class={`flex cursor-pointer items-center justify-between gap-3 list-none ${openClass}`}>
									<div class="min-w-0">
										<p class="font-medium text-surface-50">{account.name}</p>
										<p class="truncate text-sm text-surface-400">{account.host} · {account.user}</p>
									</div>
									<span class="badge preset-tonal-surface">Edit</span>
								</summary>

								<form
									method="POST"
									action="?/email_account"
									use:enhance={makeEnhancer(`email-${account.name}`)}
									class="mt-4 grid gap-3"
									aria-busy={actionBusy(`email-${account.name}`)}
								>
									<input type="hidden" name="mode" value="save" />
									<input type="hidden" name="original_name" value={account.name} />

									<label class="label gap-2">
										<span class="label-text">Name</span>
										<input class="input preset-outlined-surface-200-800" name="name" value={account.name} />
									</label>
									<label class="label gap-2">
										<span class="label-text">Host</span>
										<input class="input preset-outlined-surface-200-800" name="host" value={account.host} />
									</label>
									<label class="label gap-2">
										<span class="label-text">User</span>
										<input class="input preset-outlined-surface-200-800" name="user" value={account.user} />
									</label>
									<label class="label gap-2">
										<span class="label-text">Password</span>
										<input
											class="input preset-outlined-surface-200-800"
											type="password"
											name="password"
											placeholder="Leave blank to keep the current value"
										/>
									</label>
									<label class="label gap-2">
										<span class="label-text">Folder filter</span>
										<input
											class="input preset-outlined-surface-200-800"
											name="folder"
											value={account.folder ?? ''}
											placeholder="Optional IMAP folder"
										/>
									</label>

									<div class="flex flex-wrap gap-2">
										<button class="btn preset-filled-primary-500" type="submit" disabled={actionBusy(`email-${account.name}`)}>
											{#if actionBusy(`email-${account.name}`)}
												<span class="loading-dot mr-2"></span>
												Saving
											{:else}
												Save
											{/if}
										</button>
										<button
											class="btn preset-tonal-error"
											type="submit"
											name="mode"
											value="delete"
											formnovalidate
											disabled={actionBusy(`email-${account.name}`)}
										>
											{#if actionBusy(`email-${account.name}`)}
												<span class="loading-dot mr-2"></span>
												Removing
											{:else}
												Remove
											{/if}
										</button>
									</div>
								</form>
							</details>
						{/each}

						<details class="border-t border-white/10 pt-4">
							<summary class={`flex cursor-pointer items-center justify-between gap-3 list-none ${openClass}`}>
								<div class="min-w-0">
									<p class="font-medium text-surface-50">Add account</p>
									<p class="text-sm text-surface-400">New IMAP mailbox</p>
								</div>
								<span class="badge preset-tonal-surface">New</span>
							</summary>

							<form
								method="POST"
								action="?/email_account"
								use:enhance={makeEnhancer('email-add')}
								class="mt-4 grid gap-3"
								aria-busy={actionBusy('email-add')}
							>
								<input type="hidden" name="mode" value="save" />
								<input type="hidden" name="original_name" value="" />

								<label class="label gap-2">
									<span class="label-text">Name</span>
									<input class="input preset-outlined-surface-200-800" name="name" placeholder="Work mailbox" />
								</label>
								<label class="label gap-2">
									<span class="label-text">Host</span>
									<input class="input preset-outlined-surface-200-800" name="host" placeholder="imap.example.com" />
								</label>
								<label class="label gap-2">
									<span class="label-text">User</span>
									<input class="input preset-outlined-surface-200-800" name="user" placeholder="you@example.com" />
								</label>
								<label class="label gap-2">
									<span class="label-text">Password</span>
									<input
										class="input preset-outlined-surface-200-800"
										type="password"
										name="password"
										placeholder="App password or token"
									/>
								</label>
								<label class="label gap-2">
									<span class="label-text">Folder filter</span>
									<input
										class="input preset-outlined-surface-200-800"
										name="folder"
										placeholder="Optional IMAP folder"
									/>
								</label>

								<button class="btn preset-filled-primary-500 justify-self-start" type="submit" disabled={actionBusy('email-add')}>
									{#if actionBusy('email-add')}
										<span class="loading-dot mr-2"></span>
										Adding
									{:else}
										Add account
									{/if}
								</button>
							</form>
						</details>
					</section>
				</div>
			</Accordion.ItemContent>
		</Accordion.Item>

		<Accordion.Item value="sources" class="glass-panel overflow-hidden border border-white/10 bg-surface-950/35">
			<Accordion.ItemTrigger class="flex w-full items-center justify-between gap-4 px-5 py-4 text-left">
				<div class="min-w-0">
					<p class="text-xs uppercase tracking-[0.24em] text-surface-400">Sources</p>
					<h2 class="text-lg font-semibold text-surface-50">GitHub, Obsidian, documents</h2>
					<p class="text-sm text-surface-400">Source accounts and filesystem paths</p>
				</div>
				<span class="text-lg leading-none text-surface-400">⌄</span>
			</Accordion.ItemTrigger>

			<Accordion.ItemContent class="px-5 pb-5">
				<div class="grid gap-6 rounded-none border border-white/10 bg-white/5 p-4" transition:fade={{ duration: 160 }}>
					<section class="grid gap-4 border-t border-white/10 pt-4">
						<div class="flex items-center justify-between gap-3">
							<div>
								<p class="font-medium text-surface-50">GitHub access token</p>
								<p class="text-sm text-surface-400">Used by the GitHub ingestion worker.</p>
							</div>
							<span class={`badge ${data.sourceSecretDefinitions[0]?.configured ? 'preset-tonal-success' : 'preset-tonal-warning'}`}>
								{data.sourceSecretDefinitions[0]?.configured ? 'configured' : 'missing'}
							</span>
						</div>

						{#if data.sourceSecretDefinitions[0]}
							{@const githubSecret = data.sourceSecretDefinitions[0]}
							<form
								method="POST"
								action="?/secret"
								use:enhance={makeEnhancer('secret-github')}
								class="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto_auto]"
								aria-busy={actionBusy('secret-github')}
							>
								<input type="hidden" name="key" value={githubSecret.key} />
								<label class="label gap-2 sm:col-span-1">
									<span class="label-text">Value</span>
									<input
										class="input preset-outlined-surface-200-800"
										type="password"
										name="value"
										autocomplete="new-password"
										placeholder={githubSecret.configured ? 'Leave blank to keep the current value' : 'Enter token'}
									/>
								</label>
								<button
									class="btn preset-filled-primary-500 self-end"
									type="submit"
									disabled={actionBusy('secret-github')}
								>
									{#if actionBusy('secret-github')}
										<span class="loading-dot mr-2"></span>
										Saving
									{:else}
										Save
									{/if}
								</button>
								<button
									class="btn preset-tonal-error self-end"
									type="submit"
									name="secret_action"
									value="delete"
									formnovalidate
									disabled={actionBusy('secret-github')}
								>
									{#if actionBusy('secret-github')}
										<span class="loading-dot mr-2"></span>
										Clearing
									{:else}
										Clear
									{/if}
								</button>
							</form>
						{/if}
					</section>

					<section class="grid gap-4 border-t border-white/10 pt-4">
						<div class="flex items-center justify-between gap-3">
							<div>
								<p class="font-medium text-surface-50">Documents</p>
								<p class="text-sm text-surface-400">{data.documentSettings.source_paths.length} source path{data.documentSettings.source_paths.length === 1 ? '' : 's'}</p>
							</div>
							<span class="badge preset-tonal-surface">Browse</span>
						</div>

						<div class="grid gap-3">
							{#each data.documentSettings.source_paths as source}
								<form
									method="POST"
									action="?/document_source_remove"
									use:enhance={makeEnhancer(`remove-source-${source}`)}
									class="flex items-center justify-between gap-3"
									aria-busy={actionBusy(`remove-source-${source}`)}
								>
									<input type="hidden" name="path" value={source} />
									<span class="min-w-0 truncate text-sm text-surface-200">{source}</span>
									<button
										class="btn btn-sm preset-tonal-error"
										type="submit"
										title="Remove source"
										disabled={actionBusy(`remove-source-${source}`)}
									>
										{#if actionBusy(`remove-source-${source}`)}
											<span class="loading-dot mr-2"></span>
											Removing
										{:else}
											Remove
										{/if}
									</button>
								</form>
							{/each}
						</div>

						<div class="grid gap-3 border-t border-white/10 pt-4">
							<div class="flex items-center justify-between gap-3">
								<div class="min-w-0">
									<p class="font-medium text-surface-50">Filesystem browser</p>
									<p class="text-sm text-surface-400">Browse {data.documentBrowser.rootPath}</p>
								</div>
								<a class="btn btn-sm preset-tonal-surface" href={data.documentBrowser.rootHref}>Root</a>
							</div>

							{#if data.documentBrowser.error}
								<p class="text-sm text-surface-400">{data.documentBrowser.error}</p>
							{/if}

							<div class="flex flex-wrap gap-2">
								{#each data.documentBrowser.breadcrumbs as crumb}
									<a class="btn btn-sm preset-tonal-surface" href={crumb.href}>{crumb.label}</a>
								{/each}
							</div>

							<div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
								{#each data.documentBrowser.entries as entry}
									<div class="grid gap-3 border border-white/10 bg-black/20 p-3">
										<div class="flex items-start justify-between gap-3">
											<div class="min-w-0">
												<p class="font-medium text-surface-50">{entry.name}</p>
												<p class="truncate text-xs text-surface-400">{entry.path}</p>
											</div>
											<a class="btn btn-sm preset-tonal-surface" href={entry.href}>Open</a>
										</div>
										<form
											method="POST"
											action="?/document_source_add"
											use:enhance={makeEnhancer(`add-doc-${entry.path}`)}
											aria-busy={actionBusy(`add-doc-${entry.path}`)}
										>
											<input type="hidden" name="path" value={entry.path} />
											<button class="btn btn-sm preset-filled-primary-500 w-full" type="submit">
												Add path
											</button>
										</form>
									</div>
								{/each}
							</div>

							<form
								method="POST"
								action="?/document_source_add"
								use:enhance={makeEnhancer('add-source')}
								class="grid gap-3"
								aria-busy={actionBusy('add-source')}
							>
								<input type="hidden" name="path" value={data.documentBrowser.currentPath || '.'} />
								<button class="btn preset-filled-primary-500 justify-self-start" type="submit" disabled={actionBusy('add-source')}>
									{#if actionBusy('add-source')}
										<span class="loading-dot mr-2"></span>
										Adding
									{:else}
										Add current folder
									{/if}
								</button>
							</form>
						</div>
					</section>

					<section class="grid gap-4 border-t border-white/10 pt-4">
						<div class="flex items-center justify-between gap-3">
							<div>
								<p class="font-medium text-surface-50">Obsidian</p>
								<p class="text-sm text-surface-400">Vault path is set from the browser below.</p>
							</div>
							<span class="badge preset-tonal-surface">Browse</span>
						</div>

						<div class="grid gap-3">
							<div class="flex items-center justify-between gap-3">
								<p class="text-sm text-surface-400">
									Current vault: <span class="font-mono text-surface-100">{data.obsidianSettings.vault_path || 'root'}</span>
								</p>
								<form
								method="POST"
								action="?/obsidian_settings"
								use:enhance={makeEnhancer('obsidian-root')}
								aria-busy={actionBusy('obsidian-root')}
							>
								<input type="hidden" name="vault_path" value="." />
								<button class="btn btn-sm preset-tonal-surface" type="submit">Use root</button>
							</form>
							</div>

							{#if data.obsidianBrowser.error}
								<p class="text-sm text-surface-400">{data.obsidianBrowser.error}</p>
							{/if}

							<div class="flex flex-wrap gap-2">
								{#each data.obsidianBrowser.breadcrumbs as crumb}
									<a class="btn btn-sm preset-tonal-surface" href={crumb.href}>{crumb.label}</a>
								{/each}
							</div>

							<div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
								{#each data.obsidianBrowser.entries as entry}
									<div class="grid gap-3 border border-white/10 bg-black/20 p-3">
										<div class="flex items-start justify-between gap-3">
											<div class="min-w-0">
												<p class="font-medium text-surface-50">{entry.name}</p>
												<p class="truncate text-xs text-surface-400">{entry.path}</p>
											</div>
											<a class="btn btn-sm preset-tonal-surface" href={entry.href}>Open</a>
										</div>
										<form
											method="POST"
											action="?/obsidian_settings"
											use:enhance={makeEnhancer(`obsidian-${entry.path}`)}
											aria-busy={actionBusy(`obsidian-${entry.path}`)}
										>
											<input type="hidden" name="vault_path" value={entry.path} />
											<button class="btn btn-sm preset-filled-primary-500 w-full" type="submit">
												Use vault
											</button>
										</form>
									</div>
								{/each}
							</div>

							<form
								method="POST"
								action="?/obsidian_settings"
								use:enhance={makeEnhancer('obsidian-current')}
								class="grid gap-3"
								aria-busy={actionBusy('obsidian-current')}
							>
								<input type="hidden" name="vault_path" value={data.obsidianBrowser.currentPath || '.'} />
								<button class="btn preset-filled-primary-500 justify-self-start" type="submit" disabled={actionBusy('obsidian-current')}>
									{#if actionBusy('obsidian-current')}
										<span class="loading-dot mr-2"></span>
										Saving
									{:else}
										Use current folder
									{/if}
								</button>
							</form>
						</div>
					</section>
				</div>
			</Accordion.ItemContent>
		</Accordion.Item>

		<Accordion.Item value="backup" class="glass-panel overflow-hidden border border-white/10 bg-surface-950/35">
			<Accordion.ItemTrigger class="flex w-full items-center justify-between gap-4 px-5 py-4 text-left">
				<div class="min-w-0">
					<p class="text-xs uppercase tracking-[0.24em] text-surface-400">Backup</p>
					<h2 class="text-lg font-semibold text-surface-50">Kopia</h2>
					<p class="text-sm text-surface-400">Latest backup metadata</p>
				</div>
				<span class="text-lg leading-none text-surface-400">⌄</span>
			</Accordion.ItemTrigger>

			<Accordion.ItemContent class="px-5 pb-5">
				{#if data.backupManifest}
					<div class="grid gap-2" transition:fade={{ duration: 160 }}>
						{#each Object.entries(data.backupManifest) as [key, value]}
							<div class="flex items-center justify-between gap-3 border-t border-white/10 pt-3 first:border-t-0 first:pt-0">
								<span class="text-sm text-surface-400">{key}</span>
								<span class="truncate font-mono text-sm text-surface-100">{String(value)}</span>
							</div>
						{/each}
					</div>
				{:else}
					<p class="text-sm text-surface-400">No backup manifest yet.</p>
				{/if}
			</Accordion.ItemContent>
		</Accordion.Item>
	</Accordion>
</main>
