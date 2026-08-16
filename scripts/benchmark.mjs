#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { buildBenchmarkCommand } from "./benchmark-command.mjs";

const rootDir = dirname(dirname(fileURLToPath(import.meta.url)));
const agentDir = join(rootDir, "services", "agent");

loadRootEnvironment();
const aiopsLabDir = process.env.OPS_PILOT_AIOPSLAB_DIR?.trim();
if (!aiopsLabDir) {
  throw new Error(
    "OPS_PILOT_AIOPSLAB_DIR is required. Run `pnpm benchmark:setup` first, then set it in the repository .env.",
  );
}
if (!existsSync(aiopsLabDir)) {
  throw new Error(`OPS_PILOT_AIOPSLAB_DIR does not exist: ${aiopsLabDir}`);
}

const [command, args, options] = buildBenchmarkCommand(agentDir, aiopsLabDir, process.argv.slice(2));
const result = spawnSync(command, args, options);
if (result.error) {
  throw result.error;
}
process.exitCode = result.status ?? 1;

function loadRootEnvironment() {
  try {
    process.loadEnvFile(join(rootDir, ".env"));
  } catch (error) {
    if (error?.code !== "ENOENT") {
      throw error;
    }
  }
}
