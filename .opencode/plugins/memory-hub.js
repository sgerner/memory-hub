import { tool } from "@opencode-ai/plugin";

const DEFAULT_GATEWAY_URL = "http://127.0.0.1:3112";
const DEFAULT_AGENT = "opencode";
const DEFAULT_CATEGORIES = ["agent", "emails", "obsidian", "documents", "code"];

function gatewayConfig() {
  return {
    baseUrl: (process.env.MEMORY_GATEWAY_URL || DEFAULT_GATEWAY_URL).replace(/\/+$/, ""),
    token: process.env.MEMORY_GATEWAY_TOKEN || "",
    adminToken: process.env.MEMORY_ADMIN_TOKEN || "",
    agent: process.env.MEMORY_AGENT_NAME || DEFAULT_AGENT,
  };
}

function compactJson(value) {
  return JSON.stringify(value);
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
          Authorization: `Bearer ${authToken}`,
          ...(body ? { "Content-Type": "application/json" } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
      });

      const text = await response.text();
      if (!response.ok) {
        throw new Error(
          `Gateway ${response.status} ${response.statusText}${text ? `: ${text.slice(0, 1000)}` : ""}`
        );
      }

      return text ? JSON.parse(text) : {};
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
