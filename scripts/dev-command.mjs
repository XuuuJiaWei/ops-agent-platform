import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const WINDOWS_COMMAND_SHIMS = new Set(["pnpm"]);

export function buildLangGraphCommand(agentDir, env = process.env) {
  const args = [
    "run",
    "--with",
    "langgraph-cli[inmem]>=0.4.31,<1",
    "langgraph",
    "dev",
    "--host",
    env.LANGGRAPH_HOST ?? "127.0.0.1",
    "--port",
    env.LANGGRAPH_PORT ?? "2024",
    "--studio-url",
    env.LANGGRAPH_STUDIO_URL ?? "http://localhost:3000",
    "--no-browser",
  ];
  if (!isEnabled(env.LANGGRAPH_RELOAD ?? "false")) {
    args.push("--no-reload");
  }
  return [
    "uv",
    args,
    {
      cwd: agentDir,
      env: {
        ...env,
        LANGCHAIN_TRACING_V2: env.LANGCHAIN_TRACING_V2 ?? "false",
        LANGGRAPH_NO_VERSION_CHECK: env.LANGGRAPH_NO_VERSION_CHECK ?? "true",
        LANGSMITH_TRACING: env.LANGSMITH_TRACING ?? "false",
      },
      stdio: "inherit",
    },
  ];
}

export function resolveCommandInvocation(command, args, options = {}) {
  const platform = options.platform ?? process.platform;
  const env = options.env ?? process.env;

  if (platform !== "win32" || !WINDOWS_COMMAND_SHIMS.has(command)) {
    return { command, args };
  }

  return {
    command: env.ComSpec ?? env.COMSPEC ?? "cmd.exe",
    args: ["/d", "/s", "/c", command, ...args],
  };
}

export function resolvePackageBinary(packageName, binaryName, fromDir) {
  const require = createRequire(join(fromDir, "package.json"));
  const packageJsonPath = require.resolve(`${packageName}/package.json`);
  const packageJson = JSON.parse(readFileSync(packageJsonPath, "utf8"));
  const binaryPath =
    typeof packageJson.bin === "string" ? packageJson.bin : packageJson.bin?.[binaryName];
  if (typeof binaryPath !== "string") {
    throw new Error(`Package '${packageName}' does not define the '${binaryName}' binary.`);
  }
  return join(dirname(packageJsonPath), binaryPath);
}

function isEnabled(value) {
  return ["1", "true", "yes"].includes(String(value).toLowerCase());
}
