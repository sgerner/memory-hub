import { backupDir, readJson, statusDir } from './memory-hub';

export type WorkerStatus = {
	service: string;
	status: string;
	last_cycle_started_at?: string;
	last_cycle_finished_at?: string;
	last_success_at?: string;
	last_error?: string;
	items_processed?: number;
	items_total?: number;
	items_remaining?: number;
	primary_provider?: string;
	fallback_provider?: string;
	concurrency?: number;
	batch_size?: number;
	rate_limit_per_minute?: number;
	source?: string;
	updated_at?: string;
	details?: Record<string, unknown>;
};

export type ObservabilityCard = {
	label: string;
	file: string;
	data: WorkerStatus | null;
};

const knownStatuses: Array<[string, string]> = [
	['Docs worker', 'docs-worker.json'],
	['Email worker', 'email-worker.json'],
	['GitHub worker', 'github-worker.json'],
	['Obsidian worker', 'obsidian-worker.json'],
	['Enrichment worker', 'enricher-worker.json'],
	['Migration worker', 'migration-worker.json'],
	['Backup job', 'backup.json']
];

export async function loadObservability(): Promise<ObservabilityCard[]> {
	return Promise.all(
		knownStatuses.map(async ([label, file]) => ({
			label,
			file,
			data: await readJson<WorkerStatus | null>(`${statusDir}/${file}`, null)
		}))
	);
}

export async function loadBackupManifest(): Promise<Record<string, unknown> | null> {
	return readJson<Record<string, unknown> | null>(`${backupDir}/manifest.json`, null);
}

