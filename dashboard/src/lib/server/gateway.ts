import { env } from '$env/dynamic/private';
import { error } from '@sveltejs/kit';

const gatewayUrl = (env.MEMORY_GATEWAY_URL ?? 'http://memory-agent-gateway:3112').replace(/\/$/, '');

export async function gateway<T>(
	path: string,
	options: RequestInit = {}
): Promise<T> {
	const token = env.MEMORY_GATEWAY_TOKEN;
	if (!token) {
		throw error(500, 'Dashboard gateway token is not configured.');
	}
	const response = await fetch(`${gatewayUrl}${path}`, {
		...options,
		headers: {
			Authorization: `Bearer ${token}`,
			'Content-Type': 'application/json',
			...options.headers
		}
	});
	if (!response.ok) {
		let detail = `Gateway request failed (${response.status})`;
		try {
			const body = await response.json();
			detail = body.detail ?? detail;
		} catch {
			// Preserve the status-based message when a proxy returns non-JSON.
		}
		throw error(response.status, detail);
	}
	return response.json() as Promise<T>;
}
