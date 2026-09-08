import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    proxy: {
      "/connect": "http://127.0.0.1:7860",
      "/api": "http://127.0.0.1:7860",
      "/diagnostics": "http://127.0.0.1:7860",
      "/ws": {
        target: "ws://127.0.0.1:7860",
        ws: true,
      },
    },
  },
});
