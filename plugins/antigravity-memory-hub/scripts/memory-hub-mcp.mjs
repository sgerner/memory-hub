#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import * as z from "zod";

const DEFAULT_GATEWAY_URL = "http://127.0.0.1:3112";
const DEFAULT_AGENT = "antigravity";
const DEFAULT_CATEGORIES = ["agent", "emails", "obsidian", "documents", "code"];

function config() {
  return {
    baseUrl: (process.env.MEMORY_GATEWAY_URL || DEFAULT_GATEWAY_URL).replace(/\/+$/, ""),
    token: process.env.MEMORY_GATEWAY_TOKEN || "",
    adminToken: process.env.MEMORY_ADMIN_TOKEN || "",
    agent: process.env.MEMORY_AGENT_NAME || DEFAULT_AGENT,
  };
}

function parseJson(value, fallback) {
  if (value == null) {
    return fallback;
  }
  return value;
}

function parseCategories(value) {
  if (!value || !value.length) {
    return [];
  }
  return value;
}

async function gatewayRequest(path, { method = "GET", body, admin = false, auth = true } = {}) {
  const { baseUrl, token, adminToken } = config();
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

function textResult(payload) {
  return { content: [{ type: "text", text: JSON.stringify(payload) }] };
}

const server = new McpServer({
  name: "memory-hub",
  version: "0.1.0",
});

server.registerTool(
  "memory_health",
  {
    description: "Check whether Memory Hub is reachable.",
    inputSchema: z.object({}),
  },
  async () => textResult(await gatewayRequest("/health", { auth: false }))
);

server.registerTool(
  "memory_recall",
  {
    description: "Recall relevant memories from Memory Hub.",
    inputSchema: z.object({
      query: z.string(),
      categories: z.array(z.string()).optional(),
      limit: z.number().int().min(1).max(50).optional(),
      includeInactive: z.boolean().optional(),
      metadata: z.any().optional(),
    }),
  },
  async ({ query, categories, limit, includeInactive, metadata }) =>
    textResult(
      await gatewayRequest("/v1/recall", {
        method: "POST",
        body: {
          query,
          categories: parseCategories(categories).length ? categories : DEFAULT_CATEGORIES,
          limit: limit ?? 8,
          include_inactive: includeInactive ?? false,
          metadata: parseJson(metadata, {}),
        },
      })
    )
);

server.registerTool(
  "memory_store",
  {
    description: "Store a durable memory in Memory Hub.",
    inputSchema: z.object({
      content: z.string(),
      category: z.string().default("agent"),
      kind: z.string().default("fact"),
      importance: z.number().min(0).max(1).optional(),
      confidence: z.number().min(0).max(1).optional(),
      retention: z.string().default("normal"),
      sourceAgent: z.string().default(DEFAULT_AGENT),
      metadata: z.any().optional(),
    }),
  },
  async ({ content, category, kind, importance, confidence, retention, sourceAgent, metadata }) =>
    textResult(
      await gatewayRequest("/v1/memories", {
        method: "POST",
        body: {
          content,
          category,
          kind,
          importance: importance ?? 0.5,
          confidence: confidence ?? 0.8,
          retention,
          source_agent: sourceAgent,
          metadata: parseJson(metadata, {}),
        },
      })
    )
);

server.registerTool(
  "memory_list",
  {
    description: "List recent memories in a category.",
    inputSchema: z.object({
      category: z.string().default("agent"),
      limit: z.number().int().min(1).max(250).optional(),
      offset: z.number().int().min(0).optional(),
      includeInactive: z.boolean().optional(),
    }),
  },
  async ({ category, limit, offset, includeInactive }) =>
    textResult(
      await gatewayRequest(
        `/v1/memories/${encodeURIComponent(category)}?${new URLSearchParams({
          limit: String(limit ?? 25),
          offset: String(offset ?? 0),
          include_inactive: String(includeInactive ?? false),
        })}`
      )
    )
);

server.registerTool(
  "memory_patch",
  {
    description: "Patch memory content or metadata.",
    inputSchema: z.object({
      category: z.string(),
      memoryId: z.string(),
      content: z.string().optional(),
      sourceAgent: z.string().default(DEFAULT_AGENT),
      metadata: z.any().optional(),
    }),
  },
  async ({ category, memoryId, content, sourceAgent, metadata }) =>
    textResult(
      await gatewayRequest(`/v1/memories/${encodeURIComponent(category)}/${encodeURIComponent(memoryId)}`, {
        method: "PATCH",
        body: {
          content: content ?? null,
          source_agent: sourceAgent,
          metadata: parseJson(metadata, {}),
        },
      })
    )
);

server.registerTool(
  "memory_archive",
  {
    description: "Archive a memory so it stops showing up in normal recall.",
    inputSchema: z.object({
      category: z.string(),
      memoryId: z.string(),
      reason: z.string(),
      sourceAgent: z.string().default(DEFAULT_AGENT),
    }),
  },
  async ({ category, memoryId, reason, sourceAgent }) =>
    textResult(
      await gatewayRequest(
        `/v1/memories/${encodeURIComponent(category)}/${encodeURIComponent(memoryId)}/archive`,
        {
          method: "POST",
          body: {
            reason,
            source_agent: sourceAgent,
          },
        }
      )
    )
);

server.registerTool(
  "memory_forget",
  {
    description: "Soft-delete a memory from normal recall.",
    inputSchema: z.object({
      category: z.string(),
      memoryId: z.string(),
      reason: z.string(),
      sourceAgent: z.string().default(DEFAULT_AGENT),
    }),
  },
  async ({ category, memoryId, reason, sourceAgent }) =>
    textResult(
      await gatewayRequest(
        `/v1/memories/${encodeURIComponent(category)}/${encodeURIComponent(memoryId)}/forget`,
        {
          method: "POST",
          body: {
            reason,
            source_agent: sourceAgent,
          },
        }
      )
    )
);

server.registerTool(
  "memory_supersede",
  {
    description: "Create a replacement memory and mark the old one superseded.",
    inputSchema: z.object({
      previousCategory: z.string(),
      previousId: z.string(),
      content: z.string(),
      category: z.string().default("agent"),
      kind: z.string().default("fact"),
      sourceAgent: z.string().default(DEFAULT_AGENT),
      reason: z.string().default("updated memory"),
      metadata: z.any().optional(),
      importance: z.number().min(0).max(1).optional(),
      confidence: z.number().min(0).max(1).optional(),
      retention: z.string().default("normal"),
    }),
  },
  async ({ previousCategory, previousId, content, category, kind, sourceAgent, reason, metadata, importance, confidence, retention }) =>
    textResult(
      await gatewayRequest("/v1/memories/supersede", {
        method: "POST",
        body: {
          previous_category: previousCategory,
          previous_id: previousId,
          content,
          category,
          kind,
          source_agent: sourceAgent,
          reason,
          metadata: parseJson(metadata, {}),
          importance: importance ?? 0.5,
          confidence: confidence ?? 0.8,
          retention,
        },
      })
    )
);

server.registerTool(
  "memory_overview",
  {
    description: "Summarize current memories and backlog health.",
    inputSchema: z.object({
      sampleLimit: z.number().int().min(1).max(50).optional(),
    }),
  },
  async ({ sampleLimit }) =>
    textResult(
      await gatewayRequest(`/v1/overview?${new URLSearchParams({ sample_limit: String(sampleLimit ?? 10) })}`)
    )
);

server.registerTool(
  "memory_queue_status",
  {
    description: "Inspect the current queue backlog.",
    inputSchema: z.object({}),
  },
  async () => textResult(await gatewayRequest("/v1/queue-status"))
);

server.registerTool(
  "memory_purge",
  {
    description: "Permanently delete a memory from the database.",
    inputSchema: z.object({
      category: z.string(),
      memoryId: z.string(),
      sourceAgent: z.string().default(DEFAULT_AGENT),
    }),
  },
  async ({ category, memoryId }) =>
    textResult(
      await gatewayRequest(`/v1/memories/${encodeURIComponent(category)}/${encodeURIComponent(memoryId)}`, {
        method: "DELETE",
        admin: true,
      })
    )
);

await server.connect(new StdioServerTransport());
