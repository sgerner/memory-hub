import { env } from '$env/dynamic/private';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
	return {
		gatewayUrl: (env.MEMORY_GATEWAY_URL ?? '').replace(/\/$/, ''),
		gatewayToken: env.MEMORY_GATEWAY_TOKEN ?? ''
	};
};
