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
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: {
        // React rarely changes between releases: keep it in its own file so phones keep it cached.
        manualChunks: (id) => (/node_modules\/(react|react-dom|react-router|scheduler|cookie)/.test(id) ? "vendor" : undefined),
      },
    },
  },
});
