import { expect, test } from "vitest";
import { type PersistedAppConfig, normalizeInitialAppConfig } from "./appConfigPersistence";
import { ThreadActivityGate } from "./threadActivityGate";

test("a locally generated thread id is always explicit", () => {
  const legacyConfig: PersistedAppConfig = {
    activeThreadId: "ui-thread-id",
    activeThreadSource: "local",
    desktopSidebarOpen: true,
    hasExplicitThreadId: false,
    mainView: "chat",
  };

  const normalized = normalizeInitialAppConfig(legacyConfig);

  expect(normalized.activeThreadId).toBe("ui-thread-id");
  expect(normalized.hasExplicitThreadId).toBe(true);
});

test("a new thread id is generated once and marked explicit", () => {
  const emptyConfig: PersistedAppConfig = {
    activeThreadId: undefined,
    activeThreadSource: "local",
    desktopSidebarOpen: true,
    hasExplicitThreadId: false,
    mainView: "chat",
  };

  const normalized = normalizeInitialAppConfig(emptyConfig, () => "new-ui-thread-id");

  expect(normalized.activeThreadId).toBe("new-ui-thread-id");
  expect(normalized.hasExplicitThreadId).toBe(true);
});

test("messages retained during a thread switch do not create a ghost conversation", () => {
  const gate = new ThreadActivityGate();
  const oldMessages = [{ id: "old-user", role: "user" }];

  expect(
    gate.shouldReport({ agentThreadId: "old-thread", messages: oldMessages, selectedThreadId: "old-thread" }),
  ).toBe(false);
  expect(
    gate.shouldReport({ agentThreadId: "new-thread", messages: oldMessages, selectedThreadId: "new-thread" }),
  ).toBe(false);
  expect(gate.shouldReport({ agentThreadId: "new-thread", messages: [], selectedThreadId: "new-thread" })).toBe(false);
  expect(
    gate.shouldReport({
      agentThreadId: "new-thread",
      messages: [{ id: "new-user", role: "user" }],
      selectedThreadId: "new-thread",
    }),
  ).toBe(true);
});
