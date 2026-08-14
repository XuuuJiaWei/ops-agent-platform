import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const WINDOWS_COMMAND_SHIMS = new Set(["pnpm"]);

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
