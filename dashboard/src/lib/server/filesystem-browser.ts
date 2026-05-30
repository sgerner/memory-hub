import { readdir, stat } from 'node:fs/promises';
import { dirname, relative, resolve, sep } from 'node:path';

import { sanitizeRelativePath } from './memory-hub';

export type BrowserEntry = {
	name: string;
	path: string;
	href: string;
};

export type BrowserBreadcrumb = {
	label: string;
	path: string;
	href: string;
};

export type DirectoryBrowser = {
	label: string;
	rootPath: string;
	currentPath: string;
	currentLabel: string;
	rootHref: string;
	parentHref: string;
	breadcrumbs: BrowserBreadcrumb[];
	entries: BrowserEntry[];
	error: string | null;
};

function buildHref(url: URL, key: string, value: string): string {
	const next = new URLSearchParams(url.searchParams);
	if (value) {
		next.set(key, value);
	} else {
		next.delete(key);
	}
	const query = next.toString();
	return `${url.pathname}${query ? `?${query}` : ''}`;
}

function currentPathLabel(path: string): string {
	return path ? path : 'root';
}

export async function browseDirectory(options: {
	label: string;
	rootPath: string;
	currentPath: string;
	url: URL;
	queryKey: string;
}): Promise<DirectoryBrowser> {
	const { label, rootPath, currentPath, url, queryKey } = options;
	const normalizedCurrentPath = currentPath ? sanitizeRelativePath(currentPath) : '';
	const browsingPath = normalizedCurrentPath === '.' ? '' : normalizedCurrentPath;
	const rootAbsolute = resolve(rootPath);
	const targetPath = browsingPath ? resolve(rootPath, browsingPath) : rootAbsolute;

	try {
		const targetRelative = relative(rootAbsolute, targetPath);
		if (targetRelative.startsWith(`..${sep}`) || targetRelative === '..') {
			throw new Error('Path must stay inside the mounted source root.');
		}
		const targetStat = await stat(targetPath);
		if (!targetStat.isDirectory()) {
			throw new Error('Selected path is not a directory.');
		}

		const entries = (await readdir(targetPath, { withFileTypes: true }))
			.filter((entry) => entry.isDirectory())
			.map((entry) => {
				const childPath = browsingPath ? `${browsingPath}/${entry.name}` : entry.name;
				return {
					name: entry.name,
					path: childPath,
					href: buildHref(url, queryKey, childPath)
				};
			})
			.sort((left, right) => left.name.localeCompare(right.name));

		const breadcrumbs: BrowserBreadcrumb[] = [{ label: 'root', path: '', href: buildHref(url, queryKey, '') }];
		if (browsingPath) {
			const parts = browsingPath.split('/').filter(Boolean);
			let accumulated = '';
			for (const part of parts) {
				accumulated = accumulated ? `${accumulated}/${part}` : part;
				breadcrumbs.push({ label: part, path: accumulated, href: buildHref(url, queryKey, accumulated) });
			}
		}

		const parentPath = browsingPath ? dirname(browsingPath) : '';
		const parentHref = buildHref(url, queryKey, parentPath === '.' ? '' : parentPath);

		return {
			label,
			rootPath,
			currentPath: browsingPath,
			currentLabel: currentPathLabel(browsingPath),
			rootHref: buildHref(url, queryKey, ''),
			parentHref,
			breadcrumbs,
			entries,
			error: null
		};
	} catch (error) {
		const message = error instanceof Error ? error.message : `Could not browse ${label.toLowerCase()}.`;
		return {
			label,
			rootPath,
			currentPath: browsingPath,
			currentLabel: currentPathLabel(browsingPath),
			rootHref: buildHref(url, queryKey, ''),
			parentHref: buildHref(url, queryKey, ''),
			breadcrumbs: [{ label: 'root', path: '', href: buildHref(url, queryKey, '') }],
			entries: [],
			error: message
		};
	}
}
