import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Separate channel from the legacy `node --test src/app/*.test.mjs` suite:
// vitest can load TS + the QuickJS-WASM sandbox, which node:test cannot.
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["src/lib/**/*.test.ts", "src/spaces/**/*.test.ts"],
  },
});
