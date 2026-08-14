import assert from "node:assert/strict";
import test from "node:test";

import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { buildLangGraphCommand, resolveCommandInvocation, resolvePackageBinary } from "./dev-command.mjs";

const rootDir = dirname(dirname(fileURLToPath(import.meta.url)));

test("runs pnpm through cmd.exe on Windows", () => {
  assert.deepEqual(
    resolveCommandInvocation("pnpm", ["--version"], {
      platform: "win32",
      env: { ComSpec: "C:\\Windows\\System32\\cmd.exe" },
    }),
    {
      command: "C:\\Windows\\System32\\cmd.exe",
      args: ["/d", "/s", "/c", "pnpm", "--version"],
    },
  );
});

test("falls back to cmd.exe when Windows does not expose ComSpec", () => {
  assert.deepEqual(resolveCommandInvocation("pnpm", ["--version"], { platform: "win32", env: {} }), {
    command: "cmd.exe",
    args: ["/d", "/s", "/c", "pnpm", "--version"],
  });
});

test("runs native Windows executables directly", () => {
  assert.deepEqual(resolveCommandInvocation("uv", ["--version"], { platform: "win32", env: {} }), {
    command: "uv",
    args: ["--version"],
  });
});

test("runs commands directly on macOS and Linux", () => {
  for (const platform of ["darwin", "linux"]) {
    assert.deepEqual(resolveCommandInvocation("pnpm", ["--version"], { platform, env: {} }), {
      command: "pnpm",
      args: ["--version"],
    });
  }
});

test("resolves a workspace package binary without a package-manager shell", () => {
  const viteBinary = resolvePackageBinary("vite", "vite", `${rootDir}/apps/web`);

  assert.match(viteBinary.replaceAll("\\", "/"), /\/vite\/bin\/vite\.js$/);
});

test("builds the LangGraph dev command without a POSIX shell", () => {
  const [command, args, options] = buildLangGraphCommand("C:\\repo\\services\\agent", {
    LANGGRAPH_HOST: "127.0.0.2",
    LANGGRAPH_PORT: "3030",
    LANGGRAPH_RELOAD: "true",
    LANGGRAPH_STUDIO_URL: "http://localhost:4000",
  });

  assert.equal(command, "uv");
  assert.deepEqual(args, [
    "run",
    "--with",
    "langgraph-cli[inmem]>=0.4.31,<1",
    "langgraph",
    "dev",
    "--host",
    "127.0.0.2",
    "--port",
    "3030",
    "--studio-url",
    "http://localhost:4000",
    "--no-browser",
  ]);
  assert.equal(options.cwd, "C:\\repo\\services\\agent");
  assert.equal(options.env.LANGSMITH_TRACING, "false");
  assert.equal(options.env.LANGGRAPH_NO_VERSION_CHECK, "true");
});
