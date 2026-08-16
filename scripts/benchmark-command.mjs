export function buildBenchmarkCommand(servicesDir, aiopsLabDir, args, env = process.env) {
  return [
    "uv",
    [
      "run",
      "--with",
      "setuptools==75.8.2",
      "--with-editable",
      aiopsLabDir,
      "--package",
      "ops-pilot-platform",
      "ops_pilot",
      "benchmark",
      ...args,
    ],
    {
      cwd: servicesDir,
      env: { ...env, SETUPTOOLS_USE_DISTUTILS: "local" },
      stdio: "inherit",
    },
  ];
}
