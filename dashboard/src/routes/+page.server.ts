import { fail } from '@sveltejs/kit';
import { gateway } from '$lib/server/gateway';
import { loadObservability } from '$lib/server/observability';
import type { Actions, PageServerLoad } from './$types';

type Metadata = Record<string, string | number | boolean | null>;
type Memory = { category: string; id: string; document: string; metadata: Metadata; distance?: number };
type Overview = {
	categories: Array<{ category: string; loaded: number; active: number; sample_limit: number }>;
	loaded_statuses: Record<string, number>;
	recent: Memory[];
	sample_limit: number;
	generated_at: string;
};

const categories = ['agent', 'emails', 'obsidian', 'documents', 'code'];

export const load: PageServerLoad = async ({ url }) => {
	const category = categories.includes(url.searchParams.get('category') ?? '')
		? (url.searchParams.get('category') as string)
		: 'agent';
	const includeInactive = url.searchParams.get('inactive') === 'true';
	try {
		const [overview, listed, observability] = await Promise.all([
			gateway<Overview>('/v1/overview?sample_limit=20'),
			gateway<{ memories: Memory[] }>(`/v1/memories/${category}?limit=30&include_inactive=${includeInactive}`),
			loadObservability()
		]);
		return {
			overview,
			memories: listed.memories,
			categories,
			category,
			includeInactive,
			observability,
			backendError: null
		};
	} catch {
		const overview: Overview = {
			categories: [],
			loaded_statuses: {},
			recent: [],
			sample_limit: 20,
			generated_at: new Date().toISOString()
		};
		return {
			overview,
			memories: [],
			categories,
			category,
			includeInactive,
			observability: [],
			backendError: 'Memory data is temporarily unavailable while the backend is busy or restarting.'
		};
	}
};

export const actions: Actions = {
	recall: async ({ request }) => {
		const input = await request.formData();
		const query = String(input.get('query') ?? '').trim();
		const category = String(input.get('category') ?? '');
		if (!query) return fail(400, { operation: 'recall', message: 'Enter a search query.' });
		const result = await gateway<{ results: Memory[] }>('/v1/recall', {
			method: 'POST',
			body: JSON.stringify({
				query,
				categories: categories.includes(category) ? [category] : undefined,
				limit: 12,
				include_inactive: input.get('include_inactive') === 'true'
			})
		});
		return { operation: 'recall', query, recallResults: result.results };
	},
	store: async ({ request }) => {
		const input = await request.formData();
		const content = String(input.get('content') ?? '').trim();
		if (!content) return fail(400, { operation: 'store', message: 'Memory content is required.' });
		await gateway('/v1/memories', {
			method: 'POST',
			body: JSON.stringify({
				content,
				category: String(input.get('category') ?? 'agent'),
				kind: String(input.get('kind') ?? 'fact'),
				retention: String(input.get('retention') ?? 'normal'),
				importance: Number(input.get('importance') ?? 0.5),
				confidence: Number(input.get('confidence') ?? 0.8),
				source_agent: 'dashboard'
			})
		});
		return { operation: 'store', message: 'Memory stored.' };
	},
	archive: async ({ request }) => changeLifecycle(request, 'archive'),
	forget: async ({ request }) => changeLifecycle(request, 'forget')
};

async function changeLifecycle(request: Request, action: 'archive' | 'forget') {
	const input = await request.formData();
	const category = String(input.get('category') ?? '');
	const id = String(input.get('id') ?? '');
	if (!categories.includes(category) || !id) {
		return fail(400, { operation: action, message: 'Invalid memory reference.' });
	}
	await gateway(`/v1/memories/${encodeURIComponent(category)}/${encodeURIComponent(id)}/${action}`, {
		method: 'POST',
		body: JSON.stringify({
			reason: `Marked ${action} from dashboard`,
			source_agent: 'dashboard'
		})
	});
	return { operation: action, message: `Memory marked ${action}d.` };
}
