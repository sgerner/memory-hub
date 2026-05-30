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
				try { await update(); } finally { pendingAction = null; }
			};
		};
	};

	const actionBusy = (...actions: string[]) => actions.includes(pendingAction ?? '');
	const workerById = (id: string) => data.workerSettings.find((w: { id: string }) => w.id === id);
	const configuredSecrets = () =>
		data.enrichmentSecretDefinitions.filter((s: { configured: boolean }) => s.configured).length;
</script>

<svelte:head>
	<title>Settings — Memory Hub</title>
</svelte:head>

<main class="shell pb-24 pt-8 md:pt-12 max-w-3xl">

	<div class="mb-10">
		<p class="section-label mb-1">System</p>
		<h1 class="text-2xl font-bold text-surface-50">Settings</h1>
	</div>

	{#if form?.message}
		<div class="font-mono text-xs text-primary-300 border border-primary-400/20 bg-primary-900/10 px-4 py-3 mb-8" transition:fade>
			<span class="opacity-50 mr-2">→</span>{form.message}
		</div>
	{/if}

	<Accordion multiple collapsible defaultValue={[]}>

		<!-- ── Section 1: Enrichment ────────────────────────────────────── -->
		<Accordion.Item value="enrichment" class="settings-section">
			<Accordion.ItemTrigger class="settings-trigger">
				<div>
					<p class="settings-tag text-primary-400">Enrichment</p>
					<p class="settings-title">Tokens & Routing</p>
					<p class="settings-meta">{configuredSecrets()} of {data.enrichmentSecretDefinitions.length} tokens active</p>
				</div>
				<svg class="w-4 h-4 text-surface-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="square" stroke-linejoin="miter" stroke-width="1.5" d="M19 9l-7 7-7-7"/></svg>
			</Accordion.ItemTrigger>

			<Accordion.ItemContent>
				<div class="pb-8 space-y-8" transition:fade={{ duration: 160 }}>

					<!-- API Tokens -->
					<div>
						<p class="field-label mb-4">API Tokens</p>
						<div class="divide-y" style="border-top: 1px solid var(--border-dim)">
							{#each data.enrichmentSecretDefinitions as secret}
								<div class="py-5">
									<div class="flex flex-wrap items-center justify-between gap-2 mb-4">
										<div>
											<p class="text-sm font-semibold text-surface-100">{secret.label}</p>
											<p class="font-mono text-[0.65rem] text-surface-500 mt-0.5">{secret.description}</p>
										</div>
										<span class="status-pill {secret.configured ? 'active' : 'archived'}">
											{secret.configured ? 'active' : 'missing'}
										</span>
									</div>
									<form
										method="POST"
										action="?/secret"
										use:enhance={makeEnhancer(`secret-${secret.key}`)}
										class="flex flex-wrap gap-2 items-end"
										aria-busy={actionBusy(`secret-${secret.key}`)}
									>
										<input type="hidden" name="key" value={secret.key} />
										<div class="flex-1 min-w-48">
											<label class="field-label" for="secret-{secret.key}">New value</label>
											<input
												id="secret-{secret.key}"
												class="field-input"
												type="password"
												name="value"
												autocomplete="new-password"
												placeholder={secret.configured ? '••••••••••••••••' : 'Enter API token…'}
											/>
										</div>
										<button class="btn-primary" type="submit" disabled={actionBusy(`secret-${secret.key}`)}>
											{actionBusy(`secret-${secret.key}`) ? '…' : 'save'}
										</button>
										<button class="ghost-btn danger" type="submit" name="secret_action" value="delete" formnovalidate
											disabled={actionBusy(`secret-${secret.key}`)}>
											clear
										</button>
									</form>
								</div>
							{/each}
						</div>
					</div>

					<!-- Enrichment Worker Parameters -->
					{#if workerById('enrichment')}
						{@const enrichmentWorker = workerById('enrichment')!}
						<div class="border-t pt-6" style="border-color: var(--border-dim)">
							<p class="field-label mb-4">Enrichment Parameters</p>
							<form
								method="POST"
								action="?/worker_settings"
								use:enhance={makeEnhancer('worker-enrichment')}
								class="space-y-4"
								aria-busy={actionBusy('worker-enrichment')}
							>
								<input type="hidden" name="worker" value={enrichmentWorker.id} />
								{#each enrichmentWorker.fields as field}
									<div class="flex flex-wrap items-center justify-between gap-3 py-3 border-b" style="border-color: var(--border-dim)">
										<div>
											<p class="text-sm font-medium text-surface-200">{field.label}</p>
											<p class="font-mono text-[0.62rem] text-surface-500 mt-0.5">{field.description}</p>
										</div>
										<div>
											{#if field.type === 'number'}
												<input
													class="field-input w-24 text-center"
													type="number"
													name={field.key}
													value={enrichmentWorker.values[field.key]}
													min={field.min}
													max={field.max}
													required
												/>
											{:else}
												<select class="field-select w-40" name={field.key}>
													{#each field.options ?? [] as option}
														<option value={option} selected={option === enrichmentWorker.values[field.key]}>{option}</option>
													{/each}
												</select>
											{/if}
										</div>
									</div>
								{/each}
								<div class="flex justify-end pt-2">
									<button class="btn-primary" type="submit" disabled={actionBusy('worker-enrichment')}>
										{actionBusy('worker-enrichment') ? '…' : 'save parameters'}
									</button>
								</div>
							</form>
						</div>
					{/if}

				</div>
			</Accordion.ItemContent>
		</Accordion.Item>

		<!-- ── Section 2: Email ──────────────────────────────────────────── -->
		<Accordion.Item value="email" class="settings-section">
			<Accordion.ItemTrigger class="settings-trigger">
				<div>
					<p class="settings-tag text-secondary-400">Email Ingestion</p>
					<p class="settings-title">IMAP Accounts</p>
					<p class="settings-meta">{data.emailAccounts.length} account{data.emailAccounts.length === 1 ? '' : 's'} configured</p>
				</div>
				<svg class="w-4 h-4 text-surface-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="square" stroke-linejoin="miter" stroke-width="1.5" d="M19 9l-7 7-7-7"/></svg>
			</Accordion.ItemTrigger>

			<Accordion.ItemContent>
				<div class="pb-8 space-y-0" transition:fade={{ duration: 160 }}>
					{#each data.emailAccounts as account}
						<details class="border-b group" style="border-color: var(--border-dim)">
							<summary class="flex cursor-pointer list-none items-center justify-between gap-4 py-4 [&::-webkit-details-marker]:hidden">
								<div>
									<p class="text-sm font-semibold text-surface-100">{account.name}</p>
									<p class="font-mono text-[0.62rem] text-surface-500 mt-0.5">{account.host} · {account.user}</p>
								</div>
								<span class="ghost-btn">configure</span>
							</summary>
							<form
								method="POST"
								action="?/email_account"
								use:enhance={makeEnhancer(`email-${account.name}`)}
								class="pb-5 grid gap-4"
								aria-busy={actionBusy(`email-${account.name}`)}
							>
								<input type="hidden" name="mode" value="save" />
								<input type="hidden" name="original_name" value={account.name} />
								<div class="grid gap-3 sm:grid-cols-2">
									<div><label class="field-label" for="ename-{account.name}">Account Name</label><input id="ename-{account.name}" class="field-input" name="name" value={account.name} required /></div>
									<div><label class="field-label" for="ehost-{account.name}">IMAP Host</label><input id="ehost-{account.name}" class="field-input" name="host" value={account.host} required /></div>
									<div><label class="field-label" for="euser-{account.name}">Username</label><input id="euser-{account.name}" class="field-input" name="user" value={account.user} required /></div>
									<div><label class="field-label" for="efolder-{account.name}">Folder Filter</label><input id="efolder-{account.name}" class="field-input" name="folder" value={account.folder ?? ''} placeholder="INBOX" /></div>
								</div>
								<div><label class="field-label" for="epw-{account.name}">Password</label><input id="epw-{account.name}" class="field-input" type="password" name="password" placeholder="Leave blank to keep existing…" /></div>
								<div class="flex gap-2 justify-end pt-1">
									<button class="btn-primary" type="submit" disabled={actionBusy(`email-${account.name}`)}>
										{actionBusy(`email-${account.name}`) ? '…' : 'save account'}
									</button>
									<button class="ghost-btn danger" type="submit" name="mode" value="delete" formnovalidate disabled={actionBusy(`email-${account.name}`)}>remove</button>
								</div>
							</form>
						</details>
					{/each}

					<!-- Add Account -->
					<details class="group pt-2">
						<summary class="flex cursor-pointer list-none items-center gap-3 py-3 [&::-webkit-details-marker]:hidden">
							<span class="section-label">Add IMAP account</span>
							<svg class="w-3.5 h-3.5 text-surface-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="square" stroke-linejoin="miter" stroke-width="2" d="M12 5v14m-7-7h14"/></svg>
						</summary>
						<form
							method="POST"
							action="?/email_account"
							use:enhance={makeEnhancer('email-add')}
							class="mt-3 pb-5 grid gap-4"
							aria-busy={actionBusy('email-add')}
						>
							<input type="hidden" name="mode" value="save" />
							<input type="hidden" name="original_name" value="" />
							<div class="grid gap-3 sm:grid-cols-2">
								<div><label class="field-label" for="new-ename">Account Name</label><input id="new-ename" class="field-input" name="name" placeholder="Work Mailbox" required /></div>
								<div><label class="field-label" for="new-ehost">IMAP Host</label><input id="new-ehost" class="field-input" name="host" placeholder="imap.example.com" required /></div>
								<div><label class="field-label" for="new-euser">Username</label><input id="new-euser" class="field-input" name="user" placeholder="you@example.com" required /></div>
								<div><label class="field-label" for="new-efolder">Folder Filter</label><input id="new-efolder" class="field-input" name="folder" placeholder="INBOX" /></div>
							</div>
							<div><label class="field-label" for="new-epw">Password</label><input id="new-epw" class="field-input" type="password" name="password" placeholder="App password or token…" required /></div>
							<div class="flex justify-end pt-1">
								<button class="btn-primary" type="submit" disabled={actionBusy('email-add')}>
									{actionBusy('email-add') ? '…' : 'add mailbox'}
								</button>
							</div>
						</form>
					</details>
				</div>
			</Accordion.ItemContent>
		</Accordion.Item>

		<!-- ── Section 3: Sources ────────────────────────────────────────── -->
		<Accordion.Item value="sources" class="settings-section">
			<Accordion.ItemTrigger class="settings-trigger">
				<div>
					<p class="settings-tag text-tertiary-400">File Ingestion</p>
					<p class="settings-title">Local Vaults & GitHub</p>
					<p class="settings-meta">Directories, notes, and repository tokens</p>
				</div>
				<svg class="w-4 h-4 text-surface-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="square" stroke-linejoin="miter" stroke-width="1.5" d="M19 9l-7 7-7-7"/></svg>
			</Accordion.ItemTrigger>

			<Accordion.ItemContent>
				<div class="pb-8 space-y-8" transition:fade={{ duration: 160 }}>

					<!-- GitHub Token -->
					{#if data.sourceSecretDefinitions[0]}
						{@const gs = data.sourceSecretDefinitions[0]}
						<div>
							<div class="flex items-center justify-between mb-4">
								<p class="field-label">GitHub Integration</p>
								<span class="status-pill {gs.configured ? 'active' : 'archived'}">{gs.configured ? 'configured' : 'missing'}</span>
							</div>
							<form
								method="POST"
								action="?/secret"
								use:enhance={makeEnhancer('secret-github')}
								class="flex flex-wrap gap-2 items-end"
								aria-busy={actionBusy('secret-github')}
							>
								<input type="hidden" name="key" value={gs.key} />
								<div class="flex-1 min-w-48">
									<label class="field-label" for="gh-token">Personal access token</label>
									<input id="gh-token" class="field-input" type="password" name="value" autocomplete="new-password"
										placeholder={gs.configured ? '••••••••••••••••' : 'ghp_…'} />
								</div>
								<button class="btn-primary" type="submit" disabled={actionBusy('secret-github')}>
									{actionBusy('secret-github') ? '…' : 'save'}
								</button>
								<button class="ghost-btn danger" type="submit" name="secret_action" value="delete" formnovalidate disabled={actionBusy('secret-github')}>clear</button>
							</form>
						</div>
					{/if}

					<!-- Document Paths -->
					<div class="border-t pt-6" style="border-color: var(--border-dim)">
						<div class="flex items-center justify-between mb-3">
							<p class="field-label">Documents Ingestion</p>
							<span class="font-mono text-[0.6rem] text-surface-500">{data.documentSettings.source_paths.length} paths</span>
						</div>
						{#if data.documentSettings.source_paths.length > 0}
							<div class="mb-4">
								{#each data.documentSettings.source_paths as source}
									<form
										method="POST"
										action="?/document_source_remove"
										use:enhance={makeEnhancer(`remove-source-${source}`)}
										class="flex items-center justify-between py-2 border-b gap-4"
										style="border-color: var(--border-dim)"
										aria-busy={actionBusy(`remove-source-${source}`)}
									>
										<input type="hidden" name="path" value={source} />
										<span class="font-mono text-[0.7rem] text-surface-300 truncate">{source}</span>
										<button class="ghost-btn danger" type="submit" disabled={actionBusy(`remove-source-${source}`)}>
											{actionBusy(`remove-source-${source}`) ? '…' : 'remove'}
										</button>
									</form>
								{/each}
							</div>
						{/if}

						<!-- File Browser for Docs -->
						<div class="border" style="border-color: var(--border)">
							<div class="flex items-center justify-between px-4 py-3 border-b" style="border-color: var(--border-dim)">
								<div>
									<p class="font-mono text-[0.6rem] font-bold tracking-widest uppercase text-surface-400">File Explorer</p>
									<p class="font-mono text-[0.58rem] text-surface-600 mt-0.5">{data.documentBrowser.rootPath}</p>
								</div>
								<a class="ghost-btn" href={data.documentBrowser.rootHref}>root</a>
							</div>

							{#if data.documentBrowser.error}
								<p class="px-4 py-2 font-mono text-xs text-error-400">{data.documentBrowser.error}</p>
							{/if}

							<!-- Breadcrumbs -->
							<div class="flex flex-wrap items-center gap-1.5 px-4 py-2 border-b font-mono text-[0.6rem]" style="border-color: var(--border-dim)">
								{#each data.documentBrowser.breadcrumbs as crumb, idx}
									{#if idx > 0}<span class="text-surface-700">/</span>{/if}
									<a class="text-surface-400 hover:text-surface-100 transition-colors" href={crumb.href}>{crumb.label}</a>
								{/each}
							</div>

							<!-- Dir listing -->
							<div class="max-h-56 overflow-y-auto divide-y" style="border-color: var(--border-dim)">
								{#each data.documentBrowser.entries as entry}
									<div class="flex items-center justify-between px-4 py-2.5 gap-3 hover:bg-white/[0.01]">
										<span class="font-mono text-[0.68rem] text-surface-300 truncate">📁 {entry.name}</span>
										<div class="flex gap-1.5 shrink-0">
											<a class="ghost-btn" href={entry.href}>browse</a>
											<form method="POST" action="?/document_source_add" use:enhance={makeEnhancer(`add-doc-${entry.path}`)} aria-busy={actionBusy(`add-doc-${entry.path}`)}>
												<input type="hidden" name="path" value={entry.path} />
												<button class="btn-primary" type="submit" style="padding: 0.2rem 0.6rem; font-size: 0.58rem">add</button>
											</form>
										</div>
									</div>
								{/each}
							</div>

							<div class="px-4 py-3 flex justify-end border-t" style="border-color: var(--border-dim)">
								<form method="POST" action="?/document_source_add" use:enhance={makeEnhancer('add-source')} aria-busy={actionBusy('add-source')}>
									<input type="hidden" name="path" value={data.documentBrowser.currentPath || '.'} />
									<button class="btn-primary" type="submit" disabled={actionBusy('add-source')}>
										{actionBusy('add-source') ? '…' : 'add current directory'}
									</button>
								</form>
							</div>
						</div>
					</div>

					<!-- Obsidian -->
					<div class="border-t pt-6" style="border-color: var(--border-dim)">
						<div class="flex items-center justify-between mb-3">
							<p class="field-label">Obsidian Integration</p>
							<span class="font-mono text-[0.6rem] text-surface-500 truncate max-w-40">{data.obsidianSettings.vault_path || 'root'}</span>
						</div>

						<div class="flex items-center justify-between py-3 border-b mb-4" style="border-color: var(--border-dim)">
							<span class="font-mono text-[0.68rem] text-surface-400">Use root directory</span>
							<form method="POST" action="?/obsidian_settings" use:enhance={makeEnhancer('obsidian-root')} aria-busy={actionBusy('obsidian-root')}>
								<input type="hidden" name="vault_path" value="." />
								<button class="ghost-btn" type="submit">use root vault</button>
							</form>
						</div>

						<!-- Obsidian Browser -->
						<div class="border" style="border-color: var(--border)">
							<div class="flex items-center justify-between px-4 py-3 border-b" style="border-color: var(--border-dim)">
								<div>
									<p class="font-mono text-[0.6rem] font-bold tracking-widest uppercase text-surface-400">Vault Explorer</p>
									<p class="font-mono text-[0.58rem] text-surface-600 mt-0.5">{data.obsidianBrowser.rootPath}</p>
								</div>
								<a class="ghost-btn" href={data.obsidianBrowser.rootHref}>root</a>
							</div>

							{#if data.obsidianBrowser.error}
								<p class="px-4 py-2 font-mono text-xs text-error-400">{data.obsidianBrowser.error}</p>
							{/if}

							<div class="flex flex-wrap items-center gap-1.5 px-4 py-2 border-b font-mono text-[0.6rem]" style="border-color: var(--border-dim)">
								{#each data.obsidianBrowser.breadcrumbs as crumb, idx}
									{#if idx > 0}<span class="text-surface-700">/</span>{/if}
									<a class="text-surface-400 hover:text-surface-100 transition-colors" href={crumb.href}>{crumb.label}</a>
								{/each}
							</div>

							<div class="max-h-56 overflow-y-auto divide-y" style="border-color: var(--border-dim)">
								{#each data.obsidianBrowser.entries as entry}
									<div class="flex items-center justify-between px-4 py-2.5 gap-3 hover:bg-white/[0.01]">
										<span class="font-mono text-[0.68rem] text-surface-300 truncate">📁 {entry.name}</span>
										<div class="flex gap-1.5 shrink-0">
											<a class="ghost-btn" href={entry.href}>browse</a>
											<form method="POST" action="?/obsidian_settings" use:enhance={makeEnhancer(`obsidian-${entry.path}`)} aria-busy={actionBusy(`obsidian-${entry.path}`)}>
												<input type="hidden" name="vault_path" value={entry.path} />
												<button class="btn-primary" type="submit" style="padding: 0.2rem 0.6rem; font-size: 0.58rem">select</button>
											</form>
										</div>
									</div>
								{/each}
							</div>

							<div class="px-4 py-3 flex justify-end border-t" style="border-color: var(--border-dim)">
								<form method="POST" action="?/obsidian_settings" use:enhance={makeEnhancer('obsidian-current')} aria-busy={actionBusy('obsidian-current')}>
									<input type="hidden" name="vault_path" value={data.obsidianBrowser.currentPath || '.'} />
									<button class="btn-primary" type="submit" disabled={actionBusy('obsidian-current')}>
										{actionBusy('obsidian-current') ? '…' : 'use current directory'}
									</button>
								</form>
							</div>
						</div>
					</div>

				</div>
			</Accordion.ItemContent>
		</Accordion.Item>

		<!-- ── Section 4: Backup ─────────────────────────────────────────── -->
		<Accordion.Item value="backup" class="settings-section">
			<Accordion.ItemTrigger class="settings-trigger">
				<div>
					<p class="settings-tag text-surface-500">Preservation</p>
					<p class="settings-title">System Backup</p>
					<p class="settings-meta">Snapshot repository metadata</p>
				</div>
				<svg class="w-4 h-4 text-surface-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="square" stroke-linejoin="miter" stroke-width="1.5" d="M19 9l-7 7-7-7"/></svg>
			</Accordion.ItemTrigger>

			<Accordion.ItemContent>
				<div class="pb-8" transition:fade={{ duration: 160 }}>
					{#if data.backupManifest}
						<div class="divide-y" style="border-color: var(--border-dim)">
							{#each Object.entries(data.backupManifest) as [key, value]}
								<div class="flex items-center justify-between py-3 gap-4">
									<span class="font-mono text-[0.65rem] text-surface-500">{key}</span>
									<span class="font-mono text-[0.65rem] text-surface-200 truncate max-w-64">{String(value)}</span>
								</div>
							{/each}
						</div>
					{:else}
						<p class="font-mono text-xs text-surface-600 py-10 text-center">No system backups recorded yet.</p>
					{/if}
				</div>
			</Accordion.ItemContent>
		</Accordion.Item>

	</Accordion>

</main>
