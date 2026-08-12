const OPENSEARCH_INFO_MESSAGES = [
  "Connected OpenSearch version:",
  "Applied tool filter from environment variables",
  "Enabled tools:",
];

export function formatBackendStderrLine(line, { verboseMcp = false } = {}) {
  if (verboseMcp) {
    return line;
  }

  const record = parseStructuredLog(line);
  if (record === null) {
    return line;
  }

  const { level, logger, message } = record;
  if (logger === "opensearch.helper" && message.startsWith("Error getting OpenSearch version:")) {
    return `Optional MCP server 'opensearch' endpoint check failed: ${message
      .slice("Error getting OpenSearch version:".length)
      .trim()}`;
  }
  if (isOpenSearchConnectionNoise(logger, message)) {
    return null;
  }
  if (
    level === "INFO" &&
    (logger === "mcp_server_opensearch" ||
      logger.startsWith("opensearch.") ||
      logger === "opensearch" ||
      logger.startsWith("mcp.server.") ||
      (logger === "root" && OPENSEARCH_INFO_MESSAGES.some((prefix) => message.startsWith(prefix))))
  ) {
    return null;
  }

  return line;
}

export function pipeBackendStderr(source, destination, options = {}) {
  let pending = "";
  source.setEncoding("utf8");
  source.on("data", (chunk) => {
    pending += chunk;
    const lines = pending.split(/\r?\n/);
    pending = lines.pop() ?? "";
    for (const line of lines) {
      writeFormattedLine(destination, line, options);
    }
  });
  source.on("end", () => {
    if (pending) {
      writeFormattedLine(destination, pending, options);
    }
  });
}

function parseStructuredLog(line) {
  let value;
  try {
    value = JSON.parse(line);
  } catch {
    return null;
  }
  if (
    value === null ||
    typeof value !== "object" ||
    typeof value.level !== "string" ||
    typeof value.logger !== "string" ||
    typeof value.message !== "string"
  ) {
    return null;
  }
  return value;
}

function isOpenSearchConnectionNoise(logger, message) {
  if (logger === "opensearch.connection") {
    return message.startsWith("Streaming request failed") || message.startsWith("OpenSearch request failed");
  }
  return logger === "opensearch" && message.startsWith("GET ") && message.includes("status:N/A");
}

function writeFormattedLine(destination, line, options) {
  const formatted = formatBackendStderrLine(line, options);
  if (formatted !== null) {
    destination.write(`${formatted}\n`);
  }
}
