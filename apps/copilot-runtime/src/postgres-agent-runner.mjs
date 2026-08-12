import { compactEvents, EventType } from "@ag-ui/client";
import { AgentRunner, finalizeRunEvents } from "@copilotkit/runtime/v2";
import pg from "pg";
import { ReplaySubject } from "rxjs";

const { Pool } = pg;

const LOCK_TTL_SECONDS = 30;
const LOCK_HEARTBEAT_SECONDS = 10;
const INTERRUPTED_RUN_SWEEP_SECONDS = 15;
const EVENT_FLUSH_DELAY_MS = 100;

/**
 * Durable CopilotKit event runner backed by PostgreSQL.
 *
 * LangGraph's checkpointer remains the authority for graph execution state.
 * This runner stores the separate AG-UI event log needed to hydrate the chat
 * and reconnect a browser to a run by the same thread id.
 */
export class PostgresAgentRunner extends AgentRunner {
  #activeRuns = new Map();
  #pool;
  #setupOnStart;
  #sweepTimer;

  constructor({ connectionString, pool, setupOnStart = true }) {
    super();
    this.#pool = pool ?? new Pool({ connectionString: normalizeDatabaseUrl(connectionString) });
    this.#setupOnStart = setupOnStart;
  }

  async initialize() {
    if (this.#setupOnStart) {
      await this.#setup();
    }
    await this.#pool.query("SELECT 1");
    await this.#finalizeInterruptedRuns();
    this.#sweepTimer = setInterval(
      () =>
        void this.#finalizeInterruptedRuns().catch((error) =>
          console.error("Failed to finalize stale CopilotKit runs", error),
        ),
      INTERRUPTED_RUN_SWEEP_SECONDS * 1000,
    );
    this.#sweepTimer.unref?.();
  }

  run(request) {
    if (this.#activeRuns.has(request.threadId)) {
      throw new Error("Thread already running");
    }

    const subject = new ReplaySubject(Infinity);
    const activeRun = createActiveRun(request, subject);
    this.#activeRuns.set(request.threadId, activeRun);
    void this.#execute(activeRun);
    return subject.asObservable();
  }

  connect({ threadId }) {
    const subject = new ReplaySubject(Infinity);

    void (async () => {
      try {
        const result = await this.#pool.query(
          `SELECT e.event
             FROM copilotkit_run_events e
             JOIN copilotkit_agent_runs r ON r.run_id = e.run_id
            WHERE e.thread_id = $1
            ORDER BY r.created_at ASC, e.sequence ASC`,
          [threadId],
        );
        const historicEvents = compactEvents(result.rows.map((row) => row.event));
        const emittedMessageIds = new Set();
        for (const event of historicEvents) {
          subject.next(event);
          if (typeof event?.messageId === "string") {
            emittedMessageIds.add(event.messageId);
          }
        }

        const activeRun = this.#activeRuns.get(threadId);
        if (!activeRun) {
          subject.complete();
          return;
        }

        activeRun.subject.subscribe({
          next: (event) => {
            if (typeof event?.messageId === "string" && emittedMessageIds.has(event.messageId)) {
              return;
            }
            subject.next(event);
          },
          error: (error) => subject.error(error),
          complete: () => subject.complete(),
        });
      } catch (error) {
        subject.error(error);
      }
    })();

    return subject.asObservable();
  }

  async isRunning({ threadId }) {
    if (this.#activeRuns.has(threadId)) {
      return true;
    }
    const result = await this.#pool.query(
      `SELECT EXISTS (
         SELECT 1
           FROM copilotkit_thread_locks
          WHERE thread_id = $1 AND expires_at > NOW()
       ) AS running`,
      [threadId],
    );
    return result.rows[0]?.running === true;
  }

  async stop({ threadId, runId }) {
    const activeRun = this.#activeRuns.get(threadId);
    if (!activeRun || (runId !== undefined && activeRun.runId !== runId) || activeRun.stopRequested) {
      return false;
    }

    activeRun.stopRequested = true;
    activeRun.agent.abortRun();
    return true;
  }

  async close() {
    if (this.#sweepTimer) {
      clearInterval(this.#sweepTimer);
    }
    for (const activeRun of this.#activeRuns.values()) {
      activeRun.stopRequested = true;
      activeRun.agent.abortRun();
    }
    await Promise.allSettled([...this.#activeRuns.values()].map((activeRun) => activeRun.finished));
    await this.#pool.end();
  }

  async #execute(activeRun) {
    const { agent, input, runId, subject, threadId } = activeRun;
    let heartbeat;

    try {
      const acquired = await this.#acquireLock(threadId, runId);
      if (!acquired) {
        throw new Error("Thread already running");
      }

      const historicMessageIds = await this.#historicMessageIds(activeRun);

      await this.#pool.query(
        `INSERT INTO copilotkit_agent_runs
           (thread_id, run_id, agent_id, input, status, created_at, updated_at)
         VALUES ($1, $2, $3, $4::jsonb, 'running', NOW(), NOW())
         ON CONFLICT (run_id) DO NOTHING`,
        [threadId, runId, agent.agentId ?? "default", JSON.stringify(input)],
      );
      heartbeat = setInterval(
        () =>
          void this.#refreshLock(threadId, runId).catch((error) =>
            console.error("Failed to refresh CopilotKit thread lock", error),
          ),
        LOCK_HEARTBEAT_SECONDS * 1000,
      );
      heartbeat.unref?.();

      await agent.runAgent(input, {
        onEvent: ({ event }) => {
          const processedEvent = withRunInput(event, input, historicMessageIds);
          activeRun.events.push(processedEvent);
          activeRun.pendingEvents.push(processedEvent);
          subject.next(processedEvent);
          this.#scheduleFlush(activeRun);
        },
      });

      const appendedEvents = finalizeRunEvents(activeRun.events, { stopRequested: activeRun.stopRequested });
      for (const event of appendedEvents) {
        activeRun.pendingEvents.push(event);
        subject.next(event);
      }
      await this.#finishRun(activeRun, activeRun.stopRequested ? "stopped" : "completed");
      subject.complete();
    } catch (error) {
      const appendedEvents = finalizeRunEvents(activeRun.events, {
        stopRequested: activeRun.stopRequested,
        interruptionMessage: error instanceof Error ? error.message : String(error),
      });
      for (const event of appendedEvents) {
        activeRun.pendingEvents.push(event);
        subject.next(event);
      }

      if (activeRun.lockAcquired) {
        try {
          await this.#finishRun(activeRun, activeRun.stopRequested ? "stopped" : "failed");
        } catch (persistenceError) {
          console.error("Failed to persist interrupted CopilotKit run", persistenceError);
        }
        subject.complete();
      } else {
        subject.error(error);
      }
    } finally {
      if (heartbeat) {
        clearInterval(heartbeat);
      }
      if (activeRun.flushTimer) {
        clearTimeout(activeRun.flushTimer);
      }
      await this.#releaseLock(threadId, runId).catch((error) =>
        console.error("Failed to release CopilotKit thread lock", error),
      );
      this.#activeRuns.delete(threadId);
      activeRun.resolveFinished();
    }
  }

  async #finishRun(activeRun, status) {
    await this.#flushEvents(activeRun);
    await activeRun.writeChain;
    const messages = Array.isArray(activeRun.agent.messages) ? activeRun.agent.messages : [];
    await this.#pool.query(
      `UPDATE copilotkit_agent_runs
          SET messages = $2::jsonb, status = $3, updated_at = NOW()
        WHERE run_id = $1`,
      [activeRun.runId, JSON.stringify(messages), status],
    );
  }

  #scheduleFlush(activeRun) {
    if (activeRun.flushTimer) {
      return;
    }
    activeRun.flushTimer = setTimeout(() => {
      activeRun.flushTimer = undefined;
      void this.#flushEvents(activeRun).catch(() => undefined);
    }, EVENT_FLUSH_DELAY_MS);
    activeRun.flushTimer.unref?.();
  }

  async #flushEvents(activeRun) {
    if (activeRun.flushTimer) {
      clearTimeout(activeRun.flushTimer);
      activeRun.flushTimer = undefined;
    }
    if (activeRun.pendingEvents.length === 0) {
      return activeRun.writeChain;
    }

    const batch = activeRun.pendingEvents.splice(0);
    const firstSequence = activeRun.nextSequence;
    activeRun.nextSequence += batch.length;
    activeRun.writeChain = activeRun.writeChain.then(async () => {
      const values = [];
      const rows = batch.map((event, index) => {
        const offset = index * 5;
        values.push(activeRun.threadId, activeRun.runId, firstSequence + index, JSON.stringify(event), new Date());
        return `($${offset + 1}, $${offset + 2}, $${offset + 3}, $${offset + 4}::jsonb, $${offset + 5})`;
      });
      await this.#pool.query(
        `INSERT INTO copilotkit_run_events (thread_id, run_id, sequence, event, created_at)
         VALUES ${rows.join(", ")}
         ON CONFLICT (run_id, sequence) DO NOTHING`,
        values,
      );
    });
    return activeRun.writeChain;
  }

  async #acquireLock(threadId, runId) {
    const result = await this.#pool.query(
      `INSERT INTO copilotkit_thread_locks (thread_id, run_id, expires_at)
       VALUES ($1, $2, NOW() + ($3 * INTERVAL '1 second'))
       ON CONFLICT (thread_id) DO UPDATE
         SET run_id = EXCLUDED.run_id, expires_at = EXCLUDED.expires_at
       WHERE copilotkit_thread_locks.expires_at <= NOW()
       RETURNING run_id`,
      [threadId, runId, LOCK_TTL_SECONDS],
    );
    const acquired = result.rowCount === 1 && result.rows[0]?.run_id === runId;
    if (acquired) {
      const activeRun = this.#activeRuns.get(threadId);
      if (activeRun) {
        activeRun.lockAcquired = true;
      }
    }
    return acquired;
  }

  async #historicMessageIds(activeRun) {
    const persistedMessages = Array.isArray(activeRun.persistedInputMessages)
      ? activeRun.persistedInputMessages
      : (
          await this.#pool.query(
            `SELECT messages
               FROM copilotkit_agent_runs
              WHERE thread_id = $1 AND run_id <> $2
              ORDER BY created_at DESC
              LIMIT 1`,
            [activeRun.threadId, activeRun.runId],
          )
        ).rows[0]?.messages;
    return new Set((Array.isArray(persistedMessages) ? persistedMessages : []).map((message) => message.id));
  }

  async #refreshLock(threadId, runId) {
    await this.#pool.query(
      `UPDATE copilotkit_thread_locks
          SET expires_at = NOW() + ($3 * INTERVAL '1 second')
        WHERE thread_id = $1 AND run_id = $2`,
      [threadId, runId, LOCK_TTL_SECONDS],
    );
  }

  async #releaseLock(threadId, runId) {
    await this.#pool.query("DELETE FROM copilotkit_thread_locks WHERE thread_id = $1 AND run_id = $2", [
      threadId,
      runId,
    ]);
  }

  async #setup() {
    await this.#pool.query(`
      CREATE TABLE IF NOT EXISTS copilotkit_agent_runs (
        run_id TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        input JSONB NOT NULL,
        messages JSONB NOT NULL DEFAULT '[]'::jsonb,
        status TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      );
      CREATE INDEX IF NOT EXISTS copilotkit_agent_runs_thread_created_idx
        ON copilotkit_agent_runs (thread_id, created_at);

      CREATE TABLE IF NOT EXISTS copilotkit_run_events (
        thread_id TEXT NOT NULL,
        run_id TEXT NOT NULL REFERENCES copilotkit_agent_runs(run_id) ON DELETE CASCADE,
        sequence INTEGER NOT NULL,
        event JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (run_id, sequence)
      );
      CREATE INDEX IF NOT EXISTS copilotkit_run_events_thread_created_idx
        ON copilotkit_run_events (thread_id, created_at, sequence);

      CREATE TABLE IF NOT EXISTS copilotkit_thread_locks (
        thread_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL
      );
    `);
  }

  async #finalizeInterruptedRuns() {
    const interrupted = await this.#pool.query(
      `SELECT r.thread_id, r.run_id, COALESCE(MAX(e.sequence), -1) AS last_sequence
         FROM copilotkit_agent_runs r
         LEFT JOIN copilotkit_run_events e ON e.run_id = r.run_id
         LEFT JOIN copilotkit_thread_locks l ON l.thread_id = r.thread_id AND l.run_id = r.run_id
        WHERE r.status = 'running' AND (l.expires_at IS NULL OR l.expires_at <= NOW())
        GROUP BY r.thread_id, r.run_id`,
    );

    for (const row of interrupted.rows) {
      if (this.#activeRuns.get(row.thread_id)?.runId === row.run_id) {
        continue;
      }
      const sequence = Number(row.last_sequence) + 1;
      await this.#pool.query(
        `INSERT INTO copilotkit_run_events (thread_id, run_id, sequence, event)
         VALUES ($1, $2, $3, $4::jsonb), ($1, $2, $3 + 1, $5::jsonb)
         ON CONFLICT (run_id, sequence) DO NOTHING`,
        [
          row.thread_id,
          row.run_id,
          sequence,
          JSON.stringify({
            type: EventType.RUN_ERROR,
            message:
              "Copilot Runtime restarted before this run completed. Continue on the same thread to resume from the durable agent checkpoint.",
            code: "runtime_restarted",
          }),
          JSON.stringify({ type: EventType.RUN_FINISHED, threadId: row.thread_id, runId: row.run_id }),
        ],
      );
      await this.#pool.query(
        "UPDATE copilotkit_agent_runs SET status = 'interrupted', updated_at = NOW() WHERE run_id = $1",
        [row.run_id],
      );
    }
    await this.#pool.query("DELETE FROM copilotkit_thread_locks WHERE expires_at <= NOW()");
  }
}

function createActiveRun(request, subject) {
  let resolveFinished;
  const finished = new Promise((resolve) => {
    resolveFinished = resolve;
  });
  return {
    agent: request.agent,
    events: [],
    finished,
    flushTimer: undefined,
    input: request.input,
    lockAcquired: false,
    nextSequence: 0,
    pendingEvents: [],
    persistedInputMessages: request.persistedInputMessages,
    resolveFinished,
    runId: request.input.runId,
    stopRequested: false,
    subject,
    threadId: request.threadId,
    writeChain: Promise.resolve(),
  };
}

function withRunInput(event, input, historicMessageIds) {
  if (event.type !== EventType.RUN_STARTED || event.input) {
    return event;
  }
  const messages = input.messages?.filter((message) => !historicMessageIds.has(message.id));
  return {
    ...event,
    input: {
      ...input,
      ...(messages ? { messages } : {}),
    },
  };
}

function normalizeDatabaseUrl(value) {
  return value.replace(/^postgresql\+asyncpg:/, "postgresql:").replace(/^postgres:/, "postgresql:");
}
