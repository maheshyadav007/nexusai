import { expect, test, type APIRequestContext } from "@playwright/test";

const USER = "tester@example.com";
const CONTROL = "http://127.0.0.1:8767/";
const post = async (request: APIRequestContext, path: string, data: unknown = {}) => {
  const response = await request.post(path, { data });
  expect(response.ok(), await response.text()).toBe(true);
  const text = await response.text();
  return text ? JSON.parse(text) : {};
};

test.beforeAll(async ({ request }) => {
  const selection = await request.post("/api/home/choose", { data: { path: `${process.env.E2E_HOME}/Sorting` } });
  if (!selection.ok()) expect((await selection.json()).code).toBe("home.already_open");
  await post(request, "/api/commands/onboarding.finish");
});

test("sorting files tool mail under Automated, renamed, before the AI reads it", async ({ page, request }) => {
  await post(request, "/api/commands/mail.accounts.save", { name: "sorting", profile: { label: "Test mail", imap: { host: "127.0.0.1", port: 8143, secure: false }, smtp: { host: "127.0.0.1", port: 8025, secure: false }, auth: { user: USER } }, password: "test-password" });
  await expect.poll(async () => (await post(request, "/api/queries/mail.status")).state).toBe("live");
  const stamp = Date.now() % 100000;
  for (let n = 1; n <= 6; n += 1) {
    await post(request, CONTROL, { subject: `Build ${stamp + n} passed`, sender: "Build Bot <builds@ci.example>", to: USER, body: "The build passed.\nLogs are on the job page.\nYou get this because you watch the job.\nCI" });
  }
  await expect.poll(async () => (await post(request, "/api/queries/threads.list", { folder: "all" })).threads.filter((row: { subject: string }) => row.subject.startsWith(`Build ${stamp}`) || /^Build \d+ passed$/.test(row.subject)).length, { timeout: 30_000 }).toBeGreaterThanOrEqual(6);

  await page.goto("/mail/sort");
  const group = page.getByRole("button", { name: /^ci\s/ });
  await expect(group).toBeVisible({ timeout: 60_000 });
  await group.click();
  await expect(page.getByRole("combobox", { name: "Folder", exact: true })).toContainText("Automated");
  await page.getByRole("textbox", { name: "Category", exact: true }).fill("Build bot");
  await expect(page.getByRole("button", { name: /^Build bot\s/ })).toBeVisible();
  await page.getByRole("button", { name: "Sort my mail", exact: true }).click();
  await page.waitForURL("**/today");

  const categories = (await post(request, "/api/queries/categories.list")).categories as { name: string; mode: string }[];
  expect(categories.find((folder) => folder.name === "Automated/Build bot")?.mode).toBe("exact");
  const rows = (await post(request, "/api/queries/threads.list", { folder: "all" })).threads as { subject: string; category: string | null }[];
  expect(rows.filter((row) => /^Build \d+ passed$/.test(row.subject)).every((row) => row.category === "Automated/Build bot")).toBe(true);
  expect((await post(request, "/api/queries/mail.sort.get")).state).toBe("done");
  const rules = (await post(request, "/api/queries/rules.get")).rules as { actions: { category: string; skip_agent: boolean } }[];
  expect(rules.some((rule) => rule.actions.category === "Automated/Build bot" && rule.actions.skip_agent)).toBe(true);
});
