import assert from "node:assert/strict";
import test from "node:test";

import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { resolveCommandInvocation, resolvePackageBinary } from "./dev-command.mjs";

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
