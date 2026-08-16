#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = dirname(dirname(fileURLToPath(import.meta.url)));
const args = process.argv.slice(2);
if (args[0] === "--") {
  args.shift();
}
addDefaultArtifact(args);

const result = spawnSync("uv", ["run", "rca100-benchmark", ...args], {
  cwd: join(rootDir, "benchmarks", "rca100"),
  env: process.env,
  stdio: "inherit",
});
if (result.error) {
  throw result.error;
}
process.exitCode = result.status ?? 1;

function addDefaultArtifact(commandArgs) {
  if (commandArgs[0] !== "run") {
    return;
  }
  const agentCommandIndex = commandArgs.indexOf("--agent-command");
  const runnerArgs = commandArgs.slice(0, agentCommandIndex >= 0 ? agentCommandIndex : commandArgs.length);
  if (runnerArgs.includes("--output")) {
    return;
  }
  const taskIndex = runnerArgs.indexOf("--task");
  const requestedScope = taskIndex >= 0 ? runnerArgs[taskIndex + 1] : "suite";
  const scope = String(requestedScope || "suite").replaceAll(/[^a-zA-Z0-9._-]/g, "_");
  const timestamp = new Date().toISOString().replaceAll(":", "-").replace(".", "-");
  const output = join(rootDir, "artifacts", "rca100", `${timestamp}-${scope}.json`);
  const insertionIndex = agentCommandIndex >= 0 ? agentCommandIndex : commandArgs.length;
  commandArgs.splice(insertionIndex, 0, "--output", output);
  process.stderr.write(`RCA100 artifact: ${output}\n`);
}
