// Browser tests: a real Karoulette server (built SPA + API) driven by a TV, phones and the host remote.
// Run with `npm run build && npm run test:e2e`. KQ_PYTHON picks the Python that has the backend's packages.
import { defineConfig, devices } from "@playwright/test";

const PORT = 8097;
const python = process.env.KQ_PYTHON || "python3";

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    // A fresh database every run; no YouTube key or yt-dlp, so queued videos are accepted unverified.
    command: `rm -rf e2e/.data && mkdir -p e2e/.data && cd ../backend && DATA_PATH=../frontend/e2e/.data `
      + `STATIC_DIR=../frontend/dist HOST_PIN=2468 ENABLE_YTDLP=false UPDATE_CHECK=false `
      + `${python} -m uvicorn --factory app.main:create_app --host 127.0.0.1 --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
