import { join } from 'node:path';

import {
	emailWorkerDir,
	loadNamedJson,
	obsidianWorkerDir,
	readJson,
	settingsDir,
	sanitizeRelativePath,
	writeJson
} from './memory-hub';

export type EmailAccount = {
	name: string;
	host: string;
	user: string;
	password: string;
	folder?: string | null;
};

export type DocumentSettings = {
	sleep_interval: number;
	content_limit: number;
	source_paths: string[];
};

export type ObsidianSettings = {
	sleep_interval: number;
	content_limit: number;
	vault_path: string;
};

const emailAccountsPath = join(emailWorkerDir, 'accounts.json');
const documentSettingsPath = join(settingsDir, 'documents.json');
const obsidianSettingsPath = join(settingsDir, 'obsidian.json');

export async function loadEmailAccounts(): Promise<EmailAccount[]> {
	return loadNamedJson<EmailAccount[]>(emailWorkerDir, 'accounts.json', []);
}

export async function saveEmailAccounts(accounts: EmailAccount[]): Promise<void> {
	await writeJson(emailAccountsPath, accounts);
}

export async function loadDocumentSettings(): Promise<DocumentSettings> {
	const configured = await readJson<Record<string, unknown>>(documentSettingsPath, {});
	return {
		sleep_interval: Number(configured.sleep_interval ?? 300),
		content_limit: Number(configured.content_limit ?? 100000),
		source_paths: Array.isArray(configured.source_paths)
			? configured.source_paths
					.map((entry) => String(entry).trim())
					.filter(Boolean)
					.map((entry) => sanitizeRelativePath(entry))
			: []
	};
}

export async function saveDocumentSettings(settings: DocumentSettings): Promise<void> {
	await writeJson(documentSettingsPath, settings);
}

export async function loadObsidianSettings(): Promise<ObsidianSettings> {
	const configured = await readJson<Record<string, unknown>>(obsidianSettingsPath, {});
	return {
		sleep_interval: Number(configured.sleep_interval ?? 60),
		content_limit: Number(configured.content_limit ?? 100000),
		vault_path: String(configured.vault_path ?? '').trim()
	};
}

export async function saveObsidianSettings(settings: ObsidianSettings): Promise<void> {
	await writeJson(obsidianSettingsPath, settings);
}
