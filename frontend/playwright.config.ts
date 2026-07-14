import { defineConfig, devices } from "@playwright/test";
import { spawnSync } from "node:child_process";
import os from "node:os";
import path from "node:path";

function resolvePython(): string {
  const candidates = [
    process.env.E2E_PYTHON,
    "python3",
    path.join(os.homedir(), ".local/python3.12/bin/python3"),
  ].filter((value): value is string => Boolean(value));
  for (const candidate of candidates) {
    const probe = spawnSync(candidate, ["-c", "import uvicorn"], { stdio: "ignore" });
    if (!probe.error && probe.status === 0) return candidate;
  }
  throw new Error("No Python interpreter with uvicorn was found; set E2E_PYTHON explicitly");
}

const python = resolvePython();
process.env.E2E_PYTHON = python;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: { args: ["--host-resolver-rules=MAP localhost 127.0.0.1"] },
      },
    },
  ],
  webServer: [
    {
      command: `${JSON.stringify(python)} -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000`,
      cwd: "..",
      env: {
        PYTHONPATH: "backend",
        EDU_AGENT_AUTH_REQUIRED: "true",
        EDU_AGENT_DB_PATH: "/tmp/edu-agent-playwright.sqlite3",
        JWT_SECRET: "edu-agent-playwright-only-secret",
      },
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: "npm run dev -- --hostname 127.0.0.1",
      env: { NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8000" },
      url: "http://127.0.0.1:3000",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
