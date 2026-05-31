import { tool } from "@opencode-ai/plugin";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const DEFAULT_GATEWAY_URL = "http://127.0.0.1:3112";
const DEFAULT_AGENT = "opencode";
const DEFAULT_CATEGORIES = ["agent", "emails", "obsidian", "documents", "code"];
const ENV_KEYS = ["MEMORY_GATEWAY_URL", "MEMORY_GATEWAY_TOKEN", "MEMORY_ADMIN_TOKEN", "MEMORY_AGENT_NAME"];

let envFileLoaded = false;
const storedSignatures = new Map();

function decodeEnvValue(value) {
  let text = String(value || "").trim();
  if ((text.startsWith('"') && text.endsWith('"')) || (text.startsWith("'") && text.endsWith("'"))) {
    text = text.slice(1, -1);
  }
  return text.replace(/\\(["'\\$` ])/g, "$1");
}

function loadEnvFile() {
  if (envFileLoaded) return;
  envFileLoaded = true;

  const envFile = process.env.MEMORY_HUB_ENV_FILE || path.join(os.homedir(), ".config", "memory-hub", "agent.env");
  try {
    for (const line of fs.readFileSync(envFile, "utf8").split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const assignment = trimmed.startsWith("export ") ? trimmed.slice(7).trim() : trimmed;
      const equals = assignment.indexOf("=");
      if (equals <= 0) continue;
      const key = assignment.slice(0, equals).trim();
      if (!ENV_KEYS.includes(key) || process.env[key]) continue;
      process.env[key] = decodeEnvValue(assignment.slice(equals + 1));
    }
  } catch {
    // Plugins still work with inherited env or localhost defaults.
  }
}

function gatewayConfig() {
  loadEnvFile();
  return {
    baseUrl: (process.env.MEMORY_GATEWAY_URL || DEFAULT_GATEWAY_URL).replace(/\/+$/, ""),
    token: process.env.MEMORY_GATEWAY_TOKEN || "",
    adminToken: process.env.MEMORY_ADMIN_TOKEN || "",
    agent: process.env.MEMORY_AGENT_NAME || DEFAULT_AGENT,
  };
}

function stateDir() {
  loadEnvFile();
  return process.env.MEMORY_PLUGIN_STATE_DIR || path.join(os.homedir(), ".config", "memory-hub", "opencode-plugin");
}

function debugLog(message, data = {}) {
  if (!process.env.MEMORY_HUB_HOOK_DEBUG) return;
  try {
    const filePath = path.join(stateDir(), "hook-debug.log");
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.appendFileSync(filePath, `${new Date().toISOString()} ${message} ${JSON.stringify(data)}\n`, "utf8");
  } catch {
    // Debug logging must never affect sessions.
  }
}

function compactJson(value) {
  return JSON.stringify(value);
}

function responsePreview(text) {
  const flattened = String(text || "").replace(/\s+/g, " ").trim();
  return flattened.length > 300 ? `${flattened.slice(0, 299)}…` : flattened;
}

function clip(value, limit = 240) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}

function textFromValue(value) {
  if (value == null) return "";
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value)) return value.map(textFromValue).filter(Boolean).join("\n").trim();
  if (typeof value === "object") {
    for (const key of ["text", "content", "message", "body", "value", "parts"]) {
      const text = textFromValue(value[key]);
      if (text) return text;
    }
  }
  return "";
}

function latestMessageText(value, roles) {
  const messages = Array.isArray(value?.messages)
    ? value.messages
    : Array.isArray(value?.message)
      ? value.message
      : [];
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    const role = String(message?.role || message?.type || message?.source || "").toLowerCase();
    if (roles.some((candidate) => role.includes(candidate))) {
      return textFromValue(message);
    }
  }
  return "";
}

function extractPrompt(value) {
  for (const key of ["prompt", "userPrompt", "user_prompt", "lastUserMessage", "last_user_message", "input"]) {
    const text = textFromValue(value?.[key]);
    if (text) return text;
  }
  return latestMessageText(value, ["user"]);
}

function extractAssistant(value) {
  for (const key of [
    "lastAssistantMessage",
    "last_assistant_message",
    "lastAgentMessage",
    "last_agent_message",
    "assistantMessage",
    "response",
    "output",
  ]) {
    const text = textFromValue(value?.[key]);
    if (text) return text;
  }
  return latestMessageText(value, ["assistant", "agent"]);
}

function sessionIdFromEvent(event) {
  return String(
    event?.sessionID ||
      event?.sessionId ||
      event?.session_id ||
      event?.session?.id ||
      event?.conversationId ||
      event?.conversation_id ||
      "default"
  );
}

function sessionStateFile(sessionId) {
  return path.join(stateDir(), "turns", `${sessionId.replace(/[^a-zA-Z0-9._-]/g, "_")}.json`);
}

function readSessionState(sessionId) {
  try {
    return JSON.parse(fs.readFileSync(sessionStateFile(sessionId), "utf8"));
  } catch {
    return {};
  }
}

function writeSessionState(sessionId, payload) {
  const filePath = sessionStateFile(sessionId);
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2), "utf8");
}

async function captureEventMemory(event) {
  const eventType = String(event?.type || event?.name || "");
  const sessionId = sessionIdFromEvent(event);
  const prior = readSessionState(sessionId);
  const prompt = extractPrompt(event) || prior.prompt || "";
  const assistant = extractAssistant(event) || prior.assistant || "";

  if (prompt || assistant) {
    writeSessionState(sessionId, {
      prompt,
      assistant,
      updatedAt: new Date().toISOString(),
      eventType,
    });
  }

  if (!/(idle|complete|completed|finish|finished|compact)/i.test(eventType)) return;
  if (!prompt && !assistant) return;

  const signature = `${prompt}\n---\n${assistant}`;
  if (storedSignatures.get(sessionId) === signature || prior.lastStoredSignature === signature) return;

  await gatewayRequest("/v1/memories", {
    method: "POST",
    body: {
      content: [
        "OpenCode turn episode",
        `Prompt: ${clip(prompt, 800) || "(not available)"}`,
        `Assistant: ${clip(assistant, 1000) || "(not available)"}`,
      ].join("\n"),
      category: "agent",
      kind: "episode",
      importance: 0.25,
      confidence: 0.7,
      retention: "normal",
      source_agent: gatewayConfig().agent,
      metadata: {
        source: "opencode-plugin",
        hook_event: eventType || "event",
        session_id: sessionId,
        prompt_excerpt: clip(prompt, 240),
        assistant_excerpt: clip(assistant, 240),
        raw_event_keys: Object.keys(event || {}).slice(0, 40).join(","),
      },
    },
  });

  storedSignatures.set(sessionId, signature);
  writeSessionState(sessionId, {
    prompt,
    assistant,
    updatedAt: new Date().toISOString(),
    eventType,
    lastStoredSignature: signature,
  });
}

async function readJsonResponse(response, path) {
  const text = await response.text();
  const contentType = response.headers.get("content-type") || "";
  if (!response.ok) {
    throw new Error(
      `Gateway ${response.status} ${response.statusText}${text ? `: ${responsePreview(text)}` : ""}`
    );
  }

  if (!text) {
    return {};
  }

  if (!contentType.includes("application/json")) {
    throw new Error(
      `Gateway ${path} returned ${contentType || "unknown content type"} instead of JSON: ${responsePreview(text)}`
    );
  }

  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`Gateway ${path} returned invalid JSON: ${error.message}. Body: ${responsePreview(text)}`);
  }
}

function parseJsonValue(value, fallback) {
  if (value == null || value === "") {
    return fallback;
  }
  try {
    return JSON.parse(value);
  } catch (error) {
    throw new Error(`Invalid JSON: ${error.message}`);
  }
}

function parseCategories(value) {
  if (!value) {
    return [];
  }
  return value
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
}

async function gatewayRequest(path, { method = "GET", body, admin = false, auth = true } = {}) {
  const { baseUrl, token, adminToken } = gatewayConfig();
  const authToken = auth ? (admin ? adminToken || token : token) : "";
  if (auth && !authToken) {
    throw new Error("MEMORY_GATEWAY_TOKEN is required");
  }

  const candidates = [baseUrl];
  const hostname = (() => {
    try {
      return new URL(baseUrl).hostname;
    } catch {
      return "";
    }
  })();
  if (hostname && hostname !== "127.0.0.1" && hostname !== "localhost") {
    candidates.push(DEFAULT_GATEWAY_URL);
  }

  let lastError;
  for (const candidate of candidates) {
    try {
      const response = await fetch(`${candidate}${path}`, {
        method,
        headers: {
          ...(auth ? { Authorization: `Bearer ${authToken}` } : {}),
          ...(body ? { "Content-Type": "application/json" } : {}),
          Accept: "application/json",
        },
        body: body ? JSON.stringify(body) : undefined,
      });
      return await readJsonResponse(response, path);
    } catch (error) {
      lastError = error;
      const cause = error?.cause?.code || error?.code || "";
      if (!["EAI_AGAIN", "ENOTFOUND", "ECONNREFUSED", "ECONNRESET", "ETIMEDOUT"].includes(cause)) {
        throw error;
      }
    }
  }
  throw lastError || new Error("Gateway request failed");
}

function memoryOutput(payload) {
  return compactJson(payload);
}

function memoryTools() {
  return {
    memory_health: tool({
      description: "Check whether Memory Hub is reachable.",
      args: {},
      async execute() {
        return memoryOutput(await gatewayRequest("/health", { auth: false }));
      },
    }),
    memory_recall: tool({
      description: "Recall relevant memories from Memory Hub.",
      args: {
        query: tool.schema.string(),
        categories: tool.schema.string().optional(),
        limit: tool.schema.number().optional(),
        includeInactive: tool.schema.boolean().optional(),
        metadata: tool.schema.string().optional(),
      },
      async execute(args) {
        const categories = parseCategories(args.categories || "");
        const metadata = parseJsonValue(args.metadata || "", {});
        return memoryOutput(
          await gatewayRequest("/v1/recall", {
            method: "POST",
            body: {
              query: args.query,
              categories: categories.length ? categories : DEFAULT_CATEGORIES,
              limit: args.limit ?? 8,
              include_inactive: args.includeInactive ?? false,
              metadata,
            },
          })
        );
      },
    }),
    memory_store: tool({
      description: "Store a durable memory in Memory Hub.",
      args: {
        content: tool.schema.string(),
        category: tool.schema.string().optional(),
        kind: tool.schema.string().optional(),
        importance: tool.schema.number().optional(),
        confidence: tool.schema.number().optional(),
        retention: tool.schema.string().optional(),
        sourceAgent: tool.schema.string().optional(),
        metadata: tool.schema.string().optional(),
      },
      async execute(args) {
        const metadata = parseJsonValue(args.metadata || "", {});
        return memoryOutput(
          await gatewayRequest("/v1/memories", {
            method: "POST",
            body: {
              content: args.content,
              category: args.category || "agent",
              kind: args.kind || "fact",
              importance: args.importance ?? 0.5,
              confidence: args.confidence ?? 0.8,
              retention: args.retention || "normal",
              source_agent: args.sourceAgent || gatewayConfig().agent,
              metadata,
            },
          })
        );
      },
    }),
    memory_list: tool({
      description: "List recent memories in a category.",
      args: {
        category: tool.schema.string().optional(),
        limit: tool.schema.number().optional(),
        offset: tool.schema.number().optional(),
        includeInactive: tool.schema.boolean().optional(),
      },
      async execute(args) {
        const category = args.category || "agent";
        const params = new URLSearchParams({
          limit: String(args.limit ?? 25),
          offset: String(args.offset ?? 0),
          include_inactive: String(args.includeInactive ?? false),
        });
        return memoryOutput(await gatewayRequest(`/v1/memories/${encodeURIComponent(category)}?${params}`));
      },
    }),
    memory_patch: tool({
      description: "Patch memory content or metadata.",
      args: {
        category: tool.schema.string(),
        memoryId: tool.schema.string(),
        content: tool.schema.string().optional(),
        sourceAgent: tool.schema.string().optional(),
        metadata: tool.schema.string().optional(),
      },
      async execute(args) {
        const metadata = parseJsonValue(args.metadata || "", {});
        return memoryOutput(
          await gatewayRequest(`/v1/memories/${encodeURIComponent(args.category)}/${encodeURIComponent(args.memoryId)}`, {
            method: "PATCH",
            body: {
              content: args.content ?? null,
              source_agent: args.sourceAgent || gatewayConfig().agent,
              metadata,
            },
          })
        );
      },
    }),
    memory_archive: tool({
      description: "Archive a memory so it stops showing up in normal recall.",
      args: {
        category: tool.schema.string(),
        memoryId: tool.schema.string(),
        reason: tool.schema.string(),
        sourceAgent: tool.schema.string().optional(),
      },
      async execute(args) {
        return memoryOutput(
          await gatewayRequest(
            `/v1/memories/${encodeURIComponent(args.category)}/${encodeURIComponent(args.memoryId)}/archive`,
            {
              method: "POST",
              body: {
                reason: args.reason,
                source_agent: args.sourceAgent || gatewayConfig().agent,
              },
            }
          )
        );
      },
    }),
    memory_forget: tool({
      description: "Soft-delete a memory from normal recall.",
      args: {
        category: tool.schema.string(),
        memoryId: tool.schema.string(),
        reason: tool.schema.string(),
        sourceAgent: tool.schema.string().optional(),
      },
      async execute(args) {
        return memoryOutput(
          await gatewayRequest(
            `/v1/memories/${encodeURIComponent(args.category)}/${encodeURIComponent(args.memoryId)}/forget`,
            {
              method: "POST",
              body: {
                reason: args.reason,
                source_agent: args.sourceAgent || gatewayConfig().agent,
              },
            }
          )
        );
      },
    }),
    memory_supersede: tool({
      description: "Create a replacement memory and archive the prior one.",
      args: {
        previousCategory: tool.schema.string(),
        previousId: tool.schema.string(),
        content: tool.schema.string(),
        category: tool.schema.string().optional(),
        kind: tool.schema.string().optional(),
        sourceAgent: tool.schema.string().optional(),
        reason: tool.schema.string().optional(),
      },
      async execute(args) {
        return memoryOutput(
          await gatewayRequest("/v1/memories/supersede", {
            method: "POST",
            body: {
              previous_category: args.previousCategory,
              previous_id: args.previousId,
              content: args.content,
              category: args.category || "agent",
              kind: args.kind || "fact",
              source_agent: args.sourceAgent || gatewayConfig().agent,
              reason: args.reason || "Superseded by a corrected or newer memory",
            },
          })
        );
      },
    }),
    memory_overview: tool({
      description: "Return category counts and a recent memory sample.",
      args: {
        sampleLimit: tool.schema.number().optional(),
      },
      async execute(args) {
        const params = new URLSearchParams({ sample_limit: String(args.sampleLimit ?? 10) });
        return memoryOutput(await gatewayRequest(`/v1/overview?${params}`));
      },
    }),
    memory_queue_status: tool({
      description: "Return embedding and enrichment backlog counts.",
      args: {},
      async execute() {
        return memoryOutput(await gatewayRequest("/v1/queue-status"));
      },
    }),
  };
}

export const MemoryHubPlugin = async ({ client }) => {
  return {
    tool: memoryTools(),
    event: async ({ event }) => {
      try {
        await captureEventMemory(event);
      } catch (error) {
        debugLog("event capture failed", { error: error?.message || String(error), keys: Object.keys(event || {}) });
      }

      if (event?.type === "session.idle") {
        try {
          const queue = await gatewayRequest("/v1/queue-status");
          await client.app.log({
            body: {
              service: "memory-hub",
              level: "info",
              message: "Session idle; memory queue snapshot refreshed.",
              extra: {
                embedding_pending: queue.embedding_pending ?? queue.embedding ?? null,
                enrichment_pending: queue.enrichment_pending ?? queue.enrichment ?? null,
              },
            },
          });
        } catch {
          // Keep sessions running even if the gateway is temporarily unavailable.
        }
      }
    },
    "experimental.session.compacting": async (input, output) => {
      try {
        const [queue, overview] = await Promise.all([
          gatewayRequest("/v1/queue-status"),
          gatewayRequest("/v1/overview?sample_limit=5"),
        ]);
        const categoryLines = (overview.categories || [])
          .map(
            (category) =>
              `- ${category.category}: loaded=${category.loaded}, active=${category.active}, sample_limit=${category.sample_limit}`
          )
          .join("\n");
        output.context.push(
          `\n## Memory Hub\n` +
            `Use memory_recall before answering if the task benefits from prior context.\n` +
            `Store durable facts, preferences, decisions, and procedures after they are confirmed.\n` +
            `Backlog: embedding=${queue.embedding_pending ?? queue.embedding ?? "unknown"}, enrichment=${queue.enrichment_pending ?? queue.enrichment ?? "unknown"}.\n` +
            `Recent categories:\n${categoryLines || "- none"}\n`
        );
      } catch {
        output.context.push(
          `\n## Memory Hub\n` +
            `Use memory_recall before answering if the task benefits from prior context.\n` +
            `Store durable facts, preferences, decisions, and procedures after they are confirmed.\n`
        );
      }
    },
  };
};
