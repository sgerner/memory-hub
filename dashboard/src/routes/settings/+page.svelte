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
	const configuredSecrets = () => data.secretDefinitions.filter((secret: { configured: boolean }) => secret.configured).length;
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
		<Accordion.Item value="enrichment" class="border-b border-white/10">
			<Accordion.ItemTrigger class="flex w-full items-center justify-between gap-4 py-4 text-left">
				<div class="min-w-0">
					<p class="text-xs uppercase tracking-[0.24em] text-surface-400">Enrichment</p>
					<h2 class="text-lg font-semibold text-surface-50">Secrets and model routing</h2>
					<p class="text-sm text-surface-400">
						{configuredSecrets()} of {data.secretDefinitions.length} secrets configured
					</p>
				</div>
				<span class="text-lg leading-none text-surface-400">⌄</span>
			</Accordion.ItemTrigger>

			<Accordion.ItemContent class="pb-6">
				<div class="grid gap-6">
					<section class="grid gap-4">
						{#each data.secretDefinitions as secret}
							<div class="grid gap-3 border-t border-white/10 pt-4 first:border-t-0 first:pt-0">
								<div class="flex items-center justify-between gap-3">
									<p class="font-medium text-surface-50">{secret.label}</p>
									<span class={`badge ${secret.configured ? 'preset-tonal-success' : 'preset-tonal-warning'}`}>
										{secret.configured ? 'configured' : 'missing'}
									</span>
								</div>

								<form
									method="POST"
									action="?/secret"
									use:enhance={makeEnhancer(`secret-${secret.key}`)}
									class="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto_auto]"
									aria-busy={actionBusy(`secret-${secret.key}`)}
								>
									<input type="hidden" name="key" value={secret.key} />
									<label class="label gap-2 sm:col-span-1">
										<span class="label-text">Value</span>
										<input
											class="input preset-outlined-surface-200-800"
											type="password"
											name="value"
											autocomplete="new-password"
											placeholder={secret.configured ? 'Leave blank to keep the current value' : 'Enter value'}
										/>
									</label>

									<button
										class="btn preset-filled-primary-500 self-end"
										type="submit"
										disabled={actionBusy(`secret-${secret.key}`)}
									>
										{#if actionBusy(`secret-${secret.key}`)}
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

					<section class="grid gap-4 border-t border-white/10 pt-4">
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
								class="grid gap-4"
								aria-busy={actionBusy('worker-enrichment')}
							>
								<input type="hidden" name="worker" value={enrichmentWorker.id} />
								{#each enrichmentWorker.fields as field}
									<label class="label gap-2">
										<span class="label-text">{field.label}</span>
										{#if field.type === 'number'}
											<input
												class="input preset-outlined-surface-200-800"
												type="number"
												name={field.key}
												value={enrichmentWorker.values[field.key]}
												min={field.min}
												max={field.max}
												required
											/>
										{:else}
											<select class="select preset-outlined-surface-200-800" name={field.key}>
												{#each field.options ?? [] as option}
													<option value={option} selected={option === enrichmentWorker.values[field.key]}>{option}</option>
												{/each}
											</select>
										{/if}
										<span class="text-xs text-surface-400">{field.description}</span>
									</label>
								{/each}
								<button
									class="btn preset-filled-primary-500 justify-self-start"
									type="submit"
									disabled={actionBusy('worker-enrichment')}
								>
									{#if actionBusy('worker-enrichment')}
										<span class="loading-dot mr-2"></span>
										Saving
									{:else}
										Save enrichment
									{/if}
								</button>
							</form>
						{/if}
					</section>
				</div>
			</Accordion.ItemContent>
		</Accordion.Item>

		<Accordion.Item value="email" class="border-b border-white/10">
			<Accordion.ItemTrigger class="flex w-full items-center justify-between gap-4 py-4 text-left">
				<div class="min-w-0">
					<p class="text-xs uppercase tracking-[0.24em] text-surface-400">Email</p>
					<h2 class="text-lg font-semibold text-surface-50">IMAP accounts</h2>
					<p class="text-sm text-surface-400">
						{data.emailAccounts.length} account{data.emailAccounts.length === 1 ? '' : 's'}
					</p>
				</div>
				<span class="text-lg leading-none text-surface-400">⌄</span>
			</Accordion.ItemTrigger>

			<Accordion.ItemContent class="pb-6">
				<div class="grid gap-6">
					<section class="grid gap-4">
						<div class="flex items-center justify-between gap-3">
							<p class="font-medium text-surface-50">IMAP tuning</p>
							<span class="badge preset-tonal-surface">{workerById('email')?.fields.length ?? 0} settings</span>
						</div>

						{#if workerById('email')}
							{@const emailWorker = workerById('email')!}
							<form
								method="POST"
								action="?/worker_settings"
								use:enhance={makeEnhancer('worker-email')}
								class="grid gap-4"
								aria-busy={actionBusy('worker-email')}
							>
								<input type="hidden" name="worker" value={emailWorker.id} />
								{#each emailWorker.fields as field}
									<label class="label gap-2">
										<span class="label-text">{field.label}</span>
										{#if field.type === 'number'}
											<input
												class="input preset-outlined-surface-200-800"
												type="number"
												name={field.key}
												value={emailWorker.values[field.key]}
												min={field.min}
												max={field.max}
												required
											/>
										{:else}
											<select class="select preset-outlined-surface-200-800" name={field.key}>
												{#each field.options ?? [] as option}
													<option value={option} selected={option === emailWorker.values[field.key]}>{option}</option>
												{/each}
											</select>
										{/if}
										<span class="text-xs text-surface-400">{field.description}</span>
									</label>
								{/each}
								<button
									class="btn preset-filled-primary-500 justify-self-start"
									type="submit"
									disabled={actionBusy('worker-email')}
								>
									{#if actionBusy('worker-email')}
										<span class="loading-dot mr-2"></span>
										Saving
									{:else}
										Save email
									{/if}
								</button>
							</form>
						{/if}
					</section>

					<section class="grid gap-3 border-t border-white/10 pt-4">
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

		<Accordion.Item value="sources" class="border-b border-white/10">
			<Accordion.ItemTrigger class="flex w-full items-center justify-between gap-4 py-4 text-left">
				<div class="min-w-0">
					<p class="text-xs uppercase tracking-[0.24em] text-surface-400">Sources</p>
					<h2 class="text-lg font-semibold text-surface-50">GitHub, Obsidian, documents</h2>
					<p class="text-sm text-surface-400">Worker settings and document paths</p>
				</div>
				<span class="text-lg leading-none text-surface-400">⌄</span>
			</Accordion.ItemTrigger>

			<Accordion.ItemContent class="pb-6">
				<div class="grid gap-4">
					<details class="border-t border-white/10 pt-4">
						<summary class={`flex cursor-pointer items-center justify-between gap-3 list-none ${openClass}`}>
							<div class="min-w-0">
								<p class="font-medium text-surface-50">GitHub</p>
								<p class="text-sm text-surface-400">Set `github_token` in Enrichment</p>
							</div>
							<span class="badge preset-tonal-surface">Edit</span>
						</summary>

						{#if workerById('github')}
							{@const githubWorker = workerById('github')!}
							<form
								method="POST"
								action="?/worker_settings"
								use:enhance={makeEnhancer('worker-github')}
								class="mt-4 grid gap-4"
								aria-busy={actionBusy('worker-github')}
							>
								<input type="hidden" name="worker" value={githubWorker.id} />
								{#each githubWorker.fields as field}
									<label class="label gap-2">
										<span class="label-text">{field.label}</span>
										{#if field.type === 'number'}
											<input
												class="input preset-outlined-surface-200-800"
												type="number"
												name={field.key}
												value={githubWorker.values[field.key]}
												min={field.min}
												max={field.max}
												required
											/>
										{:else}
											<select class="select preset-outlined-surface-200-800" name={field.key}>
												{#each field.options ?? [] as option}
													<option value={option} selected={option === githubWorker.values[field.key]}>{option}</option>
												{/each}
											</select>
										{/if}
										<span class="text-xs text-surface-400">{field.description}</span>
									</label>
								{/each}
								<button
									class="btn preset-filled-primary-500 justify-self-start"
									type="submit"
									disabled={actionBusy('worker-github')}
								>
									{#if actionBusy('worker-github')}
										<span class="loading-dot mr-2"></span>
										Saving
									{:else}
										Save GitHub
									{/if}
								</button>
							</form>
						{/if}
					</details>

					<details class="border-t border-white/10 pt-4">
						<summary class={`flex cursor-pointer items-center justify-between gap-3 list-none ${openClass}`}>
							<div class="min-w-0">
								<p class="font-medium text-surface-50">Obsidian</p>
								<p class="text-sm text-surface-400">Vault path and poll cadence</p>
							</div>
							<span class="badge preset-tonal-surface">Edit</span>
						</summary>

						{#if workerById('obsidian')}
							{@const obsidianWorker = workerById('obsidian')!}
							<form
								method="POST"
								action="?/worker_settings"
								use:enhance={makeEnhancer('worker-obsidian')}
								class="mt-4 grid gap-4"
								aria-busy={actionBusy('worker-obsidian')}
							>
								<input type="hidden" name="worker" value={obsidianWorker.id} />
								{#each obsidianWorker.fields as field}
									<label class="label gap-2">
										<span class="label-text">{field.label}</span>
										{#if field.type === 'number'}
											<input
												class="input preset-outlined-surface-200-800"
												type="number"
												name={field.key}
												value={obsidianWorker.values[field.key]}
												min={field.min}
												max={field.max}
												required
											/>
										{:else}
											<select class="select preset-outlined-surface-200-800" name={field.key}>
												{#each field.options ?? [] as option}
													<option value={option} selected={option === obsidianWorker.values[field.key]}>{option}</option>
												{/each}
											</select>
										{/if}
										<span class="text-xs text-surface-400">{field.description}</span>
									</label>
								{/each}
								<button
									class="btn preset-filled-primary-500 justify-self-start"
									type="submit"
									disabled={actionBusy('worker-obsidian')}
								>
									{#if actionBusy('worker-obsidian')}
										<span class="loading-dot mr-2"></span>
										Saving
									{:else}
										Save Obsidian
									{/if}
								</button>
							</form>
						{/if}
					</details>

					<details class="border-t border-white/10 pt-4">
						<summary class={`flex cursor-pointer items-center justify-between gap-3 ${openClass}`}>
							<div class="min-w-0">
								<p class="font-medium text-surface-50">Documents</p>
								<p class="text-sm text-surface-400">{data.documentSettings.source_paths.length} source path{data.documentSettings.source_paths.length === 1 ? '' : 's'}</p>
							</div>
							<span class="badge preset-tonal-surface">Edit</span>
						</summary>

						{#if workerById('documents')}
							{@const documentsWorker = workerById('documents')!}
							<form
								method="POST"
								action="?/worker_settings"
								use:enhance={makeEnhancer('worker-documents')}
								class="mt-4 grid gap-4"
								aria-busy={actionBusy('worker-documents')}
							>
								<input type="hidden" name="worker" value={documentsWorker.id} />
								{#each documentsWorker.fields as field}
									<label class="label gap-2">
										<span class="label-text">{field.label}</span>
										{#if field.type === 'number'}
											<input
												class="input preset-outlined-surface-200-800"
												type="number"
												name={field.key}
												value={documentsWorker.values[field.key]}
												min={field.min}
												max={field.max}
												required
											/>
										{:else}
											<select class="select preset-outlined-surface-200-800" name={field.key}>
												{#each field.options ?? [] as option}
													<option value={option} selected={option === documentsWorker.values[field.key]}>{option}</option>
												{/each}
											</select>
										{/if}
										<span class="text-xs text-surface-400">{field.description}</span>
									</label>
								{/each}
								<button
									class="btn preset-filled-primary-500 justify-self-start"
									type="submit"
									disabled={actionBusy('worker-documents')}
								>
									{#if actionBusy('worker-documents')}
										<span class="loading-dot mr-2"></span>
										Saving
									{:else}
										Save documents
									{/if}
								</button>
							</form>
						{/if}

						<details class="mt-4 border-t border-white/10 pt-4">
							<summary class={`flex cursor-pointer items-center justify-between gap-3 list-none ${openClass}`}>
								<div class="min-w-0">
									<p class="font-medium text-surface-50">Document paths</p>
									<p class="text-sm text-surface-400">Add or remove mounted sources</p>
								</div>
								<span class="badge preset-tonal-surface">Manage</span>
							</summary>

							<div class="mt-4 grid gap-3">
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

							<form
								method="POST"
								action="?/document_source_add"
								use:enhance={makeEnhancer('add-source')}
								class="mt-4 grid gap-3"
								aria-busy={actionBusy('add-source')}
							>
								<label class="label gap-2">
									<span class="label-text">Source path</span>
									<input
										class="input preset-outlined-surface-200-800"
										name="path"
										placeholder="gdrive/photos or another mounted source"
									/>
								</label>
								<button class="btn preset-filled-primary-500 justify-self-start" type="submit" disabled={actionBusy('add-source')}>
									{#if actionBusy('add-source')}
										<span class="loading-dot mr-2"></span>
										Adding
									{:else}
										Add source
									{/if}
								</button>
							</form>
						</details>
					</details>
				</div>
			</Accordion.ItemContent>
		</Accordion.Item>

		<Accordion.Item value="backup" class="border-b border-white/10">
			<Accordion.ItemTrigger class="flex w-full items-center justify-between gap-4 py-4 text-left">
				<div class="min-w-0">
					<p class="text-xs uppercase tracking-[0.24em] text-surface-400">Backup</p>
					<h2 class="text-lg font-semibold text-surface-50">Kopia</h2>
					<p class="text-sm text-surface-400">Latest backup metadata</p>
				</div>
				<span class="text-lg leading-none text-surface-400">⌄</span>
			</Accordion.ItemTrigger>

			<Accordion.ItemContent class="pb-6">
				{#if data.backupManifest}
					<div class="grid gap-2">
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
