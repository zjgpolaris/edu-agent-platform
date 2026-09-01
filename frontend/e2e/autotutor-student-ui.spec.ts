import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

test.beforeAll(() => {
  execFileSync(process.env.E2E_PYTHON || "python3", ["scripts/seed_pilot_demo.py"], {
    cwd: path.resolve(process.cwd(), ".."),
    env: {
      ...process.env,
      PYTHONPATH: "backend",
      EDU_AGENT_DB_PATH: "/tmp/edu-agent-playwright.sqlite3",
      JWT_SECRET: "edu-agent-playwright-only-secret",
    },
    stdio: "inherit",
  });
});

test.beforeEach(async ({ context }) => {
  const backendPort = process.env.E2E_BACKEND_PORT || "18080";
  await context.route(new RegExp(`^http://(localhost|127[.]0[.]0[.]1):${backendPort}/.*`), async (route) => {
    const request = route.request();
    const headers = { ...request.headers() };
    delete headers.host;
    delete headers["content-length"];
    const response = await fetch(
      request.url().replace(new RegExp(`^http://(localhost|127[.]0[.]0[.]1):${backendPort}`), `http://127.0.0.1:${backendPort}`),
      { method: request.method(), headers, body: request.postData() ?? undefined },
    );
    await route.fulfill({
      status: response.status,
      headers: Object.fromEntries(response.headers.entries()),
      body: Buffer.from(await response.arrayBuffer()),
    });
  });
});

async function enterStudent(page: Page) {
  await page.goto("/");
  await page.getByRole("tab", { name: "学生" }).click();
  await page.getByRole("button", { name: /体验 Agent 自主辅导/ }).click();
  await expect(page).toHaveURL(/\/student\/auto-tutor\?.*demo=1/);
}

test("Pilot 主线完成答错、反思重规划与退出票证据", async ({ page }) => {
  test.setTimeout(90_000);
  await enterStudent(page);

  await expect(page.getByRole("complementary", { name: "Agent 演示旅程" })).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".quiz-option-btn")).toHaveCount(4, { timeout: 30_000 });

  await page.locator(".quiz-option-btn").nth(1).click();
  await expect(page.getByText("根据本次作答调整讲解")).toBeVisible({ timeout: 30_000 });
  const journey = page.getByRole("complementary", { name: "Agent 演示旅程" });
  await expect(journey.getByText(/反思当前教学策略/)).toBeVisible({ timeout: 30_000 });
  await expect(journey.getByText(/调整后续教学计划/)).toBeVisible({ timeout: 30_000 });

  await page.locator(".quiz-option-btn").first().click();
  await expect(page.getByText("退出票检验", { exact: true }).first()).toBeVisible({ timeout: 30_000 });
  await page.locator(".quiz-option-btn").first().click();

  await expect(page.getByRole("heading", { name: "本节课小结" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("学习事件已记录")).toBeVisible();
  await expect(journey.getByText(/写入学习证据/)).toBeVisible({ timeout: 30_000 });

  await page.reload();
  await expect(page.getByRole("heading", { name: "本节课小结" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("已恢复最近一节已完成课程")).toBeVisible();
});

test("AutoTutor 默认展示可信内容并隐藏开发轨迹", async ({ page }) => {
  await enterStudent(page);
  await page.goto(`/student/auto-tutor?focus=${encodeURIComponent("戊戌变法失败原因")}`);
  await expect(page.getByText("本题学习目标")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("戊戌变法失败原因", { exact: true }).last()).toBeVisible();
  await expect(page.locator(".quiz-option-btn")).toHaveCount(4);
  await expect(page.getByText(/基本史实|与史实不符|张冠李戴|完全无关/)).toHaveCount(0);
  await expect(page.getByText(/Agent 正在|反思重规划|Agent 反思/)).toHaveCount(0);
  await expect(page.getByRole("complementary", { name: "开发调试轨迹" })).toHaveCount(0);
});

test("AutoTutor 内容不足时安全阻断且不展示题目", async ({ page }) => {
  await enterStudent(page);
  await page.goto(`/student/auto-tutor?focus=${encodeURIComponent("长平之战逐日行军路线")}`);
  await expect(page.getByText("这个学习目标暂时不能安全出题")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/不会改变你的掌握记录/)).toBeVisible();
  await expect(page.locator(".quiz-option-btn")).toHaveCount(0);
});
