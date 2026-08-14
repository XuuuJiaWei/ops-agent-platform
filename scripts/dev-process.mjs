import { spawn, spawnSync } from "node:child_process";

const DEFAULT_SHUTDOWN_TIMEOUT_MS = 3_000;

export class DevProcessSupervisor {
  constructor({
    platform = process.platform,
    spawnProcess = spawn,
    runSync = spawnSync,
    killProcess = process.kill,
    shutdownTimeoutMs = DEFAULT_SHUTDOWN_TIMEOUT_MS,
  } = {}) {
    this.platform = platform;
    this.spawnProcess = spawnProcess;
    this.runSync = runSync;
    this.killProcess = killProcess;
    this.shutdownTimeoutMs = shutdownTimeoutMs;
    this.records = [];
    this.shutdownPromise = null;
  }

  start(label, command, args, options = {}) {
    const child = this.spawnProcess(command, args, {
      ...options,
      detached: this.platform !== "win32",
    });
    const record = {
      child,
      closed: null,
      done: false,
      label,
      result: null,
    };

    record.closed = new Promise((resolve) => {
      const finish = (result) => {
        if (record.done) {
          return;
        }
        record.done = true;
        record.result = { label, ...result };
        resolve(record.result);
      };
      child.once("error", (error) => finish({ code: 1, error, signal: null }));
      child.once("close", (code, signal) => finish({ code, error: null, signal }));
    });

    this.records.push(record);
    return record;
  }

  waitForAny(records = this.records) {
    if (records.length === 0) {
      throw new Error("Cannot wait for an empty process set.");
    }
    return Promise.race(records.map((record) => record.closed));
  }

  shutdown(signal = "SIGTERM") {
    if (this.shutdownPromise === null) {
      this.shutdownPromise = this.#shutdown(signal);
    }
    return this.shutdownPromise;
  }

  async #shutdown(signal) {
    const active = this.records.filter((record) => !record.done);
    for (const record of active) {
      this.#signalTree(record, signal);
    }
    await waitForRecords(active, this.shutdownTimeoutMs);

    const remaining = active.filter((record) => !record.done);
    for (const record of remaining) {
      this.#signalTree(record, "SIGKILL");
    }
    await waitForRecords(remaining, this.shutdownTimeoutMs);
  }

  #signalTree(record, signal) {
    const pid = record.child.pid;
    if (!Number.isInteger(pid) || record.done) {
      return;
    }

    if (this.platform === "win32") {
      this.runSync("taskkill", windowsTaskkillArguments(pid), {
        stdio: "ignore",
        windowsHide: true,
      });
      return;
    }

    try {
      this.killProcess(-pid, signal);
    } catch (error) {
      if (error?.code !== "ESRCH") {
        throw error;
      }
    }
  }
}

export function windowsTaskkillArguments(pid) {
  return ["/pid", String(pid), "/t", "/f"];
}

export function processResultExitCode(result) {
  if (result.error) {
    console.error(`${result.label} failed to start: ${result.error.message}`);
    return 1;
  }
  if (result.code !== null) {
    return result.code;
  }
  return result.signal === "SIGINT" ? 130 : 143;
}

async function waitForRecords(records, timeoutMs) {
  if (records.length === 0) {
    return;
  }

  let timeout;
  await Promise.race([
    Promise.all(records.map((record) => record.closed)),
    new Promise((resolve) => {
      timeout = setTimeout(resolve, timeoutMs);
    }),
  ]);
  clearTimeout(timeout);
}
