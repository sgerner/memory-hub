#!/usr/bin/env node

const args = process.argv.slice(2);

function fail(message) {
  console.error(`memorex: ${message}`);
  process.exitCode = 1;
}

function usage() {
  console.log(`Usage:
  memorex health
  memorex overview [--limit <number>]
  memorex queue
  memorex recall <query> [--category <name>] [--limit <number>] [--inactive] [--recency-decay <number>] [--filter key:op:value]
  memorex list <category> [--limit <number>] [--offset <number>] [--inactive]
  memorex get <category> <id>
  memorex store <content> [--category agent] [--kind fact] [--importance 0.5] [--confidence 0.8] [--retention normal] [--agent <name>] [--related-to <id1,id2>]
  memorex patch <category> <id> [--content <text>] [--agent <name>] [--meta key=value] [--related-to <id1,id2>]
  memorex supersede <category> <id> <content> [--new-category agent] [--kind fact] [--reason <text>] [--agent <name>]
  memorex archive <category> <id> --reason <text> [--agent <name>]
  memorex forget <category> <id> --reason <text> [--agent <name>]

Configuration:
  MEMOREX_URL       Gateway base URL, for example https://your-memory-domain.example
  MEMOREX_TOKEN     Agent gateway bearer token
  --url / --token   Overrides the corresponding environment variable`);
}

function parse(tokens) {
  const positional = [];
  const options = {};
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (!token.startsWith("--")) {
      positional.push(token);
      continue;
    }
    const key = token.slice(2);
    if (["inactive", "json"].includes(key)) {
      options[key] = true;
      continue;
    }
    const value = tokens[index + 1];
    if (value === undefined || value.startsWith("--")) {
      throw new Error(`--${key} requires a value`);
    }
    index += 1;
    if (key === "meta" || key === "filter") {
      options[key] ??= [];
      options[key].push(value);
    } else {
      options[key] = value;
    }
  }
  return { positional, options };
}

function metadata(values = []) {
  return Object.fromEntries(values.map((pair) => {
    const separator = pair.indexOf("=");
    if (separator < 1) {
      throw new Error(`metadata must be key=value: ${pair}`);
    }
    return [pair.slice(0, separator), pair.slice(separator + 1)];
  }));
}

function optionNumber(options, key, fallback) {
  if (options[key] === undefined) return fallback;
  const value = Number(options[key]);
  if (!Number.isFinite(value)) {
    throw new Error(`--${key} must be a number`);
  }
  return value;
}

async function request(path, method, body, config) {
  const headers = { Accept: "application/json" };
  if (config.token) {
    headers.Authorization = `Bearer ${config.token}`;
  }
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(`${config.url}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const responseBody = await response.text();
  let value;
  try {
    value = responseBody ? JSON.parse(responseBody) : {};
  } catch {
    value = { message: responseBody };
  }
  if (!response.ok) {
    throw new Error(`${response.status} ${value.detail ?? value.message ?? response.statusText}`);
  }
  return value;
}

async function main() {
  if (!args.length || args.includes("--help") || args.includes("-h")) {
    usage();
    return;
  }

  const command = args[0];
  const { positional, options } = parse(args.slice(1));
  const config = {
    url: (options.url ?? process.env.MEMOREX_URL ?? "http://127.0.0.1:3112").replace(/\/$/, ""),
    token: options.token ?? process.env.MEMOREX_TOKEN,
  };
  if (command !== "health" && !config.token) {
    throw new Error("set MEMOREX_TOKEN or pass --token");
  }

  let result;
  switch (command) {
    case "health":
      result = await request("/health", "GET", undefined, config);
      break;
    case "overview":
      result = await request(
        `/v1/overview?sample_limit=${encodeURIComponent(optionNumber(options, "limit", 10))}`,
        "GET",
        undefined,
        config,
      );
      break;
    case "queue":
      result = await request("/v1/queue-status", "GET", undefined, config);
      break;
    case "recall":
      if (!positional[0]) throw new Error("recall requires a query");
      result = await request("/v1/recall", "POST", {
        query: positional[0],
        categories: options.category ? [options.category] : undefined,
        limit: options.limit ? optionNumber(options, "limit") : undefined,
        include_inactive: Boolean(options.inactive),
        metadata: metadata(options.meta),
        recency_decay: options["recency-decay"] ? optionNumber(options, "recency-decay") : undefined,
        filters: options.filter ? options.filter.map(f => {
          const parts = f.split(':');
          return { key: parts[0], op: parts[1], value: parts.slice(2).join(':') };
        }) : undefined,
      }, config);
      break;
    case "list":
      if (!positional[0]) throw new Error("list requires a category");
      result = await request(
        `/v1/memories/${encodeURIComponent(positional[0])}?limit=${encodeURIComponent(optionNumber(options, "limit", 25))}&offset=${encodeURIComponent(optionNumber(options, "offset", 0))}&include_inactive=${Boolean(options.inactive)}`,
        "GET",
        undefined,
        config,
      );
      break;
    case "get":
      if (!positional[0] || !positional[1]) throw new Error("get requires category and id");
      result = await request(
        `/v1/memories/${encodeURIComponent(positional[0])}/${encodeURIComponent(positional[1])}`,
        "GET",
        undefined,
        config,
      );
      break;
    case "store":
      if (!positional[0]) throw new Error("store requires content");
      result = await request("/v1/memories", "POST", {
        content: positional[0],
        category: options.category,
        kind: options.kind,
        importance: options.importance ? optionNumber(options, "importance") : undefined,
        confidence: options.confidence ? optionNumber(options, "confidence") : undefined,
        retention: options.retention,
        source_agent: options.agent,
        metadata: metadata(options.meta),
        related_to: options["related-to"] ? options["related-to"].split(",") : undefined,
      }, config);
      break;
    case "patch":
      if (!positional[0] || !positional[1]) throw new Error("patch requires category and id");
      result = await request(`/v1/memories/${encodeURIComponent(positional[0])}/${encodeURIComponent(positional[1])}`, "PATCH", {
        content: options.content,
        source_agent: options.agent,
        metadata: metadata(options.meta),
        related_to: options["related-to"] ? options["related-to"].split(",") : undefined,
      }, config);
      break;
    case "supersede":
      if (!positional[0] || !positional[1] || !positional[2]) {
        throw new Error("supersede requires category, id, and new content");
      }
      result = await request("/v1/memories/supersede", "POST", {
        previous_category: positional[0],
        previous_id: positional[1],
        content: positional[2],
        category: options["new-category"],
        kind: options.kind,
        reason: options.reason,
        source_agent: options.agent,
      }, config);
      break;
    case "archive":
    case "forget":
      if (!positional[0] || !positional[1] || !options.reason) {
        throw new Error(`${command} requires category, id, and --reason`);
      }
      result = await request(
        `/v1/memories/${encodeURIComponent(positional[0])}/${encodeURIComponent(positional[1])}/${command}`,
        "POST",
        { reason: options.reason, source_agent: options.agent },
        config,
      );
      break;
    default:
      throw new Error(`unknown command: ${command}`);
  }
  console.log(JSON.stringify(result, null, 2));
}

main().catch((error) => fail(error.message));
