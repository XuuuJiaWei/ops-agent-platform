#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { pipeBackendStderr } from "./dev-output.mjs";
import { buildLangGraphCommand, resolveCommandInvocation, resolvePackageBinary } from "./dev-command.mjs";
import { DevProcessSupervisor, processResultExitCode } from "./dev-process.mjs";

const rootDir = dirname(dirname(fileURLToPath(import.meta.url)));
const agentDir = join(rootDir, "services", "agent");
const copilotDir = join(rootDir, "apps", "copilot-runtime");
const webDir = join(rootDir, "apps", "web");
const mode = process.argv[2] ?? "all";
const supportedModes = new Set(["all", "backend", "check", "copilot", "langgraph", "web"]);

if (!supportedModes.has(mode)) {
  console.error(`Unknown dev mode '${mode}'. Expected one of: ${[...supportedModes].join(", ")}.`);
  process.exit(2);
}

if (process.env.OPS_PILOT_DEV_ENV_READY !== "1") {
  assertWorkspace();
}
const devEnv = mode === "langgraph" ? { ...process.env } : resolveDevEnvironment();

if (mode === "check") {
  console.log("Local development preflight passed.");
  process.exit(0);
}

const supervisor = new DevProcessSupervisor();
const shutdownController = new AbortController();
let interrupted = false;
const handleSignal = (signal) => {
  interrupted = true;
  shutdownController.abort(new Error(`Received ${signal}`));
  void supervisor.shutdown(signal);
};
const onSigint = () => handleSignal("SIGINT");
const onSigterm = () => handleSignal("SIGTERM");
const onSigbreak = () => handleSignal("SIGTERM");
process.once("SIGINT", onSigint);
process.once("SIGTERM", onSigterm);
if (process.platform === "win32") {
  process.once("SIGBREAK", onSigbreak);
}

try {
  process.exitCode = await runMode(supervisor, devEnv, shutdownController.signal);
} catch (error) {
  if (!interrupted) {
    throw error;
  }
  process.exitCode = 0;
} finally {
  process.removeListener("SIGINT", onSigint);
  process.removeListener("SIGTERM", onSigterm);
  process.removeListener("SIGBREAK", onSigbreak);
  if (!shutdownController.signal.aborted) {
    shutdownController.abort(new Error("Development stack stopped."));
  }
  await supervisor.shutdown(interrupted ? "SIGINT" : "SIGTERM");
}

async function runMode(processes, env, signal) {
  if (mode === "all") {
    return runAll(processes, env, signal);
  }
  if (mode === "backend") {
    return processResultExitCode(await startBackend(processes, env).closed);
  }
  if (mode === "copilot") {
    return processResultExitCode(await processes.start("copilot", ...copilotCommand(env)).closed);
  }
  if (mode === "langgraph") {
    return processResultExitCode(await processes.start("langgraph", ...buildLangGraphCommand(agentDir, env)).closed);
  }

  await waitForBackends(env, signal);
  return processResultExitCode(await processes.start("web", ...webCommand(env)).closed);
}

async function runAll(processes, env, signal) {
  const backend = startBackend(processes, env);
  const copilot = processes.start("copilot", ...copilotCommand(env));
  const startup = await Promise.race([
    waitForBackends(env, signal).then(() => null),
    processes.waitForAny([backend, copilot]),
  ]);
  if (startup !== null) {
    return processResultExitCode(startup);
  }

  const web = processes.start("web", ...webCommand(env));
  return processResultExitCode(await processes.waitForAny([backend, copilot, web]));
}

function startBackend(processes, env) {
  const backend = processes.start("backend", ...backendCommand(env));
  if (backend.child.stderr !== null) {
    pipeBackendStderr(backend.child.stderr, process.stderr, {
      verboseMcp: isEnabled(env.OPS_PILOT_DEV_VERBOSE_MCP ?? "false"),
    });
  }
  return backend;
}

function backendCommand(env) {
  return [
    "uv",
    ["run", "ops_pilot", "serve", "--host", env.BACKEND_HOST, "--port", env.BACKEND_PORT],
    {
      cwd: agentDir,
      env,
      stdio: ["inherit", "inherit", "pipe"],
    },
  ];
}

function copilotCommand(env) {
  return [process.execPath, [join(copilotDir, "src", "index.mjs")], { cwd: copilotDir, env, stdio: "inherit" }];
}

function webCommand(env) {
  const viteBinary = resolvePackageBinary("vite", "vite", webDir);
  return [process.execPath, [viteBinary], { cwd: webDir, env, stdio: "inherit" }];
}

function assertWorkspace() {
  const requiredFiles = [
    "package.json",
    "pnpm-workspace.yaml",
    "config/config.example.yaml",
    "apps/web/package.json",
    "apps/copilot-runtime/package.json",
    "services/agent/pyproject.toml",
    "services/agent/langgraph.json",
  ];
  const missingFiles = requiredFiles.filter((path) => !existsSync(join(rootDir, path)));
  if (missingFiles.length > 0) {
    throw new Error(`Local stack is incomplete; missing: ${missingFiles.join(", ")}`);
  }
  for (const command of ["pnpm", "uv"]) {
    const invocation = resolveCommandInvocation(command, ["--version"]);
    const result = spawnSync(invocation.command, invocation.args, { stdio: "ignore" });
    if (result.error || result.status !== 0) {
      throw new Error(`Missing command: ${command}`);
    }
  }
}

function resolveDevEnvironment() {
  if (process.env.OPS_PILOT_DEV_ENV_READY === "1") {
    return { ...process.env };
  }

  const result = spawnSync("uv", ["run", "ops_pilot", "settings"], {
    cwd: agentDir,
    encoding: "utf8",
    env: process.env,
  });
  if (result.error || result.status !== 0) {
    const detail = result.stderr?.trim() || result.error?.message || `exit code ${result.status}`;
    throw new Error(`Could not resolve backend settings: ${detail}`);
  }

  let settings;
  try {
    settings = JSON.parse(result.stdout);
  } catch (error) {
    throw new Error(`Backend settings returned invalid JSON: ${error.message}`, { cause: error });
  }

  const backendHost = process.env.CHAT_HOST || String(settings.chat_host);
  const backendPort = process.env.CHAT_PORT || String(settings.chat_port);
  const chatPath = normalizePath(String(settings.chat_base_path));
  const backendUrl = `http://${backendHost}:${backendPort}`;

  return {
    ...process.env,
    AGUI_AGENT_URL: process.env.AGUI_AGENT_URL || `${backendUrl}${chatPath}`,
    ASSISTANT: String(settings.assistant_id),
    ASSISTANT_ID: process.env.ASSISTANT_ID || String(settings.assistant_id),
    BACKEND_HOST: backendHost,
    BACKEND_PORT: backendPort,
    BACKEND_URL: backendUrl,
    CHAT_PATH: chatPath,
    OPS_PILOT_DEV_ENV_READY: "1",
    OPS_PILOT_PERSISTENCE_BACKEND: String(settings.persistence_backend),
    OPS_PILOT_PERSISTENCE_SETUP_ON_START: String(settings.persistence_setup_on_start),
    VITE_BACKEND_URL: process.env.VITE_BACKEND_URL || backendUrl,
  };
}

function normalizePath(value) {
  const withLeadingSlash = value.startsWith("/") ? value : `/${value}`;
  return withLeadingSlash === "/" ? withLeadingSlash : withLeadingSlash.replace(/\/+$/, "");
}

async function waitForBackends(env, signal) {
  if (!isEnabled(env.WEB_WAIT_FOR_BACKENDS ?? "true")) {
    return;
  }

  const timeoutSeconds = Number(env.WEB_WAIT_TIMEOUT ?? 300);
  const copilotPort = env.COPILOT_RUNTIME_PORT ?? "4001";
  const copilotUrl = env.WEB_WAIT_COPILOT_INFO_URL ?? `http://127.0.0.1:${copilotPort}/api/copilotkit`;
  const healthUrl = env.WEB_WAIT_CHAT_HEALTH_URL ?? `${env.BACKEND_URL}/health`;

  await waitForUrl(
    "Copilot runtime",
    copilotUrl,
    timeoutSeconds,
    signal,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ method: "info" }),
    },
  );
  await waitForUrl("Backend", healthUrl, timeoutSeconds, signal);
}

async function waitForUrl(label, url, timeoutSeconds, shutdownSignal, options = {}) {
  console.log(`Waiting for ${label} at ${url} ...`);
  const deadline = Date.now() + timeoutSeconds * 1000;
  while (Date.now() < deadline) {
    shutdownSignal.throwIfAborted();
    try {
      const requestSignal = AbortSignal.any([shutdownSignal, AbortSignal.timeout(2_000)]);
      const response = await fetch(url, { ...options, signal: requestSignal });
      if (response.ok) {
        console.log(`${label} is ready.`);
        return;
      }
    } catch {
      shutdownSignal.throwIfAborted();
      // The sibling process is still starting.
    }
    await abortableDelay(1_000, shutdownSignal);
  }
  throw new Error(`Timed out waiting for ${label} at ${url} after ${timeoutSeconds}s.`);
}

function abortableDelay(milliseconds, signal) {
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timeout);
      reject(signal.reason);
    };
    const timeout = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function isEnabled(value) {
  return ["1", "true", "yes"].includes(String(value).toLowerCase());
}
