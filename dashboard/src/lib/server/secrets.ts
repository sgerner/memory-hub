import { settingsDir, readJson, validateSecretKey, writeJson } from './memory-hub';

export type SecretsMap = Record<string, string>;

export type SecretView = {
	key: string;
	configured: boolean;
	valuePreview: string;
};

const secretsPath = `${settingsDir}/secrets.json`;

export async function loadSecrets(): Promise<SecretView[]> {
	const secrets = await readJson<SecretsMap>(secretsPath, {});
	return Object.keys(secrets)
		.sort((left, right) => left.localeCompare(right))
		.map((key) => ({
			key,
			configured: Boolean(secrets[key]),
			valuePreview: secrets[key] ? 'configured' : 'empty'
		}));
}

export async function readSecretsMap(): Promise<SecretsMap> {
	return readJson<SecretsMap>(secretsPath, {});
}

export async function saveSecret(key: string, value: string): Promise<SecretsMap> {
	const normalized = validateSecretKey(key);
	const secrets = await readSecretsMap();
	secrets[normalized] = value;
	await writeJson(secretsPath, secrets);
	return secrets;
}

export async function deleteSecret(key: string): Promise<SecretsMap> {
	const normalized = validateSecretKey(key);
	const secrets = await readSecretsMap();
	delete secrets[normalized];
	await writeJson(secretsPath, secrets);
	return secrets;
}

