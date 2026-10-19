import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backend = process.env.KQ_BACKEND || "http://localhost:8095";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": backend,
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
