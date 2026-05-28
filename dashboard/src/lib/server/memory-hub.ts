import { env } from '$env/dynamic/private';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname, join, normalize } from 'node:path';

export const memoryHubRoot = env.MEMORY_HUB_DATA_DIR ?? '/app/data/memory-hub';
export const settingsDir = join(memoryHubRoot, 'settings');
export const statusDir = join(memoryHubRoot, 'status');
export const backupDir = join(memoryHubRoot, 'backups');
export const emailWorkerDir = join(memoryHubRoot, 'email-worker');
export const docsWorkerDir = join(memoryHubRoot, 'docs-worker');
export const obsidianWorkerDir = join(memoryHubRoot, 'obsidian-worker');
export const githubWorkerDir = join(memoryHubRoot, 'github-worker');
export const enricherWorkerDir = join(memoryHubRoot, 'enricher-worker');

const SECRET_KEY = /^[a-z][a-z0-9_]{0,62}$/;
const RELATIVE_PATH = /^[a-zA-Z0-9._/-]+$/;

export type JsonRecord = Record<string, unknown>;

export async function readJson<T>(path: string, fallback: T): Promise<T> {
	try {
		const raw = await readFile(path, 'utf-8');
		return JSON.parse(raw) as T;
	} catch {
		return fallback;
	}
}

export async function writeJson(path: string, value: unknown, mode = 0o600): Promise<void> {
	await mkdir(dirname(path), { recursive: true });
	const tempPath = `${path}.tmp`;
	await writeFile(tempPath, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf-8', mode });
	await rename(tempPath, path);
}

export async function loadNamedJson<T>(dir: string, file: string, fallback: T): Promise<T> {
	return readJson<T>(join(dir, file), fallback);
}

export async function saveNamedJson(dir: string, file: string, value: unknown): Promise<void> {
	await writeJson(join(dir, file), value);
}

export function validateSecretKey(key: string): string {
	const normalized = key.trim().toLowerCase();
	if (!SECRET_KEY.test(normalized)) {
		throw new Error('Secret keys must use lowercase letters, digits, and underscores.');
	}
	return normalized;
}

export function sanitizeRelativePath(path: string): string {
	const normalized = path.trim().replace(/^\/+/, '').replace(/\\+/g, '/');
	if (!normalized) {
		throw new Error('Path cannot be empty.');
	}
	if (!RELATIVE_PATH.test(normalized) || normalized.split('/').some((part) => part === '..')) {
		throw new Error('Path must stay inside the mounted ingest tree.');
	}
	return normalize(normalized).replace(/^\/+/, '');
}

