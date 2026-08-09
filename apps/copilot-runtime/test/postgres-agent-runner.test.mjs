import assert from "node:assert/strict";
import test from "node:test";
import { EventType } from "@ag-ui/client";
import { PostgresAgentRunner } from "../src/postgres-agent-runner.mjs";

test("PostgresAgentRunner replays a completed run after a new runner is created", async () => {
  const pool = new FakePool();
  const threadId = "7c62088b-a7cc-46de-ad05-d90ec36bf21f";
  const runId = "run-1";
  const agent = new FakeAgent(threadId, runId);
  const firstRunner = new PostgresAgentRunner({ pool, setupOnStart: false });
  await firstRunner.initialize();

  const liveEvents = await collectEvents(
    firstRunner.run({
      agent,
      input: { threadId, runId, messages: [{ id: "user-1", role: "user", content: "hello" }] },
      threadId,
    }),
  );
  assert.equal(liveEvents.at(0)?.type, EventType.RUN_STARTED);
  assert.equal(liveEvents.at(-1)?.type, EventType.RUN_FINISHED);
  await firstRunner.close();

  const secondRunner = new PostgresAgentRunner({ pool, setupOnStart: false });
  await secondRunner.initialize();
  const replayedEvents = await collectEvents(secondRunner.connect({ threadId }));
  assert.deepEqual(replayedEvents, liveEvents);
  assert.equal(await secondRunner.isRunning({ threadId }), false);
  await secondRunner.close();
});

class FakeAgent {
  agentId = "agent";
  messages = [];

  constructor(threadId, runId) {
    this.threadId = threadId;
    this.runId = runId;
  }

  async runAgent(input, { onEvent }) {
    const events = [
      { type: EventType.RUN_STARTED, threadId: this.threadId, runId: this.runId },
      { type: EventType.TEXT_MESSAGE_START, messageId: "assistant-1", role: "assistant" },
      { type: EventType.TEXT_MESSAGE_CONTENT, messageId: "assistant-1", delta: "hi" },
      { type: EventType.TEXT_MESSAGE_END, messageId: "assistant-1" },
      { type: EventType.RUN_FINISHED, threadId: this.threadId, runId: this.runId },
    ];
    for (const event of events) {
      onEvent({ event });
    }
    this.messages = [...input.messages, { id: "assistant-1", role: "assistant", content: "hi" }];
  }

  abortRun() {}
}

class FakePool {
  events = [];
  locks = new Map();
  runs = new Map();

  async query(sql, values = []) {
    const statement = sql.replace(/\s+/g, " ").trim();
    if (statement === "SELECT 1") {
      return { rowCount: 1, rows: [{ "?column?": 1 }] };
    }
    if (statement.startsWith("SELECT r.thread_id")) {
      return { rowCount: 0, rows: [] };
    }
    if (statement.startsWith("DELETE FROM copilotkit_thread_locks WHERE expires_at")) {
      return { rowCount: 0, rows: [] };
    }
    if (statement.startsWith("INSERT INTO copilotkit_thread_locks")) {
      const [threadId, runId] = values;
      if (this.locks.has(threadId)) {
        return { rowCount: 0, rows: [] };
      }
      this.locks.set(threadId, runId);
      return { rowCount: 1, rows: [{ run_id: runId }] };
    }
    if (statement.startsWith("INSERT INTO copilotkit_agent_runs")) {
      const [threadId, runId, agentId, input] = values;
      this.runs.set(runId, { agentId, createdAt: Date.now(), input: JSON.parse(input), status: "running", threadId });
      return { rowCount: 1, rows: [] };
    }
    if (statement.startsWith("SELECT messages")) {
      return { rowCount: 0, rows: [] };
    }
    if (statement.startsWith("INSERT INTO copilotkit_run_events")) {
      for (let index = 0; index < values.length; index += 5) {
        this.events.push({
          threadId: values[index],
          runId: values[index + 1],
          sequence: values[index + 2],
          event: JSON.parse(values[index + 3]),
        });
      }
      return { rowCount: values.length / 5, rows: [] };
    }
    if (statement.startsWith("UPDATE copilotkit_agent_runs SET messages")) {
      const [runId, messages, status] = values;
      Object.assign(this.runs.get(runId), { messages: JSON.parse(messages), status });
      return { rowCount: 1, rows: [] };
    }
    if (statement.startsWith("DELETE FROM copilotkit_thread_locks WHERE thread_id")) {
      const [threadId, runId] = values;
      if (this.locks.get(threadId) === runId) {
        this.locks.delete(threadId);
      }
      return { rowCount: 1, rows: [] };
    }
    if (statement.startsWith("SELECT e.event")) {
      const [threadId] = values;
      const rows = this.events
        .filter((entry) => entry.threadId === threadId)
        .sort((left, right) => {
          const runDelta = this.runs.get(left.runId).createdAt - this.runs.get(right.runId).createdAt;
          return runDelta || left.sequence - right.sequence;
        })
        .map(({ event }) => ({ event }));
      return { rowCount: rows.length, rows };
    }
    if (statement.startsWith("SELECT EXISTS")) {
      return { rowCount: 1, rows: [{ running: this.locks.has(values[0]) }] };
    }
    if (statement.startsWith("UPDATE copilotkit_thread_locks")) {
      return { rowCount: 1, rows: [] };
    }
    throw new Error(`Unexpected SQL in fake pool: ${statement}`);
  }

  async end() {}
}

function collectEvents(observable) {
  return new Promise((resolve, reject) => {
    const events = [];
    observable.subscribe({
      next: (event) => events.push(event),
      error: reject,
      complete: () => resolve(events),
    });
  });
}
