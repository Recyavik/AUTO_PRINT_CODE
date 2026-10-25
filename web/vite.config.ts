import fs from "node:fs";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const { version } = JSON.parse(fs.readFileSync(new URL("./package.json", import.meta.url), "utf-8"));

// Страница собирается в dist/, её раздаёт помощник (server/main.ts).
// Разработка: «npm run dev» (помощник) + «npm run dev:client» (Vite с горячей перезагрузкой).
export default defineConfig({
  root: "client",
  plugins: [react()],
  // версия страницы: если помощник в памяти старее файлов на диске, страница предупредит
  define: { __APP_VERSION__: JSON.stringify(version) },
  build: { outDir: "../dist", emptyOutDir: true, chunkSizeWarningLimit: 1500 },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/ws": { target: "ws://127.0.0.1:8790", ws: true },
      "/sounds": "http://127.0.0.1:8790",
      "/api": "http://127.0.0.1:8790",
    },
  },
});
