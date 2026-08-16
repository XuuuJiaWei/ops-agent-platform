import assert from "node:assert/strict";
import test from "node:test";

import { formatBackendStderrLine } from "./dev-output.mjs";

test("collapses OpenSearch startup connection failures", () => {
  const lowLevel = JSON.stringify({
    level: "WARNING",
    logger: "opensearch",
    message: "GET https://example.invalid/ [status:N/A]",
    exception: "Traceback (most recent call last):\nClientConnectorDNSError",
  });
  const summary = JSON.stringify({
    level: "ERROR",
    logger: "opensearch.helper",
    message: "Error getting OpenSearch version: endpoint unavailable",
  });

  assert.equal(formatBackendStderrLine(lowLevel), null);
  assert.equal(
    formatBackendStderrLine(summary),
    "Optional MCP server 'opensearch' endpoint check failed: endpoint unavailable",
  );
});

test("preserves ordinary backend errors and verbose MCP diagnostics", () => {
  const traceback = "Traceback: application failure";
  const structuredBackendError = JSON.stringify({
    level: "ERROR",
    logger: "ops_pilot_platform.web.app",
    message: "application failure",
    exception: "full backend traceback",
  });
  const structured = JSON.stringify({
    level: "ERROR",
    logger: "opensearch.helper",
    message: "Error getting OpenSearch version: endpoint unavailable",
    exception: "full traceback",
  });

  assert.equal(formatBackendStderrLine(traceback), traceback);
  assert.equal(formatBackendStderrLine(structuredBackendError), structuredBackendError);
  assert.equal(formatBackendStderrLine(structured, { verboseMcp: true }), structured);
});
