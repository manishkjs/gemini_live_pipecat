import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    allowedHosts: true,
    proxy: {
      "/connect": {
        target: "http://127.0.0.1:7860",
        changeOrigin: true,
      },
      "/api": {
        target: "http://127.0.0.1:7860",
        changeOrigin: true,
      },
      "/diagnostics": {
        target: "http://127.0.0.1:7860",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://127.0.0.1:7860",
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
