import { fail } from '@sveltejs/kit';

import { loadBackupManifest } from '$lib/server/observability';
import { browseDirectory } from '$lib/server/filesystem-browser';
import { deleteSecret, readSecretsMap, saveSecret } from '$lib/server/secrets';
import {
	loadDocumentSettings,
	loadEmailAccounts,
	loadObsidianSettings,
	saveDocumentSettings,
	saveEmailAccounts,
	saveObsidianSettings
} from '$lib/server/worker-config';
import { getWorkerSettings, updateWorkerSettings } from '$lib/server/worker-settings';
import {
	memoryIngestDir,
	memoryObsidianDir,
	sanitizeRelativePath,
	validateSecretKey
} from '$lib/server/memory-hub';
import type { Actions, PageServerLoad } from './$types';

type SecretDefinition = {
	key: string;
	label: string;
	description: string;
};

const enrichmentSecretDefinitions: SecretDefinition[] = [
	{
		key: 'llm_api_key',
		label: 'Primary enrichment token',
		description: 'Used by the main remote summarizer.'
	},
	{
		key: 'fallback_llm_api_key',
		label: 'Fallback enrichment token',
		description: 'Used when the primary provider is rate limited or unavailable.'
	}
];

const sourceSecretDefinitions: SecretDefinition[] = [
	{
		key: 'github_token',
		label: 'GitHub access token',
		description: 'Used by the GitHub ingestion worker.'
	}
];

const secretKeys = new Set(
	[...enrichmentSecretDefinitions, ...sourceSecretDefinitions].map((definition) => definition.key)
);

export const load: PageServerLoad = async ({ url }) => {
	const docsPath = url.searchParams.get('docs_path') ?? '';
	const obsidianPath = url.searchParams.get('obsidian_path') ?? '';
	const [
		workerSettings,
		secrets,
		emailAccounts,
		documentSettings,
		obsidianSettings,
		backupManifest
	] = await Promise.all([
		getWorkerSettings(),
		readSecretsMap(),
		loadEmailAccounts(),
		loadDocumentSettings(),
		loadObsidianSettings(),
		loadBackupManifest()
	]);
	const documentBrowser = await browseDirectory({
		label: 'Documents',
		rootPath: memoryIngestDir,
		currentPath: docsPath || documentSettings.source_paths[0] || '',
		url,
		queryKey: 'docs_path'
	});
	const obsidianBrowser = await browseDirectory({
		label: 'Obsidian',
		rootPath: memoryObsidianDir,
		currentPath: obsidianPath || obsidianSettings.vault_path,
		url,
		queryKey: 'obsidian_path'
	});

	return {
		workerSettings,
		enrichmentSecretDefinitions: enrichmentSecretDefinitions.map((definition) => ({
			...definition,
			configured: Boolean(secrets[definition.key])
		})),
		sourceSecretDefinitions: sourceSecretDefinitions.map((definition) => ({
			...definition,
			configured: Boolean(secrets[definition.key])
		})),
		emailAccounts,
		documentSettings,
		obsidianSettings,
		backupManifest,
		documentBrowser,
		obsidianBrowser
	};
};

export const actions: Actions = {
	worker_settings: async ({ request }) => {
		const input = await request.formData();
		try {
			const worker = await updateWorkerSettings(String(input.get('worker') ?? ''), input);
			return { operation: 'worker_settings', message: `${worker} settings saved.` };
		} catch (error) {
			return fail(400, {
				operation: 'worker_settings',
				message: error instanceof Error ? error.message : 'Could not save worker settings.'
			});
		}
	},
	secret: async ({ request }) => {
		const input = await request.formData();
		const key = String(input.get('key') ?? '');
		const value = String(input.get('value') ?? '');
		const action = String(input.get('secret_action') ?? 'save');
		try {
			const normalized = validateSecretKey(key);
			if (!secretKeys.has(normalized)) {
				return fail(400, { operation: 'secret', message: 'Unknown secret.' });
			}
			if (action === 'delete') {
				await deleteSecret(normalized);
				return { operation: 'secret', message: `Secret ${normalized} deleted.` };
			}
			if (!value.trim()) {
				const current = await readSecretsMap();
				if (current[normalized]) {
					return { operation: 'secret', message: `Secret ${normalized} left unchanged.` };
				}
				return fail(400, { operation: 'secret', message: 'Secret value is required.' });
			}
			await saveSecret(normalized, value.trim());
			return { operation: 'secret', message: `Secret ${normalized} saved.` };
		} catch (error) {
			return fail(400, {
				operation: 'secret',
				message: error instanceof Error ? error.message : 'Could not save secret.'
			});
		}
	},
	email_account: async ({ request }) => {
		const input = await request.formData();
		const modeValues = input.getAll('mode').map((value) => String(value).trim()).filter(Boolean);
		const mode = modeValues.length > 0 ? modeValues[modeValues.length - 1] : 'save';
		const originalName = String(input.get('original_name') ?? '').trim();
		const name = String(input.get('name') ?? '').trim();
		try {
			const accounts = await loadEmailAccounts();
			if (mode === 'delete') {
				const targetName = originalName || name;
				if (!targetName) {
					return fail(400, { operation: 'email_account', message: 'Missing account name.' });
				}
				const nextAccounts = accounts.filter((account) => account.name.trim() !== targetName);
				if (nextAccounts.length === accounts.length) {
					return fail(404, {
						operation: 'email_account',
						message: `Email account ${targetName} was not found.`
					});
				}
				await saveEmailAccounts(nextAccounts);
				return { operation: 'email_account', message: `Email account ${targetName} removed.` };
			}
			const host = String(input.get('host') ?? '').trim();
			const user = String(input.get('user') ?? '').trim();
			const password = String(input.get('password') ?? '');
			const folder = String(input.get('folder') ?? '').trim();
			if (!name || !host || !user) {
				return fail(400, {
					operation: 'email_account',
					message: 'Name, host, and user are required.'
				});
			}
			const existing = accounts.find((account) => account.name === originalName);
			const port = Number(input.get('port') ?? existing?.port ?? 993);
			if (!Number.isInteger(port) || port < 1 || port > 65535) {
				return fail(400, {
					operation: 'email_account',
					message: 'IMAP port must be an integer from 1 to 65535.'
				});
			}
			const sslInput = input.get('ssl');
			const ssl = sslInput === null ? (existing?.ssl ?? true) : sslInput === 'on' || sslInput === 'true' || sslInput === '1';
			const nextPassword = password.trim() || existing?.password;
			if (!nextPassword) {
				return fail(400, {
					operation: 'email_account',
					message: 'Password is required for new accounts.'
				});
			}
			const filtered = accounts.filter((account) => account.name !== originalName);
			filtered.push({
				name,
				host,
				port,
				ssl,
				user,
				password: nextPassword,
				folder: folder || null
			});
			filtered.sort((left, right) => left.name.localeCompare(right.name));
			await saveEmailAccounts(filtered);
			return { operation: 'email_account', message: `Email account ${name} saved.` };
		} catch (error) {
			return fail(400, {
				operation: 'email_account',
				message: error instanceof Error ? error.message : 'Could not save email account.'
			});
		}
	},
	document_settings: async ({ request }) => {
		const input = await request.formData();
		try {
			const current = await loadDocumentSettings();
			const sourcePaths = current.source_paths;
			await saveDocumentSettings({
				sleep_interval: Number(input.get('sleep_interval') ?? current.sleep_interval),
				content_limit: Number(input.get('content_limit') ?? current.content_limit),
				source_paths: sourcePaths
			});
			return { operation: 'document_settings', message: 'Document settings saved.' };
		} catch (error) {
			return fail(400, {
				operation: 'document_settings',
				message: error instanceof Error ? error.message : 'Could not save document settings.'
			});
		}
	},
	document_source_add: async ({ request }) => {
		const input = await request.formData();
		const path = String(input.get('path') ?? '');
		try {
			const current = await loadDocumentSettings();
			const normalized = sanitizeRelativePath(path);
			const next = Array.from(new Set([...current.source_paths, normalized])).sort((left, right) =>
				left.localeCompare(right)
			);
			await saveDocumentSettings({ ...current, source_paths: next });
			return { operation: 'document_source_add', message: `Document source ${normalized} added.` };
		} catch (error) {
			return fail(400, {
				operation: 'document_source_add',
				message: error instanceof Error ? error.message : 'Could not add document source.'
			});
		}
	},
	document_source_remove: async ({ request }) => {
		const input = await request.formData();
		const path = String(input.get('path') ?? '');
		try {
			const current = await loadDocumentSettings();
			const normalized = sanitizeRelativePath(path);
			const next = current.source_paths.filter((entry) => entry !== normalized);
			await saveDocumentSettings({ ...current, source_paths: next });
			return { operation: 'document_source_remove', message: `Document source ${normalized} removed.` };
		} catch (error) {
			return fail(400, {
				operation: 'document_source_remove',
				message: error instanceof Error ? error.message : 'Could not remove document source.'
			});
		}
	},
	obsidian_settings: async ({ request }) => {
		const input = await request.formData();
		try {
			const current = await loadObsidianSettings();
			const requestedVaultPath = String(input.get('vault_path') ?? '').trim() || current.vault_path || '.';
			await saveObsidianSettings({
				sleep_interval: Number(input.get('sleep_interval') ?? current.sleep_interval),
				content_limit: Number(input.get('content_limit') ?? current.content_limit),
				vault_path: sanitizeRelativePath(requestedVaultPath)
			});
			return { operation: 'obsidian_settings', message: 'Obsidian settings saved.' };
		} catch (error) {
			return fail(400, {
				operation: 'obsidian_settings',
				message: error instanceof Error ? error.message : 'Could not save Obsidian settings.'
			});
		}
	}
};
