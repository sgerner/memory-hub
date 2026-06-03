#!/usr/bin/env node
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const DEFAULT_GATEWAY_URL = 'http://127.0.0.1:3112';
const DEFAULT_AGENT = 'codex';
const DEFAULT_CATEGORIES = ['agent', 'emails', 'obsidian', 'documents', 'code'];
const MAX_RECALL_RESULTS = 5;
const ENV_KEYS = ['MEMORY_GATEWAY_URL', 'MEMORY_GATEWAY_TOKEN', 'MEMORY_ADMIN_TOKEN', 'MEMORY_AGENT_NAME'];

let envFileLoaded = false;

function inputFromStdin() {
  const raw = fs.readFileSync(0, 'utf8').trim();
  return raw ? JSON.parse(raw) : {};
}

function decodeEnvValue(value) {
  let text = String(value || '').trim();
  if (
    (text.startsWith('"') && text.endsWith('"')) ||
    (text.startsWith("'") && text.endsWith("'"))
  ) {
    text = text.slice(1, -1);
  }
  return text.replace(/\\(["'\\$` ])/g, '$1');
}

function loadEnvFile() {
  if (envFileLoaded) return;
  envFileLoaded = true;

  const envFile =
    process.env.MEMORY_HUB_ENV_FILE || path.join(os.homedir(), '.config', 'memory-hub', 'agent.env');
  try {
    const lines = fs.readFileSync(envFile, 'utf8').split(/\r?\n/);
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const assignment = trimmed.startsWith('export ') ? trimmed.slice(7).trim() : trimmed;
      const equals = assignment.indexOf('=');
      if (equals <= 0) continue;
      const key = assignment.slice(0, equals).trim();
      if (!ENV_KEYS.includes(key) || process.env[key]) continue;
      process.env[key] = decodeEnvValue(assignment.slice(equals + 1));
    }
  } catch {
    // Hooks still work with inherited env or localhost defaults.
  }
}

function config() {
  loadEnvFile();
  return {
    baseUrl: (process.env.MEMORY_GATEWAY_URL || DEFAULT_GATEWAY_URL).replace(/\/+$/, ''),
    token: process.env.MEMORY_GATEWAY_TOKEN || '',
    adminToken: process.env.MEMORY_ADMIN_TOKEN || '',
    agent: process.env.MEMORY_AGENT_NAME || DEFAULT_AGENT,
    pluginData: process.env.PLUGIN_DATA || path.join(os.tmpdir(), 'memory-hub-plugin-data'),
  };
}

function debugLog(message, data = {}) {
  if (!process.env.MEMORY_HUB_HOOK_DEBUG) return;
  try {
    const { pluginData } = config();
    const filePath = path.join(pluginData, 'hook-debug.log');
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.appendFileSync(
      filePath,
      `${new Date().toISOString()} ${message} ${JSON.stringify(data)}\n`,
      'utf8'
    );
  } catch {
    // Debug logging must never affect hooks.
  }
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

function responsePreview(text) {
  const flattened = String(text || '').replace(/\s+/g, ' ').trim();
  return flattened.length > 300 ? `${flattened.slice(0, 299)}…` : flattened;
}

function textFromValue(value) {
  if (value == null) return '';
  if (typeof value === 'string') return value.trim();
  if (Array.isArray(value)) return value.map(textFromValue).filter(Boolean).join('\n').trim();
  if (typeof value === 'object') {
    for (const key of ['text', 'content', 'message', 'body', 'value']) {
      const text = textFromValue(value[key]);
      if (text) return text;
    }
  }
  return '';
}

function latestMessageText(input, roles) {
  const messages = Array.isArray(input?.messages) ? input.messages : [];
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    const role = String(message?.role || message?.type || '').toLowerCase();
    if (roles.some((candidate) => role.includes(candidate))) {
      return textFromValue(message);
    }
  }
  return '';
}

function extractPrompt(input) {
  for (const key of ['prompt', 'user_prompt', 'userPrompt', 'last_user_message', 'lastUserMessage']) {
    const text = textFromValue(input?.[key]);
    if (text) return text;
  }
  return latestMessageText(input, ['user']);
}

function extractAssistant(input) {
  for (const key of [
    'last_assistant_message',
    'lastAssistantMessage',
    'last_agent_message',
    'lastAgentMessage',
    'assistant_message',
    'response',
    'final_response',
    'output',
  ]) {
    const text = textFromValue(input?.[key]);
    if (text) return text;
  }
  return latestMessageText(input, ['assistant', 'agent']);
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

  return /^(?:y|yes|yes please|yeah|yeah please|yep|yep please|no|nope|nah|no thanks|ok|okay|k|sure|sounds good|sounds right|that works|sgtm|thanks|thank you|continue|go ahead|go for it|do it|proceed|please do|ship it|looks good|lgtm|run it|try it|retry|again|same|confirm|confirmed)$/.test(
    normalized
  );
}

function isTransientOperationalPrompt(prompt) {
  const normalized = normalizeForClassification(prompt);
  if (!normalized) return true;

  const commandPatterns = [
    /^(?:run|rerun|execute|try)\s+(?:the\s+)?(?:tests?|checks?|build|lint|formatter|format|typecheck|ci)\b/,
    /^(?:npm|pnpm|yarn|bun|make|just|pytest|ruff|black|cargo|go|docker|docker compose)\s+\S+/,
    /^git\s+(?:add|commit|push|pull|fetch|merge|rebase|checkout|switch|status|log|diff|stash|reset|amend|tag)\b/,
    /^(?:please\s+)?(?:commit|push)\b(?:\s+(?:the\s+)?changes|\s+to\s+(?:origin|main|master|upstream)|\s+the\s+branch)?\b/,
    /^(?:please\s+)?commit\s+and\s+push\b/,
  ];
  if (commandPatterns.some((pattern) => pattern.test(normalized))) {
    return true;
  }

  const logLikePatterns = [
    /\b(?:build|test|lint|typecheck|ci|workflow|job)\s+(?:failed|passed|errored|timed out|is failing|is passing)\b/,
    /\b(?:exit code|stack trace|traceback|exception|error log|command output)\b/,
  ];
  return logLikePatterns.some((pattern) => pattern.test(normalized)) && wordCount(normalized) < 20;
}

function shouldStoreTurnSummary(prompt, assistantMessage) {
  const promptText = String(prompt || '').trim();
  const assistantText = String(assistantMessage || '').trim();
  if (!promptText && !assistantText) return false;
  if (isLowInformationPrompt(promptText)) return false;
  if (isTransientOperationalPrompt(promptText)) return false;
  if (wordCount(promptText) < 4 && wordCount(assistantText) < 12) return false;

  return wordCount(promptText) >= 4 || wordCount(assistantText) >= 20;
}

function stateKeys(input) {
  return [
    input?.turn_id,
    input?.turnId,
    input?.session_id,
    input?.sessionId,
    input?.thread_id,
    input?.threadId,
  ]
    .filter((value) => value != null && String(value).trim())
    .map((value) => String(value).trim())
    .filter((value, index, values) => values.indexOf(value) === index);
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
  const prompt = extractPrompt(input);
  const keys = stateKeys(input);

  for (const key of keys) {
    await saveTurn(pluginData, key, {
      prompt,
      session_id: input?.session_id || null,
      cwd: input?.cwd || null,
      created_at: new Date().toISOString(),
      raw_event_keys: Object.keys(input || {}).slice(0, 40),
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
  } catch (error) {
    debugLog('UserPromptSubmit failed', { error: error?.message || String(error), keys: Object.keys(input || {}) });
    return { continue: true };
  }
}

async function stop(input) {
  const { pluginData, agent } = config();
  const keys = stateKeys(input);
  const lastAssistantMessage = extractAssistant(input);

  try {
    let saved = null;
    for (const key of keys) {
      saved = await loadTurn(pluginData, key);
      if (saved) break;
    }
    const prompt = extractPrompt(input) || String(saved?.prompt || '').trim();

    if (shouldStoreTurnSummary(prompt, lastAssistantMessage)) {
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
            turn_id: input?.turn_id || input?.turnId || null,
            prompt_excerpt: clip(prompt, 240),
            assistant_excerpt: clip(lastAssistantMessage, 240),
            raw_event_keys: Object.keys(input || {}).slice(0, 40).join(','),
          },
        },
      });
    } else if (process.env.MEMORY_HUB_HOOK_DEBUG) {
      debugLog('Stop skipped transient summary', {
        keys: Object.keys(input || {}).slice(0, 40),
        prompt: clip(prompt, 240),
        assistant: clip(lastAssistantMessage, 240),
      });
    }
  } catch (error) {
    debugLog('Stop failed', { error: error?.message || String(error), keys: Object.keys(input || {}) });
    // keep Codex moving even if the summary store fails
  } finally {
    for (const key of keys) {
      await deleteTurn(pluginData, key);
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
