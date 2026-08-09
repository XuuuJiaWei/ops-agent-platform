#!/usr/bin/env node

import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = dirname(dirname(fileURLToPath(import.meta.url)));
const agentDir = join(rootDir, "services", "agent");
const mode = process.argv[2] ?? "all";
const supportedModes = new Set(["all", "backend", "check", "copilot", "web"]);

if (!supportedModes.has(mode)) {
  console.error(`Unknown dev mode '${mode}'. Expected one of: ${[...supportedModes].join(", ")}.`);
  process.exit(2);
}

if (process.env.OPS_PILOT_DEV_ENV_READY !== "1") {
  assertWorkspace();
}
const devEnv = resolveDevEnvironment();

if (mode === "check") {
  console.log("Local development preflight passed.");
  process.exit(0);
}

if (mode === "all") {
  process.exitCode = await run(
    "pnpm",
    [
      "exec",
      "concurrently",
      "--names",
      "web,backend,copilot",
      "--prefix-colors",
      "cyan,green,yellow",
      "--kill-others-on-fail",
      "node ./scripts/dev.mjs web",
      "node ./scripts/dev.mjs backend",
      "node ./scripts/dev.mjs copilot",
    ],
    { cwd: rootDir, env: devEnv },
  );
} else if (mode === "backend") {
  process.exitCode = await run(
    "uv",
    ["run", "ops_pilot", "serve", "--host", devEnv.BACKEND_HOST, "--port", devEnv.BACKEND_PORT],
    { cwd: agentDir, env: devEnv },
  );
} else if (mode === "copilot") {
  process.exitCode = await run("pnpm", ["--filter", "./apps/copilot-runtime", "dev"], {
    cwd: rootDir,
    env: devEnv,
  });
} else {
  await waitForBackends(devEnv);
  process.exitCode = await run("pnpm", ["--filter", "./apps/web", "dev:vite"], {
    cwd: rootDir,
    env: devEnv,
  });
}

function assertWorkspace() {
  const requiredFiles = [
    "package.json",
    "pnpm-workspace.yaml",
    "config/config.example.yaml",
    "apps/web/package.json",
    "apps/copilot-runtime/package.json",
    "services/agent/pyproject.toml",
  ];
  const missingFiles = requiredFiles.filter((path) => !existsSync(join(rootDir, path)));
  if (missingFiles.length > 0) {
    throw new Error(`Local stack is incomplete; missing: ${missingFiles.join(", ")}`);
  }
  for (const command of ["pnpm", "uv"]) {
    const result = spawnSync(command, ["--version"], { stdio: "ignore" });
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

async function waitForBackends(env) {
  if (!isEnabled(env.WEB_WAIT_FOR_BACKENDS ?? "true")) {
    return;
  }

  const timeoutSeconds = Number(env.WEB_WAIT_TIMEOUT ?? 300);
  const copilotPort = env.COPILOT_RUNTIME_PORT ?? "4001";
  const copilotUrl = env.WEB_WAIT_COPILOT_INFO_URL ?? `http://127.0.0.1:${copilotPort}/api/copilotkit`;
  const healthUrl = env.WEB_WAIT_CHAT_HEALTH_URL ?? `${env.BACKEND_URL}/health`;

  await waitForUrl("Copilot runtime", copilotUrl, timeoutSeconds, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ method: "info" }),
  });
  await waitForUrl("Backend", healthUrl, timeoutSeconds);
}

async function waitForUrl(label, url, timeoutSeconds, options = {}) {
  console.log(`Waiting for ${label} at ${url} ...`);
  const deadline = Date.now() + timeoutSeconds * 1000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { ...options, signal: AbortSignal.timeout(2_000) });
      if (response.ok) {
        console.log(`${label} is ready.`);
        return;
      }
    } catch {
      // The sibling process is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }
  throw new Error(`Timed out waiting for ${label} at ${url} after ${timeoutSeconds}s.`);
}

function isEnabled(value) {
  return ["1", "true", "yes"].includes(String(value).toLowerCase());
}

function run(command, args, options) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { ...options, stdio: "inherit" });
    let forwardedSignal;
    const forward = (signal) => {
      forwardedSignal = signal;
      if (child.exitCode === null && child.signalCode === null) {
        child.kill(signal);
      }
    };
    const onSigint = () => forward("SIGINT");
    const onSigterm = () => forward("SIGTERM");
    process.once("SIGINT", onSigint);
    process.once("SIGTERM", onSigterm);

    child.once("error", reject);
    child.once("close", (code, signal) => {
      process.removeListener("SIGINT", onSigint);
      process.removeListener("SIGTERM", onSigterm);
      if (forwardedSignal) {
        resolve(0);
        return;
      }
      if (code !== null) {
        resolve(code);
        return;
      }
      resolve(signal === "SIGINT" || forwardedSignal === "SIGINT" ? 130 : 143);
    });
  });
}
