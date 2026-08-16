export function buildBenchmarkCommand(agentDir, aiopsLabDir, args, env = process.env) {
  return [
    "uv",
    ["run", "--with-editable", aiopsLabDir, "ops_pilot", "benchmark", ...args],
    { cwd: agentDir, env, stdio: "inherit" },
  ];
}
