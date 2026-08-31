import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const E2E_ADMIN = {
  username: "pilot-admin",
  password: "pilot-admin-123",
};

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
  const env = {
    ...process.env,
    PYTHONPATH: "backend",
    EDU_AGENT_DB_PATH: "/tmp/edu-agent-playwright.sqlite3",
    JWT_SECRET: "edu-agent-playwright-only-secret",
  };
  execFileSync(process.env.E2E_PYTHON || "python3", ["scripts/seed_pilot_demo.py"], {
    cwd: root,
    env,
    stdio: "inherit",
  });
  execFileSync(process.env.E2E_PYTHON || "python3", ["scripts/bootstrap_admin.py"], {
    cwd: root,
    env: {
      ...env,
      ADMIN_USERNAME: E2E_ADMIN.username,
      ADMIN_PASSWORD: E2E_ADMIN.password,
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

async function enterAdmin(page: Page) {
  await page.goto("/");
  await page.getByLabel("用户名 / 学号").fill(E2E_ADMIN.username);
  await page.getByLabel("密码").fill(E2E_ADMIN.password);
  await page.getByRole("button", { name: "登录学生工作台" }).click();
  await expect(page).toHaveURL(/\/eval$/);
}

test("学生可从工作台进入今日复习与错题库", async ({ page }) => {
  await enterDemo(page, "student");
  await page.goto("/student/review");
  await expect(page.getByRole("tab", { name: "今日任务" })).toBeVisible();
  await expect(page.getByText("这道题还没出好")).toHaveCount(0);
  await expect(page.locator(".rv-opt")).toHaveCount(4);
  const firstQuestion = await page.locator(".rv-q").innerText();
  await expect(page.locator(".rv-material")).toHaveCount(0);
  await page.locator(".rv-opt").first().click();
  await page.getByRole("button", { name: "确认答案" }).click();
  await expect(page.locator(".rv-material")).toBeVisible();
  await page.getByRole("button", { name: "看完了，做一道验证题" }).click();
  await expect(page.locator(".rv-q")).not.toHaveText(firstQuestion);
  await expect(page.locator(".rv-material")).toHaveCount(0);
  await expect(page.locator(".rv-opt")).toHaveCount(4);
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

test("智能练习在模型不可用时仍可按教材出题", async ({ page }) => {
  await enterDemo(page, "student");
  await page.goto("/student/quiz");
  const selectors = page.getByRole("combobox");
  await selectors.nth(0).selectOption({ label: "七年级下 · 中国历史七年级下册（人教版）" });
  await selectors.nth(1).selectOption({ label: "第7课 辽、西夏与北宋的并立" });
  await page.getByRole("button", { name: "3 题" }).click();
  await page.getByRole("button", { name: /开始练习/ }).click();
  await expect(page.locator(".quiz-card-question")).toBeVisible();
  await expect(page.locator(".quiz-dot")).toHaveCount(3);
  await expect(page.getByText("Failed to fetch")).toHaveCount(0);
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

test("随问高风险确认在同一个 Runtime Run 内完成", async ({ page }) => {
  test.setTimeout(60_000);
  await enterDemo(page, "student");
  await page.goto("/student/assistant");
  await page.getByRole("button", { name: "新对话" }).click();
  await page.getByRole("textbox", { name: "学习问题" }).fill("演示高风险工具，删除演示记忆");
  await page.getByRole("button", { name: "发送问题" }).click();

  await expect(page.getByText("需要你的确认", { exact: true })).toBeVisible({ timeout: 45_000 });
  await page.getByRole("button", { name: "确认执行", exact: true }).click();

  await expect(page.getByText("需要你的确认", { exact: true })).toHaveCount(0, { timeout: 45_000 });
  const completedAnswer = page.locator(".learning-message.assistant").last();
  await expect(completedAnswer).toContainText("已完成高风险工具确认演示", { timeout: 45_000 });
  await expect(completedAnswer).toContainText("只删除了 demo 范围内的学习记忆");
  await expect(completedAnswer).toContainText("没有影响真实学生画像");
});

test("学情薄弱点进入新随问会话并围绕指定知识点讲解", async ({ page }) => {
  test.setTimeout(60_000);
  await enterDemo(page, "student");
  await page.goto("/student/dashboard");
  await page.getByRole("button", { name: /薄弱点/ }).click();
  const reviewLink = page.getByRole("link", { name: /洋务运动目的.*复习/ });
  await expect(reviewLink).toBeVisible();
  await reviewLink.click();

  await expect(page).toHaveURL(/\/student\/assistant\?.*new=1/);
  const composer = page.getByRole("textbox", { name: "学习问题" });
  await expect(composer).toHaveValue(/洋务运动目的/);
  await page.getByRole("button", { name: "发送问题" }).click();

  const answer = page.locator(".learning-message.assistant").last();
  await expect(answer).toContainText("洋务运动", { timeout: 45_000 });
  await expect(answer).not.toContainText("分析下长平之战");
  await expect(answer).not.toContainText("suggest_review_plan");
});

test("教师可查看作业管理与 Pilot 作业", async ({ page }) => {
  await enterDemo(page, "teacher");
  await page.goto("/teacher/assignments");
  await expect(page.getByRole("heading", { name: "作业管理" })).toBeVisible();
  await expect(page.getByText("【Pilot Demo】辛亥革命随堂诊断")).toBeVisible();
  await expect(page.getByRole("button", { name: "+ 新建作业" })).toBeVisible();
});

test("管理员可查看 Eval 评测与 Trace 运行状态", async ({ page }) => {
  await enterAdmin(page);
  await expect(page.getByRole("heading", { name: "Eval 评估中心" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "AgentOps 运行状态" })).toBeVisible();
  await expect(page.getByText("Trace 覆盖率")).toBeVisible();
  await expect(page.getByLabel("Runtime Rollout")).toBeVisible();
  await expect(page.getByText("下一步：")).toBeVisible();
});
