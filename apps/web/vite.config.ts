import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";

const appRoot = fileURLToPath(new URL(".", import.meta.url));

function trimTrailingSlash(value: string): string {
  return value.replace(/\/$/, "");
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, appRoot, "");
  const backendUrl = trimTrailingSlash(env.BACKEND_URL ?? env.VITE_BACKEND_URL ?? "http://127.0.0.1:8123");
  const a2aApiUrl = trimTrailingSlash(env.A2A_API_URL ?? backendUrl);
  const copilotRuntimeUrl = trimTrailingSlash(env.COPILOT_RUNTIME_URL ?? "http://127.0.0.1:4001");
  const webPort = Number(process.env.WEB_PORT ?? env.WEB_PORT ?? "3000");

  return {
    envDir: appRoot,
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: {
      host: "0.0.0.0",
      port: webPort,
      strictPort: false,
      proxy: {
        "/api/copilotkit": {
          target: copilotRuntimeUrl,
          changeOrigin: true,
        },
        "/a2a": {
          target: a2aApiUrl,
          changeOrigin: true,
        },
        "/spaces": {
          target: backendUrl,
          changeOrigin: true,
        },
      },
    },
    preview: {
      host: "0.0.0.0",
      port: webPort,
      strictPort: false,
    },
  };
});
