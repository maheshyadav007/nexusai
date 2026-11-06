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
  const selection = await request.post("/api/home/choose", { data: { path: `${process.env.E2E_HOME}/Organization` } });
  if (!selection.ok()) expect((await selection.json()).code).toBe("home.already_open");
  await post(request, "/api/commands/onboarding.finish");
});

test("Exact filing, Important, archive Undo and Restore work together", async ({ page, request }) => {
  await post(request, "/api/commands/mail.accounts.save", { name: "organization", profile: { label: "Test mail", imap: { host: "127.0.0.1", port: 8143, secure: false }, smtp: { host: "127.0.0.1", port: 8025, secure: false }, auth: { user: USER } }, password: "test-password" });
  await expect.poll(async () => (await post(request, "/api/queries/mail.status")).state).toBe("live");
  await post(request, "/api/commands/categories.save", { name: "PLM", mode: "exact", subject: "[PLM]", in_priority: false });
  const subject = `[PLM] Organization ${Date.now()}`;
  await post(request, CONTROL, { subject });
  let id = 0;
  await expect.poll(async () => {
    const rows = (await post(request, "/api/queries/threads.list", { folder: "all" })).threads;
    id = rows.find((row: { subject: string; id: number }) => row.subject === subject)?.id ?? 0;
    return id;
  }).toBeGreaterThan(0);
  await page.goto("/mail/priority");
  await expect(page.getByRole("link", { name: subject, exact: false })).toHaveCount(0);
  await post(request, "/api/commands/thread.setImportance", { id, importance: "high" });
  await page.goto("/mail/important");
  await expect(page.getByText(subject, { exact: true })).toBeVisible();
  await page.getByText(subject, { exact: true }).click();
  await page.getByRole("button", { name: "Archive", exact: true }).click();
  await page.getByText("Undo", { exact: true }).click();
  await expect.poll(async () => (await post(request, "/api/queries/threads.list", { folder: "inbox" })).threads.some((row: { id: number }) => row.id === id)).toBe(true);
  await page.goto(`/mail/thread/${id}`);
  await page.getByRole("button", { name: "Archive", exact: true }).click();
  await page.goto(`/mail/archive/${id}`);
  await page.getByRole("button", { name: "Restore to inbox", exact: true }).click();
  await expect.poll(async () => (await post(request, "/api/queries/threads.list", { folder: "important" })).threads.some((row: { id: number }) => row.id === id)).toBe(true);
  const restored = await post(request, "/api/queries/thread.get", { id });
  expect(restored.thread.category).toBe("PLM");
  expect(restored.thread.importance).toBe("high");
});

test("an empty Smart folder can be changed to Exact by supplying a prefix", async ({ page, request }) => {
  const name = `Mode test ${Date.now()}`;
  await post(request, "/api/commands/categories.save", { name, mode: "smart" });
  await page.goto("/settings?section=categories");
  await page.getByRole("button", { name: `Open ${name}`, exact: true }).click();
  const row = page.getByTestId("category").filter({ hasText: name });
  await row.getByRole("combobox", { name: "Mode", exact: true }).click();
  await page.getByRole("option", { name: "Exact", exact: true }).click();
  await row.getByRole("textbox", { name: "Subject starts with", exact: true }).fill("[MODE]");
  await row.getByRole("textbox", { name: "Subject starts with", exact: true }).press("Tab");
  await expect.poll(async () => (await post(request, "/api/queries/categories.list")).categories.find((folder: { name: string }) => folder.name === name)?.mode).toBe("exact");
  await expect(row.getByRole("combobox", { name: "Mode", exact: true })).toContainText("Exact");
});

test("Priority, Important and Starred are separate views", async ({ page, request }) => {
  const rows = (await post(request, "/api/queries/threads.list", { folder: "all" })).threads;
  const target = rows[0];
  await post(request, "/api/commands/thread.setFlag", { id: target.id, flagged: true });
  await page.goto("/mail/starred");
  await expect(page.getByRole("link", { name: "Priority", exact: false }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Important", exact: false }).first()).toBeVisible();
  await expect(page.getByText(target.subject, { exact: true })).toBeVisible();
  await page.getByText(target.subject, { exact: true }).click();
  await page.getByRole("button", { name: "Remove star", exact: true }).click();
  await expect.poll(async () => (await post(request, "/api/queries/threads.list", { folder: "starred" })).threads.length).toBe(0);
});

test("folder and category context menus perform scoped operations", async ({ page, request }) => {
  await page.goto("/mail/all");
  for (const href of ["priority", "important", "starred", "all", "sent", "drafts", "archive", "trash"]) {
    await page.locator(`nav a[href='/mail/${href}']`).click({ button: "right" });
    await expect(page.getByRole("menuitem", { name: "Open", exact: true })).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Mark downloaded mail as read", exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
  }
  await page.locator("nav a[href='/mail/all']").click({ button: "right" });
  await page.getByRole("menuitem", { name: "Mark downloaded mail as read", exact: true }).click();
  await expect.poll(async () => (await post(request, "/api/queries/threads.list", { folder: "all" })).threads.every((row: {unread_count:number}) => row.unread_count === 0)).toBe(true);
  let name = "Context menu test";
  await post(request, "/api/commands/categories.save", { name, mode: "exact", subject: "[MENU]", in_priority: false });
  const rows = (await post(request, "/api/queries/threads.list", { folder: "all" })).threads;
  const id = rows[0].id;
  await post(request, "/api/commands/thread.setCategory", { id, category: name });
  await post(request, "/api/commands/thread.setRead", { id, read: false });
  await page.reload();
  let category = page.locator("nav").getByRole("link", { name, exact: false });
  await category.click({ button: "right" });
  await page.getByRole("menuitem", { name: "Mark downloaded mail as read", exact: true }).click();
  await expect.poll(async () => (await post(request, "/api/queries/threads.list", { folder: "all", category: name })).threads[0].unread_count).toBe(0);
  await category.click({ button: "right" });
  await page.getByRole("menuitem", { name: "Show in Priority", exact: true }).click();
  await expect.poll(async () => (await post(request, "/api/queries/categories.list")).categories.find((c: { name: string }) => c.name === name).in_priority).toBe(true);
  await category.click({ button: "right" });
  await page.getByRole("menuitem", { name: "Switch to Smart", exact: true }).click();
  await expect.poll(async () => (await post(request, "/api/queries/categories.list")).categories.find((c: { name: string }) => c.name === name).mode).toBe("smart");
  await category.click({ button: "right" });
  await page.getByRole("menuitem", { name: "Category settings…", exact: true }).click();
  await expect(page.getByTestId("category").filter({ hasText: name }).getByRole("textbox", { name: "Description", exact: true })).toBeVisible();
  await page.goto("/mail/all");
  await category.click({ button: "right" });
  await page.getByRole("menuitem", { name: "Rename category…", exact: true }).click();
  await page.getByRole("dialog").getByRole("textbox", { name: "Name", exact: true }).fill("Renamed context category");
  await page.getByRole("dialog").getByRole("button", { name: "Save", exact: true }).click();
  name = "Renamed context category";
  category = page.locator("nav").getByRole("link", { name, exact: false });
  await expect(category).toBeVisible();
  await category.click({ button: "right" });
  await page.getByRole("menuitem", { name: "Sort older mail…", exact: true }).click();
  await expect(page.getByRole("dialog").getByRole("button", { name: "Confirm sorting", exact: true })).toBeEnabled();
  await page.getByRole("dialog").getByRole("button", { name: "Close", exact: true }).click();
  await category.click({ button: "right" });
  await page.getByRole("menuitem", { name: "Remove category…", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("Its mail will be kept");
  await page.getByRole("dialog").getByRole("button", { name: "Close", exact: true }).click();
  await expect(category).toBeVisible();
  await category.click({ button: "right" });
  await page.getByRole("menuitem", { name: "Remove category…", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove category", exact: true }).click();
  await expect(category).toHaveCount(0);
  await expect.poll(async () => (await post(request, "/api/queries/threads.list", { folder: "all" })).threads.some((row: {id:number}) => row.id === id)).toBe(true);
});


test("failed learning retries through the recovery command and exposes retry failures", async ({ page }) => {
  let attempts = 0;
  let recovered = false;
  await page.route("**/api/queries/mail.organization", (route) => route.fulfill({ json: { state: recovered ? "done" : "failed", interview: null, groups: [], missed: [], merges: [], suggestions: [], done: 0, total: 1, metrics: {} } }));
  await page.route("**/api/commands/mailAgent.retryLearning", (route) => {
    attempts += 1;
    if (attempts === 1) return route.fulfill({ status: 503, json: { code: "retry.unavailable", message: "Recovery temporarily unavailable" } });
    recovered = true;
    return route.fulfill({ json: { ok: true } });
  });
  await page.goto("/today");
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await expect(page.getByText("Recovery temporarily unavailable", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await expect(page.getByText("Learning needs attention. Retry from Mail agent settings.", { exact: true })).toHaveCount(0);
  expect(attempts).toBe(2);
});
