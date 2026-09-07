import { expect, test, type Route } from "@playwright/test";

const port = process.env.E2E_BACKEND_PORT || "18080";
async function forward(route: Route) {
  const request = route.request();
  const headers = { ...request.headers() };
  delete headers.host; delete headers["content-length"];
  return fetch(request.url(), { method: request.method(), headers, body: request.postData() ?? undefined });
}

test("Graph 开课与答题提交后丢响应，同键恢复不重复推进", async ({ page, context }) => {
  test.setTimeout(120_000);
  const starts: { key: string; session: string }[] = [];
  const answers: { revision: number; key: string }[] = [];
  let dropStart = true;
  let dropAnswer = true;
  await context.route(`http://127.0.0.1:${port}/**`, async route => {
    const response = await forward(route);
    const body = await response.text();
    const url = route.request().url();
    if (url.endsWith("/api/autotutor/start") && response.ok) {
      starts.push({ key: route.request().postDataJSON().idempotency_key, session: JSON.parse(body).session_id });
      if (dropStart) { dropStart = false; await route.abort("failed"); return; }
    }
    if (url.endsWith("/api/autotutor/answer") && response.ok) {
      answers.push({ revision: JSON.parse(body).revision, key: route.request().postDataJSON().idempotency_key });
      if (dropAnswer) { dropAnswer = false; await route.abort("failed"); return; }
    }
    await route.fulfill({ status: response.status, headers: Object.fromEntries(response.headers.entries()), body });
  });
  await page.goto("/");
  await page.getByRole("button", { name: /体验 Agent 自主辅导/ }).click();
  await expect(page.getByLabel("请求恢复")).toBeVisible({ timeout: 30_000 });
  await page.reload();
  await page.getByRole("button", { name: "同步进度 / 恢复请求" }).click();
  await expect(page.locator(".quiz-option-btn")).toHaveCount(4, { timeout: 30_000 });
  expect(starts).toHaveLength(2);
  expect(starts[0]).toEqual(starts[1]);
  await expect(page.getByLabel("实际执行摘要")).toContainText("本地 Graph");
  await page.locator(".quiz-option-btn").first().evaluate(button => {
    // Two immediate clicks exercise the synchronous mutation guard before a
    // React rerender can disable the button.
    (button as HTMLButtonElement).click();
    (button as HTMLButtonElement).click();
  });
  await expect(page.getByLabel("请求恢复")).toBeVisible();
  expect(answers).toHaveLength(1);
  await page.reload();
  await page.getByRole("button", { name: "同步进度 / 恢复请求" }).click();
  await expect(page.getByLabel("请求恢复")).toHaveCount(0);
  await expect(page.getByText("已同步最新辅导进度", { exact: true })).toBeVisible();
  expect(answers).toHaveLength(1); // recovery used GET, no repeated answer mutation
  await expect(page.getByLabel("实际执行摘要")).toContainText(`版本 ${answers[0].revision}`);
});

test("登录503不是密码错误", async ({ page }) => {
  await page.route(`http://127.0.0.1:${port}/api/auth/login`, route => route.fulfill({ status: 503, contentType: "application/json", body: '{}' }));
  await page.goto("/");
  await page.getByRole("button", { name: /体验 Agent 自主辅导/ }).click();
  await expect(page.getByText("服务暂不可用，请稍后重试", { exact: true })).toBeVisible();
  await expect(page.getByText("用户名或密码错误，请重试", { exact: true })).toHaveCount(0);
});
