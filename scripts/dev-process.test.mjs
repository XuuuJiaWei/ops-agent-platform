import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { EventEmitter } from "node:events";
import test from "node:test";

import {
  DevProcessSupervisor,
  processResultExitCode,
  windowsTaskkillArguments,
} from "./dev-process.mjs";

test("uses taskkill to terminate an entire Windows process tree", () => {
  assert.deepEqual(windowsTaskkillArguments(321), ["/pid", "321", "/t", "/f"]);
});

test("maps child results to conventional exit codes", () => {
  assert.equal(processResultExitCode({ label: "web", code: 0, error: null, signal: null }), 0);
  assert.equal(processResultExitCode({ label: "web", code: null, error: null, signal: "SIGINT" }), 130);
  assert.equal(processResultExitCode({ label: "web", code: null, error: null, signal: "SIGTERM" }), 143);
});

test("creates and signals a POSIX process group", async () => {
  const child = fakeChild(123);
  let spawnOptions;
  const signals = [];
  const supervisor = new DevProcessSupervisor({
    platform: "linux",
    spawnProcess: (_command, _args, options) => {
      spawnOptions = options;
      return child;
    },
    killProcess: (pid, signal) => {
      signals.push([pid, signal]);
      queueMicrotask(() => child.emit("close", null, signal));
    },
  });

  supervisor.start("fixture", "node", [], { stdio: "inherit" });
  await supervisor.shutdown("SIGINT");

  assert.equal(spawnOptions.detached, true);
  assert.deepEqual(signals, [[-123, "SIGINT"]]);
});

test("uses taskkill for a managed Windows process", async () => {
  const child = fakeChild(456);
  let spawnOptions;
  const invocations = [];
  const supervisor = new DevProcessSupervisor({
    platform: "win32",
    spawnProcess: (_command, _args, options) => {
      spawnOptions = options;
      return child;
    },
    runSync: (command, args, options) => {
      invocations.push({ args, command, options });
      queueMicrotask(() => child.emit("close", null, "SIGTERM"));
      return { status: 0 };
    },
  });

  supervisor.start("fixture", "node", [], { stdio: "inherit" });
  await supervisor.shutdown("SIGTERM");

  assert.equal(spawnOptions.detached, false);
  assert.deepEqual(invocations, [
    {
      args: ["/pid", "456", "/t", "/f"],
      command: "taskkill",
      options: { stdio: "ignore", windowsHide: true },
    },
  ]);
});

test("stops a spawned process and its descendant", { timeout: 15_000 }, async () => {
  const fixtureDir = await mkdtemp(join(tmpdir(), "ops-pilot-dev-process-"));
  const pidFile = join(fixtureDir, "pids.json");
  const fixtureFile = join(fixtureDir, "parent.mjs");
  await writeFile(
    fixtureFile,
    `import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";
const child = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)"], { stdio: "ignore" });
writeFileSync(process.argv[2], JSON.stringify({ parent: process.pid, child: child.pid }));
setInterval(() => {}, 1000);
`,
  );

  const supervisor = new DevProcessSupervisor({ shutdownTimeoutMs: 2_000 });
  const parent = supervisor.start("fixture", process.execPath, [fixtureFile, pidFile], {
    stdio: "ignore",
  });

  try {
    const pids = await waitForPidFile(pidFile);
    await supervisor.shutdown("SIGTERM");
    await waitForProcessesToExit([pids.parent, pids.child]);

    assert.equal(isProcessRunning(pids.parent), false);
    assert.equal(isProcessRunning(pids.child), false);
    assert.equal(parent.done, true);
  } finally {
    await supervisor.shutdown("SIGKILL");
    await rm(fixtureDir, { force: true, recursive: true });
  }
});

async function waitForPidFile(path) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      return JSON.parse(await readFile(path, "utf8"));
    } catch (error) {
      if (error?.code !== "ENOENT") {
        throw error;
      }
      await delay(50);
    }
  }
  throw new Error("Timed out waiting for the process fixture.");
}

async function waitForProcessesToExit(pids) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (pids.every((pid) => !isProcessRunning(pid))) {
      return;
    }
    await delay(50);
  }
}

function isProcessRunning(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if (error?.code === "ESRCH") {
      return false;
    }
    throw error;
  }
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function fakeChild(pid) {
  return Object.assign(new EventEmitter(), {
    exitCode: null,
    pid,
    signalCode: null,
  });
}
