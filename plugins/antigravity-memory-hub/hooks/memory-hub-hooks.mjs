#!/usr/bin/env node
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const DEFAULT_GATEWAY_URL = 'http://127.0.0.1:3112';
const DEFAULT_AGENT = 'antigravity';
const DEFAULT_CATEGORIES = ['agent', 'emails', 'obsidian', 'documents', 'code'];
const MAX_RECALL_RESULTS = 5;
const HOOK_SOURCE = 'antigravity-hook';

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

function responsePreview(text) {
  const flattened = String(text || '').replace(/\s+/g, ' ').trim();
  return flattened.length > 300 ? `${flattened.slice(0, 299)}…` : flattened;
}

async function readJsonResponse(response, path) {
  const text = await response.text();
  const contentType = response.headers.get('content-type') || '';
  if (!response.ok) {
    throw new Error(
      `Gateway ${response.status} ${response.statusText}${text ? `: ${responsePreview(text)}` : ''}`
    );
  }

  if (!text) {
    return {};
  }

  if (!contentType.includes('application/json')) {
    throw new Error(
      `Gateway ${path} returned ${contentType || 'unknown content type'} instead of JSON: ${responsePreview(text)}`
    );
  }

  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`Gateway ${path} returned invalid JSON: ${error.message}. Body: ${responsePreview(text)}`);
  }
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
      return await readJsonResponse(response, pathname);
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

  const lines = ['Memory Hub recall (use only if relevant):'];
  for (const [index, result] of results.slice(0, MAX_RECALL_RESULTS).entries()) {
    const metadata = result?.metadata || {};
    const kind = metadata.memory_kind || metadata.kind || 'memory';
    const category = result?.category || 'agent';
    const id = result?.id ? `#${result.id}` : '';
    const score = typeof result?.score === 'number' ? ` (${result.score.toFixed(2)})` : '';
    const title = metadata.enrichment_title || metadata.title || '';
    const summary = metadata.enrichment_summary || metadata.summary || '';
    const source = metadata.repo || metadata.source || metadata.plugin || '';
    const content = title && summary ? `${title}: ${summary}` : title || summary || result?.document || '';
    const why = metadata.agent_value || metadata.future_use || metadata.reason || '';
    const sourceText = source ? ` source=${source}` : '';
    const whyText = why ? ` | use: ${clip(why, 120)}` : '';
    lines.push(`${index + 1}. [${category}/${kind}${id}${sourceText}] ${clip(content, 260)}${whyText}${score}`);
  }
  lines.push('Fetch full details only when needed with memory_get(category, memoryId).');
  return lines.join('\n');
}

function normalizeForClassification(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[`*_~>#"'()[\]{},.!?:;]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function wordCount(value) {
  const words = normalizeForClassification(value).match(/[a-z0-9][a-z0-9_-]*/g);
  return words ? words.length : 0;
}

function isLowInformationPrompt(prompt) {
  const normalized = normalizeForClassification(prompt);
  if (!normalized) return true;
  if (wordCount(normalized) > 6) return false;

  return /^(?:y|yes|yes please|yeah|yeah please|yep|yep please|no|nope|nah|no thanks|ok|okay|k|sure|sounds good|sounds right|that works|sgtm|thanks|thank you|continue|go ahead|go for it|do it|proceed|please do|ship it|looks good|lgtm|run it|try it|retry|again|same|confirm|confirmed|commit|commit and push)$/.test(
    normalized
  );
}

function isTransientOperationalPrompt(prompt) {
  const normalized = normalizeForClassification(prompt);
  if (!normalized) return true;

  const commandPatterns = [
    /^(?:run|rerun|execute|try)\\s+(?:the\\s+)?(?:tests?|checks?|build|lint|formatter|format|typecheck|ci)\\b/,
    /^(?:npm|pnpm|yarn|bun|make|just|pytest|ruff|black|cargo|go|docker|docker compose)\\s+\\S+/,
    /^git\\s+(?:add|commit|push|pull|fetch|merge|rebase|checkout|switch|status|log|diff|stash|reset|amend|tag)\\b/,
    /^(?:please\\s+)?(?:commit|push)\\b(?:\\s+(?:the\\s+)?changes|\\s+to\\s+(?:origin|main|master|upstream)|\\s+the\\s+branch)?\\b/,
    /^(?:please\\s+)?commit\\s+and\\s+push\\b/,
  ];
  if (commandPatterns.some((pattern) => pattern.test(normalized))) {
    return true;
  }

  const logLikePatterns = [
    /\\b(?:build|test|lint|typecheck|ci|workflow|job)\\s+(?:failed|passed|errored|timed out|is failing|is passing)\\b/,
    /\\b(?:exit code|stack trace|traceback|exception|error log|command output)\\b/,
  ];
  return logLikePatterns.some((pattern) => pattern.test(normalized)) && wordCount(normalized) < 20;
}

function shouldSkipRecall(prompt) {
  const promptText = String(prompt || '').trim();
  if (!promptText) return true;
  return isLowInformationPrompt(promptText) || isTransientOperationalPrompt(promptText);
}

function durableTurnMemory(prompt, assistantMessage) {
  const promptText = String(prompt || '').trim();
  const assistantText = String(assistantMessage || '').trim();
  const combined = normalizeForClassification(`${promptText} ${assistantText}`);
  if (!combined || wordCount(combined) < 18) {
    return null;
  }

  const durableSignals = [
    /\b(?:decided|decision|confirmed|preference|convention|policy|must|should|avoid|always|never)\b/,
    /\b(?:implemented|fixed|changed|added|removed|renamed|migrated|optimized|refactored)\b/,
    /\b(?:root cause|bug|regression|schema|contract|api|workflow|procedure|gotcha|pitfall)\b/,
    /\b(?:future agents?|durable|remember|store|recall|cross-session)\b/,
  ];
  if (!durableSignals.some((pattern) => pattern.test(combined))) {
    return null;
  }

  const kind = /\b(?:decided|decision|preference|convention|policy|must|should|avoid|always|never)\b/.test(combined)
    ? 'decision'
    : /\b(?:workflow|procedure|steps?|how to|runbook)\b/.test(combined)
      ? 'procedure'
      : /\b(?:root cause|bug|regression|fixed|implemented|changed|added|removed|optimized)\b/.test(combined)
        ? 'fact'
        : 'episode';

  const importance = kind === 'decision' || kind === 'procedure' ? 0.75 : kind === 'fact' ? 0.65 : 0.45;
  const title = clip(promptText || assistantText, 90);
  const outcome = clip(assistantText || promptText, 900);
  const goal = clip(promptText || '(not available)', 500);
  const agentValue =
    kind === 'decision'
      ? 'Preserves a decision or convention future agents should follow.'
      : kind === 'procedure'
        ? 'Preserves a repeatable workflow future agents can reuse.'
        : 'Preserves a completed change, bug, or project fact future agents may need.';

  return {
    content: [
      `Agent durable ${kind}`,
      `User goal: ${goal}`,
      `Outcome: ${outcome || '(not available)'}`,
      `Future agent value: ${agentValue}`,
    ].join('\n'),
    kind,
    importance,
    title,
    summary: `${goal}${outcome && outcome !== goal ? ` -> ${outcome}` : ''}`,
    agentValue,
  };
}

async function recallForPrompt(prompt) {
  if (shouldSkipRecall(prompt)) {
    return [];
  }

  const body = {
    query: prompt,
    categories: DEFAULT_CATEGORIES,
    limit: 5,
    include_inactive: false,
    recency_decay: 365,
  };

  const recall = await gatewayRequest('/v1/recall', {
    method: 'POST',
    body,
  });
  const results = recall?.results || [];
  if (results.length) {
    return results;
  }

  const agentRecall = await gatewayRequest('/v1/recall', {
    method: 'POST',
    body: { ...body, categories: ['agent'], recency_decay: null },
  });
  return agentRecall?.results || [];
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
      const results = await recallForPrompt(prompt);
      if (results.length) {
        recallText = recallSummary(results);
      }
    } catch {
      recallText = 'Memory Hub recall: unavailable.';
    }
  }

  return {
    injectSteps: [
      {
        ephemeralMessage: [queueSummary, recallText, 'Remember to store confirmed durable facts after they are established.']
          .filter(Boolean)
          .join('\n'),
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
    const memory = durableTurnMemory(prompt, assistantSummary);
    if (input?.conversationId && memory) {
      await gatewayRequest('/v1/memories', {
        method: 'POST',
        body: {
          content: memory.content,
          category: 'agent',
          kind: memory.kind,
          importance: memory.importance,
          confidence: 0.75,
          retention: 'normal',
          source_agent: agent,
          metadata: {
            source: HOOK_SOURCE,
            hook_event: 'Stop',
            conversation_id: input?.conversationId || null,
            title: memory.title,
            summary: memory.summary,
            agent_value: memory.agentValue,
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
