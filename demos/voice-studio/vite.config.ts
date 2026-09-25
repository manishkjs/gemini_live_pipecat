import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    allowedHosts: true,
    proxy: {
      "/connect": {
        target: "http://127.0.0.1:7860",
        changeOrigin: true,
      },
      "/persona-prompt": {
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
  plugins: [
    react(),
    {
      name: "sni-mismatch-handler",
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          const gfeInfo = req.headers["x-google-gfe-frontline-info"];
          if (gfeInfo && typeof gfeInfo === "string") {
            const host = (req.headers.host || "").split(":")[0].toLowerCase();
            const match = gfeInfo.match(/(?:^|,)\s*sni=([^,]+)/i);
            if (match && match[1]) {
              const sni = match[1].trim().toLowerCase();
              if (sni && host && sni !== host) {
                res.statusCode = 421;
                res.end("Misdirected Request");
                return;
              }
            }
          }
          next();
        });
      },
    },
  ],
});
