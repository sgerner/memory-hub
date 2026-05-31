import { env } from '$env/dynamic/private';
import type { PageServerLoad } from './$types';

function normalizeOrigin(value: string) {
	return value.replace(/\/+$/, '');
}

export const load: PageServerLoad = async ({ url }) => {
	const publicOrigin = normalizeOrigin(env.MEMORY_PUBLIC_ORIGIN ?? '');
	const resolvedOrigin = publicOrigin || url.origin;

	return {
		publicOrigin: resolvedOrigin,
		apiUrl: `${resolvedOrigin}/api`,
		mcpUrl: `${resolvedOrigin}/mcp`,
		gatewayToken: env.MEMORY_GATEWAY_TOKEN ?? ''
	};
};
