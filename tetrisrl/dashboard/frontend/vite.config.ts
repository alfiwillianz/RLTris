import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// Built assets are committed to tetrisrl/dashboard/static so the dashboard
// works from a plain checkout without Node.js.  In development, Vite proxies
// the API and websocket to the FastAPI backend on port 8000.
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: fileURLToPath(new URL("../static", import.meta.url)),
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": {
        target: "ws://127.0.0.1:8000",
        ws: true,
      },
    },
  },
});
