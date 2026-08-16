#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { buildBenchmarkCommand } from "./benchmark-command.mjs";

const rootDir = dirname(dirname(fileURLToPath(import.meta.url)));
const servicesDir = join(rootDir, "services");

loadRootEnvironment();
const aiopsLabDir = loadBenchmarkConfig().aiopslab_dir?.trim();
if (!aiopsLabDir) {
  throw new Error(
    "config/runtime.yaml requires entrypoints.benchmark.benchmark.aiopslab.directory. Run `pnpm benchmark:setup` first.",
  );
}
if (!existsSync(aiopsLabDir)) {
  throw new Error(`OPS_PILOT_AIOPSLAB_DIR does not exist: ${aiopsLabDir}`);
}

const benchmarkArgs = process.argv.slice(2);
if (benchmarkArgs[0] === "--") {
  benchmarkArgs.shift();
}
const [command, args, options] = buildBenchmarkCommand(servicesDir, aiopsLabDir, benchmarkArgs);
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

function loadBenchmarkConfig() {
  const result = spawnSync("uv", ["run", "ops_pilot", "benchmark-launch-config"], {
    cwd: servicesDir,
    env: process.env,
    encoding: "utf8",
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`Unable to load the benchmark entrypoint from config/runtime.yaml:\n${result.stderr || result.stdout}`);
  }
  try {
    return JSON.parse(result.stdout);
  } catch (error) {
    throw new Error(`benchmark-launch-config returned invalid JSON: ${error}`);
  }
}
