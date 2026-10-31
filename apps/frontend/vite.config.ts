import { fileURLToPath, URL } from "node:url";
import { existsSync, readFileSync } from "node:fs";

import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vitest/config";

function apiAddress(): string {
  let address = "http://127.0.0.1:8000";
  for (const name of ["project.json", "user.project.json"]) {
    const path = fileURLToPath(new URL(`../../config/${name}`, import.meta.url));
    if (!existsSync(path)) continue;
    const config: unknown = JSON.parse(readFileSync(path, "utf8"));
    if (typeof config !== "object" || config === null || !("frontend" in config)) continue;
    const frontend = config.frontend;
    if (typeof frontend !== "object" || frontend === null || !("apiBaseUrl" in frontend)) continue;
    if (typeof frontend.apiBaseUrl === "string") address = frontend.apiBaseUrl;
  }
  const url = new URL(address);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
    throw new Error("frontend.apiBaseUrl 必须是无凭据的 HTTP(S) 地址");
  }
  return address;
}

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  define: { __PUBLIC_API_BASE_URL__: JSON.stringify(apiAddress()) },
  server: { fs: { deny: ["**/config/project.json", "**/config/user.project.json", "**/.env*"] } },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "@agent-py/api-contracts": fileURLToPath(
        new URL("../../packages/api-contracts/src/index.ts", import.meta.url)
      )
    }
  },
  test: {
    include: ["tests/**/*.test.ts"]
  }
});
