#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = dirname(dirname(fileURLToPath(import.meta.url)));
const args = process.argv.slice(2);
if (args[0] === "--") {
  args.shift();
}

const result = spawnSync("uv", ["run", "rca100-benchmark", ...args], {
  cwd: join(rootDir, "benchmarks", "rca100"),
  env: process.env,
  stdio: "inherit",
});
if (result.error) {
  throw result.error;
}
process.exitCode = result.status ?? 1;
