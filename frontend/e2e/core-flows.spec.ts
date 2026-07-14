import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

test.beforeEach(async ({ context }) => {
  // Keep the real FastAPI boundary while avoiding browser/system proxy rules
  // that can intercept localhost cross-port requests on managed desktops.
  await context.route("http://localhost:8000/**", async (route) => {
    const browserRequest = route.request();
    const headers = { ...browserRequest.headers() };
    delete headers.host;
    delete headers["content-length"];
    const apiResponse = await fetch(
      browserRequest.url().replace("http://localhost:8000", "http://127.0.0.1:8000"),
      {
        method: browserRequest.method(),
        headers,
        body: browserRequest.postDataBuffer() || undefined,
      },
    );
    await route.fulfill({
      status: apiResponse.status,
      headers: Object.fromEntries(apiResponse.headers.entries()),
      body: Buffer.from(await apiResponse.arrayBuffer()),
    });
  });
});

test.beforeAll(() => {
  const root = path.resolve(process.cwd(), "..");
  execFileSync(process.env.E2E_PYTHON || "python3", ["scripts/seed_pilot_demo.py"], {
    cwd: root,
    env: {
      ...process.env,
      PYTHONPATH: "backend",
      EDU_AGENT_DB_PATH: "/tmp/edu-agent-playwright.sqlite3",
      JWT_SECRET: "edu-agent-playwright-only-secret",
    },
    stdio: "inherit",
  });
});

async function enterDemo(page: Page, role: "student" | "teacher") {
  await page.goto("/");
  await page.getByRole("tab", { name: role === "student" ? "学生" : "教师" }).click();
  await page.getByRole("button", { name: new RegExp(role === "student" ? "学生体验" : "教师体验") }).click();
  await expect(page).toHaveURL(new RegExp(`/${role}$`));
}

test("学生可从工作台进入今日复习与错题库", async ({ page }) => {
  await enterDemo(page, "student");
  await page.goto("/student/review");
  await expect(page.getByRole("tab", { name: "今日任务" })).toBeVisible();
  await page.getByRole("tab", { name: "错题库" }).click();
  await expect(page).toHaveURL(/tab=weakpoints/);
  await expect(page.getByRole("heading", { name: "错因档案馆" })).toBeVisible();
});

test("学生可查看 Pilot 作业本", async ({ page }) => {
  await enterDemo(page, "student");
  await page.goto("/student/assignments");
  await expect(page.getByRole("heading", { name: "作业本" })).toBeVisible();
  await expect(page.getByText("【Pilot Demo】辛亥革命随堂诊断")).toBeVisible();
});

test("学生可打开 AutoTutor 自主辅导入口", async ({ page }) => {
  await enterDemo(page, "student");
  await page.goto("/student/auto-tutor");
  await expect(page.getByRole("heading", { name: "AutoTutor 自主辅导" })).toBeVisible();
  await expect(page.getByText("本节课计划")).toBeVisible();
});

test("教师可查看作业管理与 Pilot 作业", async ({ page }) => {
  await enterDemo(page, "teacher");
  await page.goto("/teacher/assignments");
  await expect(page.getByRole("heading", { name: "作业管理" })).toBeVisible();
  await expect(page.getByText("【Pilot Demo】辛亥革命随堂诊断")).toBeVisible();
  await expect(page.getByRole("button", { name: "+ 新建作业" })).toBeVisible();
});

test("Eval 页面展示评测与 Trace 运行状态", async ({ page }) => {
  await enterDemo(page, "teacher");
  await page.goto("/eval");
  await expect(page.getByRole("heading", { name: "Eval 评估中心" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "AgentOps 运行状态" })).toBeVisible();
  await expect(page.getByText("Trace 覆盖率")).toBeVisible();
});
