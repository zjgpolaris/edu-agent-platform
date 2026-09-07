import { defineConfig, devices } from "@playwright/test";
import { spawnSync } from "node:child_process";
import os from "node:os";
import path from "node:path";
import { mkdtempSync } from "node:fs";

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
const browserChannel = process.env.E2E_BROWSER_CHANNEL === "chrome" ? "chrome" : undefined;
const graphDemo = process.env.E2E_GRAPH_DEMO === "1";
if (process.env.DATABASE_URL || process.env.DIRECT_URL) throw new Error("Unset DATABASE_URL / DIRECT_URL before isolated E2E");
process.env.E2E_DB_PATH ||= path.join(mkdtempSync(path.join(os.tmpdir(), "edu-agent-e2e-")), "demo.sqlite3");

export default defineConfig({
  testDir: "./e2e",
  testMatch: graphDemo ? ["autotutor-student-ui.spec.ts", "autotutor-graph-recovery.spec.ts"] : ["core-flows.spec.ts", "autotutor-student-ui.spec.ts"],
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
        channel: browserChannel,
        launchOptions: { args: ["--host-resolver-rules=MAP localhost 127.0.0.1"] },
      },
    },
  ],
  webServer: [
    {
      command: graphDemo ? `${JSON.stringify(python)} scripts/dev_autotutor_graph_demo.py --backend-only --port ${backendPort} --frontend-port ${frontendPort}` : `${JSON.stringify(python)} -m uvicorn backend.api.main:app --host 127.0.0.1 --port ${backendPort}`,
      cwd: "..",
      env: {
        PYTHONPATH: "backend",
        EDU_AGENT_AUTH_REQUIRED: "true",
        EDU_AGENT_DB_PATH: process.env.E2E_DB_PATH,
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
      env: { NEXT_PUBLIC_API_BASE_URL: `http://127.0.0.1:${backendPort}`, NEXT_DIST_DIR: graphDemo ? ".next-e2e-graph" : ".next-e2e" },
      url: `http://127.0.0.1:${frontendPort}`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
