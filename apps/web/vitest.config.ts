import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Single test channel for the web app. Vitest loads TS + the QuickJS-WASM
// sandbox, so all unit tests live here as `*.test.ts`.
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
