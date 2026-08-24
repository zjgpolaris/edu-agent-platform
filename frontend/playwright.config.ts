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
const backendPort = process.env.E2E_BACKEND_PORT || "18080";
const frontendPort = process.env.E2E_FRONTEND_PORT || "13000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
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
      command: `${JSON.stringify(python)} -m uvicorn backend.api.main:app --host 127.0.0.1 --port ${backendPort}`,
      cwd: "..",
      env: {
        PYTHONPATH: "backend",
        EDU_AGENT_AUTH_REQUIRED: "true",
        EDU_AGENT_DB_PATH: "/tmp/edu-agent-playwright.sqlite3",
        JWT_SECRET: "edu-agent-playwright-only-secret",
        EDU_AGENT_LLM_DISABLED: "1",
        EDU_AGENT_ASSISTANT_PLANNER_ENABLED: "true",
        EDU_AGENT_RUNTIME_V2_ENABLED: "true",
        EDU_AGENT_RUNTIME_V2_PERCENT_BPS: "10000",
        EDU_AGENT_RUNTIME_V2_ARTIFACT_ENABLED: "true",
        EDU_AGENT_RUNTIME_V2_LEARNING_ASSISTANT_BPS: "10000",
        EDU_AGENT_AUTOTUTOR_CONTENT_GATE_MODE: "enforce",
        EDU_AGENT_AUTOTUTOR_CONTENT_GATE_BPS: "10000",
      },
      url: `http://127.0.0.1:${backendPort}/api/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npm run dev -- --hostname 127.0.0.1 --port ${frontendPort}`,
      env: { NEXT_PUBLIC_API_BASE_URL: `http://127.0.0.1:${backendPort}`, NEXT_DIST_DIR: ".next-e2e" },
      url: `http://127.0.0.1:${frontendPort}`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
