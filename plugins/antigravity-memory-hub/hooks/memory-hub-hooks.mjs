#!/usr/bin/env node
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const DEFAULT_GATEWAY_URL = 'http://127.0.0.1:3112';
const DEFAULT_AGENT = 'antigravity';
const DEFAULT_CATEGORIES = ['agent', 'emails', 'obsidian', 'documents', 'code'];
const MAX_RECALL_RESULTS = 5;

function readStdinJson() {
  const raw = fs.readFileSync(0, 'utf8').trim();
  return raw ? JSON.parse(raw) : {};
}

function config() {
  return {
    baseUrl: (process.env.MEMORY_GATEWAY_URL || DEFAULT_GATEWAY_URL).replace(/\/+$/, ''),
    token: process.env.MEMORY_GATEWAY_TOKEN || '',
    adminToken: process.env.MEMORY_ADMIN_TOKEN || '',
    agent: process.env.MEMORY_AGENT_NAME || DEFAULT_AGENT,
    stateDir:
      process.env.MEMORY_PLUGIN_STATE_DIR ||
      path.join(os.homedir(), '.gemini', 'antigravity-cli', 'cache', 'memory-hub'),
  };
}

function clip(value, limit = 240) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}

function extractUserRequest(content) {
  const raw = String(content || '');
  const match = raw.match(/<USER_REQUEST>([\s\S]*?)<\/USER_REQUEST>/i);
  if (match?.[1]) {
    return match[1].trim();
  }
  return raw.trim();
}

function extractAssistantResponse(content) {
  const raw = String(content || '').trim();
  return raw || '';
}

function parseTranscriptLines(transcriptPath) {
  try {
    const lines = fs.readFileSync(transcriptPath, 'utf8').split(/\r?\n/);
    return lines
      .map((line) => {
        if (!line.trim()) return null;
        try {
          return JSON.parse(line);
        } catch {
          return null;
        }
      })
      .filter(Boolean);
  } catch {
    return [];
  }
}

function findLatestUserPrompt(rows) {
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    const row = rows[i];
    if (row?.source === 'USER_EXPLICIT' && row?.type === 'USER_INPUT') {
      return extractUserRequest(row.content);
    }
  }
  return '';
}

function findLatestPlannerResponse(rows) {
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    const row = rows[i];
    if (row?.source === 'MODEL' && row?.type === 'PLANNER_RESPONSE' && row?.content) {
      return extractAssistantResponse(row.content);
    }
  }
  return '';
}

function turnStateFile(stateDir, conversationId) {
  return path.join(stateDir, 'turns', `${String(conversationId || 'unknown').replace(/[^a-zA-Z0-9._-]/g, '_')}.json`);
}

async function writeTurnState(stateDir, conversationId, payload) {
  const file = turnStateFile(stateDir, conversationId);
  await fs.promises.mkdir(path.dirname(file), { recursive: true });
  await fs.promises.writeFile(file, JSON.stringify(payload, null, 2), 'utf8');
}

async function readTurnState(stateDir, conversationId) {
  const file = turnStateFile(stateDir, conversationId);
  try {
    const raw = await fs.promises.readFile(file, 'utf8');
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

async function deleteTurnState(stateDir, conversationId) {
  const file = turnStateFile(stateDir, conversationId);
  try {
    await fs.promises.unlink(file);
  } catch {
    // ignore
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

function recallSummary(results = []) {
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

async function preInvocation(input) {
  const { stateDir, agent } = config();
  const transcriptPath = String(input?.transcriptPath || '');
  const rows = transcriptPath ? parseTranscriptLines(transcriptPath) : [];
  const prompt = findLatestUserPrompt(rows);

  const payload = {
    conversationId: input?.conversationId || null,
    invocationNum: input?.invocationNum ?? null,
    prompt,
    createdAt: new Date().toISOString(),
  };

  if (input?.conversationId) {
    await writeTurnState(stateDir, input.conversationId, payload);
  }

  let queueSummary = '';
  try {
    const queue = await gatewayRequest('/v1/queue-status', { timeoutMs: 3000 });
    const totals = queue?.totals || {};
    queueSummary = `Queue: ${Number(totals.embedding_pending ?? 0)} embedding pending, ${Number(
      totals.enrichment_pending ?? 0
    )} enrichment pending.`;
  } catch {
    queueSummary = 'Queue: unavailable.';
  }

  let recallText = '';
  if (prompt) {
    try {
      const recall = await gatewayRequest('/v1/recall', {
        method: 'POST',
        body: {
          query: prompt,
          categories: DEFAULT_CATEGORIES,
          limit: 5,
          include_inactive: false,
          metadata: { source: 'antigravity-hook', hook_event: 'PreInvocation' },
        },
      });
      recallText = recallSummary(recall?.results || []);
    } catch {
      recallText = 'Memory Hub recall: unavailable.';
    }
  }

  return {
    injectSteps: [
      {
        ephemeralMessage: `${queueSummary}\n${recallText}\nRemember to store confirmed durable facts after they are established.`,
      },
    ],
  };
}

async function stop(input) {
  const { stateDir, agent } = config();
  const fullyIdle = Boolean(input?.fullyIdle);

  if (!fullyIdle) {
    return {
      decision: 'continue',
      reason: 'Memory Hub: waiting for background tasks to finish.',
    };
  }

  const state = input?.conversationId ? await readTurnState(stateDir, input.conversationId) : null;
  const transcriptPath = String(input?.transcriptPath || '');
  const rows = transcriptPath ? parseTranscriptLines(transcriptPath) : [];
  const assistantSummary = findLatestPlannerResponse(rows);
  const prompt = String(state?.prompt || '').trim();

  try {
    if (input?.conversationId && (prompt || assistantSummary)) {
      await gatewayRequest('/v1/memories', {
        method: 'POST',
        body: {
          content: [
            'Antigravity turn summary',
            prompt ? `Prompt: ${clip(prompt, 800)}` : null,
            assistantSummary ? `Assistant summary: ${clip(assistantSummary, 1200)}` : null,
          ]
            .filter(Boolean)
            .join('\n'),
          category: 'agent',
          kind: 'episode',
          importance: 0.25,
          confidence: 0.7,
          retention: 'normal',
          source_agent: agent,
          metadata: {
            source: 'antigravity-hook',
            hook_event: 'Stop',
            conversation_id: input?.conversationId || null,
            prompt_excerpt: clip(prompt, 240),
            assistant_excerpt: clip(assistantSummary, 240),
          },
        },
      });
    }
  } catch {
    // Never block shutdown on memory persistence.
  } finally {
    if (input?.conversationId) {
      await deleteTurnState(stateDir, input.conversationId);
    }
  }

  return {
    decision: 'terminate',
  };
}

async function main() {
  const input = readStdinJson();
  const eventName = String(process.argv[2] || '').trim();
  let output = {};

  if (eventName === 'pre-invocation') {
    output = await preInvocation(input);
  } else if (eventName === 'stop') {
    output = await stop(input);
  } else {
    output = {};
  }

  process.stdout.write(JSON.stringify(output));
}

main().catch((error) => {
  console.error(error?.stack || error?.message || String(error));
  process.stdout.write(JSON.stringify({}));
});
