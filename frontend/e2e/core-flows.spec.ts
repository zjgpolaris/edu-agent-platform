import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

test.beforeEach(async ({ context }) => {
  // Keep the real FastAPI boundary while avoiding browser/system proxy rules
  // that can intercept localhost cross-port requests on managed desktops.
  const backendPort = process.env.E2E_BACKEND_PORT || "18080";
  await context.route(new RegExp(`http:\\/\\/(localhost|127\\.0\\.0\\.1):${backendPort}\\/.*`), async (route) => {
    const browserRequest = route.request();
    const headers = { ...browserRequest.headers() };
    delete headers.host;
    delete headers["content-length"];
    const apiResponse = await fetch(
      browserRequest.url().replace(new RegExp(`http:\\/\\/(localhost|127\\.0\\.0\\.1):${backendPort}`), `http://127.0.0.1:${backendPort}`),
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
  // 未开课时页面渲染启动引导；「本节课计划」等三栏面板要开课后才出现
  await expect(page.getByRole("button", { name: "开始本节课" })).toBeVisible();
});

test("学生打开随问后可直接提问或按需添加教材", async ({ page }) => {
  await enterDemo(page, "student");
  await page.goto("/student/assistant");
  await expect(page.getByRole("heading", { name: "随问", exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "学习问题" })).toBeEnabled();
  await expect(page.getByRole("heading", { name: "学习上下文" })).toHaveCount(0);
  await page.getByRole("button", { name: "历史会话" }).click();
  await expect(page.getByRole("dialog", { name: "历史会话" })).toBeVisible();
  await page.getByRole("button", { name: "关闭历史会话" }).click();
  await page.getByRole("button", { name: "添加教材上下文" }).click();
  await expect(page.getByRole("dialog", { name: "添加教材上下文" })).toBeVisible();
  await page.getByRole("button", { name: "暂不使用" }).click();
  await expect(page.getByRole("dialog", { name: "添加教材上下文" })).toHaveCount(0);
});

test("随问可执行解释后出题的三步受限计划", async ({ page }) => {
  test.setTimeout(60_000);
  await enterDemo(page, "student");
  await page.goto("/student/assistant");
  await page.getByRole("button", { name: "新对话" }).click();
  await page.getByRole("textbox", { name: "学习问题" }).fill("先解释洋务运动，再出3道选择题");
  await page.getByRole("button", { name: "发送问题" }).click();
  await expect(page.getByLabel("学习计划进度")).toBeVisible({ timeout: 45_000 });
  await expect(page.locator(".learning-plan-step.completed")).toHaveCount(3, { timeout: 45_000 });
  const plannedAnswer = page.locator(".learning-message.assistant").filter({ has: page.getByLabel("学习计划进度") }).last();
  await expect(plannedAnswer.getByText(/已为你生成 3 道练习题/)).toBeVisible();
  await plannedAnswer.getByText("查看回答依据").click();
  await expect(plannedAnswer).not.toContainText(/灰度决策|路由方式|reason_code|bucket|置信度/);
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
