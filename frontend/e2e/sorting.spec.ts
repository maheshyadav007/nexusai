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

  // A person writes too, so the side the AI reads has someone on it.
  for (const topic of ["the offsite", "Friday's demo"]) await post(request, CONTROL, { subject: `About ${topic} ${stamp}`, sender: "Kim Lee <kim@people.example>", to: USER, body: "What do you think?\nKim" });
  const shots = process.env.E2E_SHOTS;
  if (shots) await page.setViewportSize({ width: 1440, height: 1400 });
  await page.goto("/mail/sort");
  // The build bot repeats its subjects, so it starts on the side the AI ignores, in a folder of its own.
  const card = page.locator('[data-testid="sort-folder"][data-sort-key="builds@ci.example"]');
  await expect(card).toBeVisible({ timeout: 60_000 });
  await expect(card).toHaveAttribute("data-side", "ignores");
  // Which side is said in words: the switch shows it, and a press moves the whole folder across,
  // into the Inbox, where it shows open and marked.
  await card.getByTestId("sort-folder-head").getByRole("radio", { name: "AI reads" }).click();
  await expect(page.locator('[data-testid="sort-sender"][data-sort-key="builds@ci.example"]')).toHaveAttribute("data-side", "reads");
  await expect(page.getByTestId("sort-moved-note")).toContainText("moved to Inbox");
  await page.getByTestId("sort-moved-note").getByRole("button", { name: "Undo" }).click();
  await expect(card).toHaveAttribute("data-side", "ignores");
  await card.getByRole("textbox", { name: "Folder name" }).fill("Build bot");
  await expect(card).toContainText("Automated/Build bot");
  if (shots) await page.screenshot({ path: `${shots}/sort.png`, fullPage: true });
  await page.getByRole("button", { name: "Sort my mail", exact: true }).click();
  await page.waitForURL("**/today");

  const categories = (await post(request, "/api/queries/categories.list")).categories as { name: string; mode: string }[];
  expect(categories.find((folder) => folder.name === "Automated/Build bot")?.mode).toBe("exact");
  const rows = (await post(request, "/api/queries/threads.list", { folder: "all" })).threads as { subject: string; category: string | null }[];
  expect(rows.filter((row) => /^Build \d+ passed$/.test(row.subject)).every((row) => row.category === "Automated/Build bot")).toBe(true);
  expect((await post(request, "/api/queries/mail.sort.get")).state).toBe("done");
  const rules = (await post(request, "/api/queries/rules.get")).rules as { actions: { category: string; skip_agent: boolean } }[];
  expect(rules.some((rule) => rule.actions.category === "Automated/Build bot" && rule.actions.skip_agent)).toBe(true);

  // Settings shows what sorting wrote under its folder, in words.
  await page.goto("/settings?section=rules");
  const written = page.getByTestId("rule-group").filter({ hasText: "Automated/Build bot" });
  await written.getByRole("button", { name: "Open Automated/Build bot" }).click();
  await expect(written.getByTestId("written-rule").first()).toContainText("From builds@ci.example");
  if (shots) {
    await page.screenshot({ path: `${shots}/rules-sorted.png`, fullPage: true });
    await page.getByRole("navigation", { name: "Main navigation" }).getByRole("button", { name: "More" }).click();
    await page.screenshot({ path: `${shots}/sidebar-more.png` });
  }
});

test("the Sort page opens again as things are now, and moving a sender saves its one rule", async ({ page, request }) => {
  type Rule = { name: string; conditions: { field: string; value: string }[]; actions: { category: string | null; skip_agent: boolean } };
  const rulesFor = async (sender: string) => ((await post(request, "/api/queries/rules.get")).rules as Rule[]).filter((rule) => rule.conditions.some((c) => c.value === sender));
  // Sorted by the test before: the build bot is kept from the AI in its own folder, Kim is read.
  await page.goto("/mail/sort");
  const bot = page.locator('[data-testid="sort-folder"][data-folder="Automated/Build bot"]');
  await expect(bot).toBeVisible({ timeout: 60_000 });
  await expect(bot).toContainText("Filed here by a rule now");
  const inbox = page.locator('[data-testid="sort-folder"][data-side="reads"][data-folder=""]');
  await inbox.getByRole("button", { name: "Show the senders in Inbox · no folder" }).click();
  await expect(inbox.locator('[data-testid="sort-sender"][data-sort-key="kim@people.example"]')).toHaveAttribute("data-side", "reads");
  await expect(page.getByRole("button", { name: "Skip sorting" })).toHaveCount(0);

  // A move can be undone: from the note where it was, or from the list of changes beside Save.
  await bot.getByTestId("sort-folder-head").getByRole("radio", { name: "AI reads" }).click();
  await expect(page.getByTestId("sort-moved-note")).toContainText("moved to Inbox");
  await page.getByTestId("sort-moved-note").getByRole("button", { name: "Undo" }).click();
  await expect(bot).toBeVisible();
  await expect(page.getByTestId("sort-changes")).toHaveCount(0);
  // The bot moves to the AI: it leaves the folder the AI skips, with one rule that lets it in.
  await bot.getByTestId("sort-folder-head").getByRole("radio", { name: "AI reads" }).click();
  await expect(page.getByTestId("sort-changes")).toHaveText("1 change · Review");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await page.waitForURL("**/today");
  await expect.poll(async () => (await rulesFor("builds@ci.example")).map((rule) => rule.actions.skip_agent)).toEqual([false]);

  // Opened again, the page shows that, not what it showed before.
  await page.goto("/mail/sort");
  await inbox.getByRole("button", { name: "Show the senders in Inbox · no folder" }).click({ timeout: 60_000 });
  await expect(inbox.locator('[data-testid="sort-sender"][data-sort-key="builds@ci.example"]')).toHaveAttribute("data-side", "reads");
  // Kim goes the other way: kept from the AI, with one rule.
  await inbox.locator('[data-testid="sort-sender"][data-sort-key="kim@people.example"]').getByRole("radio", { name: "AI ignores" }).click();
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await page.waitForURL("**/today");
  await expect.poll(async () => (await rulesFor("kim@people.example")).map((rule) => rule.actions.skip_agent)).toEqual([true]);
  expect((await rulesFor("builds@ci.example")).length).toBe(1);

  // A new folder the AI reads, made on the page; Kim is put in it from her details, mail and all.
  await page.goto("/mail/sort");
  await page.getByRole("button", { name: "+ New folder the AI reads" }).click({ timeout: 60_000 });
  await page.getByRole("textbox", { name: "New folder name" }).fill("Friends");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const friends = page.locator('[data-testid="sort-folder"][data-folder="Friends"]');
  await expect(friends).toContainText("Drag senders here");
  const automated = page.locator('[data-testid="sort-folder"][data-folder="Automated"]');
  await automated.getByRole("button", { name: "Show the senders in Automated · everything else" }).click();
  const kim = automated.locator('[data-testid="sort-sender"][data-sort-key="kim@people.example"]');
  await kim.getByRole("button", { name: /kim@people.example/ }).click();
  await kim.getByRole("combobox", { name: "Folder for people" }).click();
  await page.getByRole("option", { name: "AI reads · Friends" }).click();
  await expect(friends.locator('[data-testid="sort-sender"][data-sort-key="kim@people.example"]')).toHaveAttribute("data-side", "reads");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await page.waitForURL("**/today");
  await expect.poll(async () => (await rulesFor("kim@people.example")).map((rule) => [rule.actions.category, rule.actions.skip_agent])).toEqual([["Friends", false]]);
  const rows = (await post(request, "/api/queries/threads.list", { folder: "all" })).threads as { subject: string; category: string | null }[];
  const hers = rows.filter((row) => /^About (the offsite|Friday's demo) \d+$/.test(row.subject));
  expect(hers.length).toBeGreaterThan(0);
  expect(hers.map((row) => row.category)).toEqual(hers.map(() => "Friends"));
});
