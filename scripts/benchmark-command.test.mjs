import assert from "node:assert/strict";
import test from "node:test";

import { buildBenchmarkCommand } from "./benchmark-command.mjs";

test("layers AIOpsLab over the project for one benchmark run", () => {
  const [command, args, options] = buildBenchmarkCommand(
    "D:/repo/services",
    "D:/tools/AIOpsLab",
    ["--problem", "pod_failure_hotel_res-detection-1", "--max-steps", "10"],
    { MODEL_API_KEY: "test" },
  );

  assert.equal(command, "uv");
  assert.deepEqual(args, [
    "run",
    "--with",
    "setuptools==75.8.2",
    "--with-editable",
    "D:/tools/AIOpsLab",
    "--package",
    "ops-pilot-platform",
    "ops_pilot",
    "benchmark",
    "--problem",
    "pod_failure_hotel_res-detection-1",
    "--max-steps",
    "10",
  ]);
  assert.equal(options.cwd, "D:/repo/services");
  assert.equal(options.env.MODEL_API_KEY, "test");
  assert.equal(options.env.SETUPTOOLS_USE_DISTUTILS, "local");
});
