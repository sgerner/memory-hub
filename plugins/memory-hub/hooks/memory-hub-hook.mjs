#!/usr/bin/env node
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const DEFAULT_GATEWAY_URL = 'http://127.0.0.1:3112';
const DEFAULT_AGENT = 'codex';
const DEFAULT_CATEGORIES = ['agent', 'emails', 'obsidian', 'documents', 'code'];
const MAX_RECALL_RESULTS = 5;

function inputFromStdin() {
  const raw = fs.readFileSync(0, 'utf8').trim();
  return raw ? JSON.parse(raw) : {};
}

function config() {
  return {
    baseUrl: (process.env.MEMORY_GATEWAY_URL || DEFAULT_GATEWAY_URL).replace(/\/+$/, ''),
    token: process.env.MEMORY_GATEWAY_TOKEN || '',
    adminToken: process.env.MEMORY_ADMIN_TOKEN || '',
    agent: process.env.MEMORY_AGENT_NAME || DEFAULT_AGENT,
    pluginData: process.env.PLUGIN_DATA || path.join(os.tmpdir(), 'memory-hub-plugin-data'),
  };
}

function sanitizeSegment(value) {
  return String(value || 'unknown').replace(/[^a-zA-Z0-9._-]/g, '_');
}

function clip(text, limit = 220) {
  const flattened = String(text || '').replace(/\s+/g, ' ').trim();
  if (!flattened) return '';
  if (flattened.length <= limit) return flattened;
  return `${flattened.slice(0, limit - 1)}…`;
}

function turnFile(pluginData, turnId) {
  return path.join(pluginData, 'turns', `${sanitizeSegment(turnId)}.json`);
}

async function ensureDir(filePath) {
  await fs.promises.mkdir(path.dirname(filePath), { recursive: true });
}

async function saveTurn(pluginData, turnId, payload) {
  const filePath = turnFile(pluginData, turnId);
  await ensureDir(filePath);
  await fs.promises.writeFile(filePath, JSON.stringify(payload, null, 2), 'utf8');
}

async function loadTurn(pluginData, turnId) {
  const filePath = turnFile(pluginData, turnId);
  try {
    const raw = await fs.promises.readFile(filePath, 'utf8');
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

async function deleteTurn(pluginData, turnId) {
  const filePath = turnFile(pluginData, turnId);
  try {
    await fs.promises.unlink(filePath);
  } catch {
    // ignore missing files
  }
}

async function gatewayRequest(pathname, { method = 'GET', body, auth = true, admin = false, timeoutMs = 4000 } = {}) {
  const { baseUrl, token, adminToken } = config();
  const authToken = auth ? (admin ? adminToken || token : token) : '';
  if (auth && !authToken) {
    throw new Error('Memory Hub gateway token is unavailable');
  }

  const candidates = [baseUrl];
  try {
    const hostname = new URL(baseUrl).hostname;
    if (hostname && hostname !== '127.0.0.1' && hostname !== 'localhost') {
      candidates.push(DEFAULT_GATEWAY_URL);
    }
  } catch {
    candidates.push(DEFAULT_GATEWAY_URL);
  }

  let lastError;
  for (const candidate of candidates) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${candidate}${pathname}`, {
        method,
        headers: {
          ...(auth ? { Authorization: `Bearer ${authToken}` } : {}),
          ...(body ? { 'Content-Type': 'application/json' } : {}),
          Accept: 'application/json',
        },
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
      const text = await response.text();
      if (!response.ok) {
        throw new Error(
          `Gateway ${response.status} ${response.statusText}${text ? `: ${text.slice(0, 1000)}` : ''}`
        );
      }
      return text ? JSON.parse(text) : {};
    } catch (error) {
      lastError = error;
      const cause = error?.cause?.code || error?.code || error?.name || '';
      if (!['EAI_AGAIN', 'ENOTFOUND', 'ECONNREFUSED', 'ECONNRESET', 'ETIMEDOUT', 'AbortError'].includes(cause)) {
        throw error;
      }
    } finally {
      clearTimeout(timeout);
    }
  }

  throw lastError || new Error('Gateway request failed');
}

function formatRecallResults(results = []) {
  if (!results.length) {
    return 'Memory Hub recall: no close matches.';
  }

  const lines = ['Memory Hub recall:'];
  for (const [index, result] of results.slice(0, MAX_RECALL_RESULTS).entries()) {
    const kind = result?.metadata?.memory_kind || result?.metadata?.kind || 'memory';
    const category = result?.category || 'agent';
    const score = typeof result?.score === 'number' ? ` (${result.score.toFixed(2)})` : '';
    lines.push(`${index + 1}. [${category}/${kind}] ${clip(result?.document || '', 150)}${score}`);
  }
  return lines.join('\n');
}

async function sessionStart(input) {
  try {
    const queue = await gatewayRequest('/v1/queue-status');
    const totals = queue?.totals || {};
    const embedding = Number(totals.embedding_pending ?? 0);
    const enrichment = Number(totals.enrichment_pending ?? 0);
    return {
      continue: true,
      hookSpecificOutput: {
        hookEventName: 'SessionStart',
        additionalContext:
          `Memory Hub queue: ${embedding} embedding pending, ${enrichment} enrichment pending. ` +
          'Use recall before answering, and store durable facts only after confirmation.',
      },
    };
  } catch {
    return { continue: true };
  }
}

async function userPromptSubmit(input) {
  const { pluginData, agent } = config();
  const prompt = String(input?.prompt || '').trim();
  const turnId = String(input?.turn_id || input?.session_id || '');

  if (turnId) {
    await saveTurn(pluginData, turnId, {
      prompt,
      session_id: input?.session_id || null,
      cwd: input?.cwd || null,
      created_at: new Date().toISOString(),
    });
  }

  if (!prompt) {
    return { continue: true };
  }

  try {
    const recall = await gatewayRequest('/v1/recall', {
      method: 'POST',
      body: {
        query: prompt,
        categories: DEFAULT_CATEGORIES,
        limit: 5,
        include_inactive: false,
        metadata: { source: 'codex-hook', hook_event: 'UserPromptSubmit' },
      },
    });

    return {
      continue: true,
      hookSpecificOutput: {
        hookEventName: 'UserPromptSubmit',
        additionalContext:
          `${formatRecallResults(recall?.results || [])}\n` +
          `Memory Hub agent: ${agent}. Store confirmed durable facts after they are established.`,
      },
    };
  } catch {
    return { continue: true };
  }
}

async function stop(input) {
  const { pluginData, agent } = config();
  const turnId = String(input?.turn_id || '');
  const lastAssistantMessage = String(input?.last_assistant_message || '').trim();

  try {
    const saved = turnId ? await loadTurn(pluginData, turnId) : null;
    const prompt = String(saved?.prompt || '').trim();

    if ((prompt || lastAssistantMessage) && (prompt.length > 20 || lastAssistantMessage.length > 20)) {
      await gatewayRequest('/v1/memories', {
        method: 'POST',
        body: {
          content: [
            'Codex turn episode',
            `Prompt: ${clip(prompt, 800) || '(not available)'}`,
            `Assistant: ${clip(lastAssistantMessage, 1000) || '(not available)'}`,
          ].join('\n'),
          category: 'agent',
          kind: 'episode',
          importance: 0.25,
          confidence: 0.7,
          retention: 'normal',
          source_agent: agent,
          metadata: {
            source: 'codex-hook',
            hook_event: 'Stop',
            session_id: input?.session_id || null,
            turn_id: turnId || null,
            prompt_excerpt: clip(prompt, 240),
            assistant_excerpt: clip(lastAssistantMessage, 240),
          },
        },
      });
    }
  } catch {
    // keep Codex moving even if the summary store fails
  } finally {
    if (turnId) {
      await deleteTurn(pluginData, turnId);
    }
  }

  return { continue: true };
}

async function main() {
  const input = inputFromStdin();
  const eventName = String(input?.hook_event_name || process.argv[2] || '').trim();

  let output = { continue: true };
  switch (eventName) {
    case 'SessionStart':
      output = await sessionStart(input);
      break;
    case 'UserPromptSubmit':
      output = await userPromptSubmit(input);
      break;
    case 'Stop':
      output = await stop(input);
      break;
    default:
      output = { continue: true };
      break;
  }

  process.stdout.write(JSON.stringify(output));
}

main().catch((error) => {
  console.error(error?.stack || error?.message || String(error));
  process.stdout.write(JSON.stringify({ continue: true }));
});
