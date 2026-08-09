import assert from "node:assert/strict";
import test from "node:test";
import { normalizeInitialAppConfig } from "./appConfigPersistence.ts";
import { ThreadActivityGate } from "./threadActivityGate.ts";

test("a locally generated thread id is always explicit", () => {
  const legacyConfig = {
    activeThreadId: "ui-thread-id",
    activeThreadSource: "local",
    desktopSidebarOpen: true,
    hasExplicitThreadId: false,
    mainView: "chat",
  };

  const normalized = normalizeInitialAppConfig(legacyConfig);

  assert.equal(normalized.activeThreadId, "ui-thread-id");
  assert.equal(normalized.hasExplicitThreadId, true);
});

test("a new thread id is generated once and marked explicit", () => {
  const emptyConfig = {
    activeThreadId: undefined,
    activeThreadSource: "local",
    desktopSidebarOpen: true,
    hasExplicitThreadId: false,
    mainView: "chat",
  };

  const normalized = normalizeInitialAppConfig(emptyConfig, () => "new-ui-thread-id");

  assert.equal(normalized.activeThreadId, "new-ui-thread-id");
  assert.equal(normalized.hasExplicitThreadId, true);
});

test("messages retained during a thread switch do not create a ghost conversation", () => {
  const gate = new ThreadActivityGate();
  const oldMessages = [{ id: "old-user", role: "user" }];

  assert.equal(
    gate.shouldReport({ agentThreadId: "old-thread", messages: oldMessages, selectedThreadId: "old-thread" }),
    false,
  );
  assert.equal(
    gate.shouldReport({ agentThreadId: "new-thread", messages: oldMessages, selectedThreadId: "new-thread" }),
    false,
  );
  assert.equal(gate.shouldReport({ agentThreadId: "new-thread", messages: [], selectedThreadId: "new-thread" }), false);
  assert.equal(
    gate.shouldReport({
      agentThreadId: "new-thread",
      messages: [{ id: "new-user", role: "user" }],
      selectedThreadId: "new-thread",
    }),
    true,
  );
});
