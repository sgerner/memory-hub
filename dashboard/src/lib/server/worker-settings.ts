import { settingsDir, loadNamedJson, writeJson } from './memory-hub';

export type SettingField = {
	key: string;
	label: string;
	description: string;
	type: 'number' | 'select';
	min?: number;
	max?: number;
	options?: string[];
};

type WorkerDefinition = {
	id: string;
	name: string;
	description: string;
	file: string;
	defaults: Record<string, number | string>;
	fields: SettingField[];
};

const definitions: WorkerDefinition[] = [
	{
		id: 'documents',
		name: 'Documents',
		description: 'PDF, Word and file-system document discovery.',
		file: 'documents.json',
		defaults: { sleep_interval: 300, content_limit: 100000 },
		fields: [
			numberField('sleep_interval', 'Poll interval', 'Seconds between folder scans.', 30, 86400),
			numberField(
				'content_limit',
				'Content limit',
				'Maximum extracted characters embedded per file.',
				1000,
				500000
			)
		]
	},
	{
		id: 'obsidian',
		name: 'Obsidian',
		description: 'Markdown vault synchronization.',
		file: 'obsidian.json',
		defaults: { sleep_interval: 60, content_limit: 100000, vault_path: '' },
		fields: [
			numberField('sleep_interval', 'Poll interval', 'Seconds between vault scans.', 10, 86400),
			numberField(
				'content_limit',
				'Content limit',
				'Maximum characters embedded per note.',
				1000,
				500000
			)
		]
	},
	{
		id: 'email',
		name: 'Email',
		description: 'IMAP ingestion and attachment extraction.',
		file: 'email.json',
		defaults: { batch_size: 2000, sleep_interval: 60, attachment_text_limit: 50000 },
		fields: [
			numberField('batch_size', 'Batch size', 'Maximum new messages per folder per cycle.', 1, 10000),
			numberField('sleep_interval', 'Poll interval', 'Seconds between mail cycles.', 30, 86400),
			numberField(
				'attachment_text_limit',
				'Attachment limit',
				'Maximum extracted characters per attachment.',
				1000,
				250000
			)
		]
	},
	{
		id: 'github',
		name: 'GitHub',
		description: 'Repository source and discussion discovery.',
		file: 'github.json',
		defaults: { sleep_interval: 3600, content_limit: 100000, issues_per_repo: 50 },
		fields: [
			numberField('sleep_interval', 'Poll interval', 'Seconds between account scans.', 300, 86400),
			numberField(
				'content_limit',
				'Content limit',
				'Maximum source characters embedded per record.',
				1000,
				500000
			),
			numberField(
				'issues_per_repo',
				'Issues per repo',
				'Recent issues and pull requests checked each scan.',
				1,
				100
			)
		]
	},
	{
		id: 'enrichment',
		name: 'Enrichment',
		description: 'Remote summarization followed by local vector refresh.',
		file: 'enrichment.json',
		defaults: {
			batch_size: 100,
			sleep_interval: 10,
			concurrency: 50,
			text_limit: 8000,
			email_model: 'deepseek-v4-flash',
			email_fallback_model: 'deepseek-v4-flash-free',
			knowledge_model: 'deepseek-v4-flash',
			knowledge_fallback_model: 'deepseek-v4-flash-free',
			fallback_requests_per_minute: 4
		},
		fields: [
			numberField('batch_size', 'Batch size', 'Pending records fetched per category.', 1, 1000),
			numberField('sleep_interval', 'Idle interval', 'Seconds before checking again when idle.', 5, 3600),
			numberField(
				'concurrency',
				'Concurrency',
				'Concurrent summaries and local embedding updates.',
				1,
				100
			),
			numberField('text_limit', 'Prompt limit', 'Maximum source characters sent for summarization.', 500, 32000),
			numberField(
				'fallback_requests_per_minute',
				'Fallback RPM',
				'Maximum fallback requests per minute.',
				1,
				120
			),
			selectField('email_model', 'Email model', ['deepseek-v4-flash', 'deepseek-v4-pro']),
			selectField('email_fallback_model', 'Email fallback model', [
				'deepseek-v4-flash-free',
				'mimo-v2.5-free'
			]),
			selectField('knowledge_model', 'Knowledge model', ['deepseek-v4-flash', 'deepseek-v4-pro']),
			selectField('knowledge_fallback_model', 'Knowledge fallback model', [
				'deepseek-v4-flash-free',
				'mimo-v2.5-free'
			])
		]
	}
];

function numberField(key: string, label: string, description: string, min: number, max: number): SettingField {
	return { key, label, description, type: 'number', min, max };
}

function selectField(key: string, label: string, options: string[]): SettingField {
	return { key, label, description: 'Remote summarization tier.', type: 'select', options };
}

export async function getWorkerSettings() {
	return Promise.all(
		definitions.map(async (definition) => ({
			id: definition.id,
			name: definition.name,
			description: definition.description,
			fields: definition.fields,
			values: { ...definition.defaults, ...(await readSettings(definition)) }
		}))
	);
}

export async function updateWorkerSettings(id: string, form: FormData) {
	const definition = definitions.find((worker) => worker.id === id);
	if (!definition) throw new Error('Unknown worker.');
	const values: Record<string, number | string> = {};
	for (const field of definition.fields) {
		const submitted = String(form.get(field.key) ?? '').trim();
		if (field.type === 'number') {
			const value = Number(submitted);
			if (!Number.isInteger(value) || value < (field.min ?? 0) || value > (field.max ?? Infinity)) {
				throw new Error(`${field.label} must be an integer from ${field.min} to ${field.max}.`);
			}
			values[field.key] = value;
		} else if (!field.options?.includes(submitted)) {
			throw new Error(`${field.label} is invalid.`);
		} else {
			values[field.key] = submitted;
		}
	}
	const current = await readSettings(definition);
	await writeJson(`${settingsDir}/${definition.file}`, { ...current, ...values });
	return definition.name;
}

async function readSettings(definition: WorkerDefinition) {
	return loadNamedJson<Record<string, number | string>>(settingsDir, definition.file, {});
}
