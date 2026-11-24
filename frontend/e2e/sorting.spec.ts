import { expect, test, type APIRequestContext } from "@playwright/test";

const USER = "tester@example.com";
const CONTROL = "http://127.0.0.1:8767/";
const post = async (request: APIRequestContext, path: string, data: unknown = {}) => {
  const response = await request.post(path, { data });
  expect(response.ok(), await response.text()).toBe(true);
  const text = await response.text();
  return text ? JSON.parse(text) : {};
};

// A folder's senders open in its window over the page, in groups, beside their emails.
const sendersOf = async (page: import("@playwright/test").Page, card: import("@playwright/test").Locator) => {
  await card.getByTestId("sort-folder-head").getByRole("button", { name: /^Open .*: its emails, senders and rule$/ }).click();
  return page.getByTestId("sort-folder-modal");
};

test.beforeAll(async ({ request }) => {
  const selection = await request.post("/api/home/choose", { data: { path: `${process.env.E2E_HOME}/Sorting` } });
  if (!selection.ok()) expect((await selection.json()).code).toBe("home.already_open");
  await post(request, "/api/commands/onboarding.finish");
});

test("sorting files tool mail in a folder of its own in Hidden from AI, renamed, before the AI reads it", async ({ page, request }) => {
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
  // The AI's side gives its biggest senders folders of their own too, ticked to show in the
  // sidebar. Unticked, one the page made goes back to being a group in no folder; ticked again,
  // it's a folder again.
  // One the page made: a folder that already exists stays a folder whatever its tick says.
  const made = page.locator('[data-testid="sort-folder"][data-side="reads"][data-ticked="true"]:not([data-group]):not([data-real])').first();
  const label = (await made.getAttribute("data-folder")) as string;
  await made.getByRole("checkbox").click();
  const group = page.locator(`[data-testid="sort-folder"][data-side="reads"][data-folder="${label}"][data-group="true"]`);
  await expect(group.getByRole("checkbox")).not.toBeChecked();
  await group.getByRole("checkbox").click();
  await expect(page.locator(`[data-testid="sort-folder"][data-side="reads"][data-folder="${label}"]:not([data-group])`).getByRole("checkbox")).toBeChecked();
  // Move to takes the whole folder across, to Read by AI, where it shows marked.
  await card.getByRole("button", { name: /^Move .* to$/ }).click();
  await page.getByRole("menuitem", { name: "Read by AI, as its own folder" }).click();
  await expect(card).toHaveAttribute("data-side", "reads");
  await expect(page.getByTestId("sort-moved-note")).toContainText("moved to");
  await page.getByTestId("sort-moved-note").getByRole("button", { name: "Undo" }).click();
  await expect(card).toHaveAttribute("data-side", "ignores");
  // Renamed in place: a name another folder has is refused as it's typed, and Enter saves a free one.
  await card.getByRole("button", { name: /^Rename / }).click();
  const name = card.getByRole("textbox", { name: "Folder name" });
  await name.fill("read by ai");
  await expect(card.getByRole("alert")).toBeVisible();
  await name.fill("Build bot");
  await name.press("Enter");
  await expect(card.getByRole("button", { name: /^Open Build bot: / })).toBeVisible();
  // Ticked, it shows in the sidebar; its emails and rule open in a window, the page stays put.
  await expect(card.getByRole("checkbox", { name: "Show Build bot in the sidebar" })).toBeChecked();
  await card.getByRole("button", { name: /^Open Build bot: / }).click();
  const window = page.getByTestId("sort-folder-modal");
  await expect(window).toContainText("passed");
  // The rules, by sender, as rules: each one a row of conditions.
  await window.getByRole("tab", { name: /^Rules/ }).click();
  await expect(window.getByTestId("sort-rules")).toContainText("builds@ci.example");
  await expect(window.getByTestId("sort-rule").first()).toBeVisible();
  // A sender pressed keeps the tab that was chosen, then shows only its mail on Emails.
  await window.locator('[data-testid="sort-sender"][data-sort-key="builds@ci.example"]').getByRole("button", { name: "builds@ci.example", exact: true }).click();
  await expect(window.getByRole("tab", { name: /^Rules/ })).toHaveAttribute("aria-selected", "true");
  await window.getByRole("tab", { name: "Emails" }).click();
  await expect(window).toContainText(/of \d+ emails/);
  await page.keyboard.press("Escape");
  await expect(window).toHaveCount(0);
  // Each side ends with its "No folder" card, and the columns are named like the two homes.
  await expect(page.getByRole("region", { name: "Read by AI", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Hidden from AI", exact: true })).toBeVisible();
  if (shots) await page.screenshot({ path: `${shots}/sort.png`, fullPage: true });
  await page.getByRole("button", { name: "Sort my mail", exact: true }).click();
  await page.waitForURL("**/today");

  const categories = (await post(request, "/api/queries/categories.list")).categories as { name: string; mode: string }[];
  const bot = (categories as { name: string; mode: string; ai_reads?: boolean; parent?: string | null }[]).find((folder) => folder.name === "Build bot");
  expect([bot?.mode, bot?.ai_reads, bot?.parent ?? null]).toEqual(["exact", false, null]);
  expect(categories.some((folder) => folder.name.includes("/"))).toBe(false);
  const rows = (await post(request, "/api/queries/threads.list", { folder: "all" })).threads as { subject: string; category: string | null }[];
  expect(rows.filter((row) => /^Build \d+ passed$/.test(row.subject)).every((row) => row.category === "Build bot")).toBe(true);
  expect((await post(request, "/api/queries/mail.sort.get")).state).toBe("done");
  const rules = (await post(request, "/api/queries/rules.get")).rules as { actions: { category: string; skip_agent: boolean } }[];
  expect(rules.some((rule) => rule.actions.category === "Build bot" && rule.actions.skip_agent)).toBe(true);

  // Settings shows what sorting wrote under its folder, in words.
  await page.goto("/settings?section=rules");
  const written = page.getByTestId("rule-group").filter({ hasText: "Build bot" });
  await written.getByRole("button", { name: "Open Build bot" }).click();
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
  const bot = page.locator('[data-testid="sort-folder"][data-folder="Build bot"]');
  await expect(bot).toBeVisible({ timeout: 60_000 });
  await expect(bot).toContainText("Filed here by a rule now");
  const inbox = page.locator('[data-testid="sort-folder"][data-side="reads"][data-folder=""]');
  let open = await sendersOf(page, inbox);
  await expect(open.locator('[data-testid="sort-sender"][data-sort-key="kim@people.example"]')).toHaveAttribute("data-side", "reads");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Skip sorting" })).toHaveCount(0);

  // A move can be undone: from the note where it was, or from the list of changes beside Save.
  const moveBot = async () => {
    await bot.getByRole("button", { name: /^Move .* to$/ }).click();
    await page.getByRole("menuitem", { name: "Read by AI, as its own folder" }).click();
  };
  await moveBot();
  await expect(page.getByTestId("sort-moved-note")).toContainText("moved to Build bot");
  await page.getByTestId("sort-moved-note").getByRole("button", { name: "Undo" }).click();
  await expect(bot).toHaveAttribute("data-side", "ignores");
  await expect(page.getByTestId("sort-changes")).toHaveCount(0);
  // The whole folder moves to Read by AI: the bot in it is read by the AI, with one rule.
  await moveBot();
  await expect(page.getByTestId("sort-changes")).toHaveText("1 change · Review");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await page.waitForURL("**/today");
  await expect.poll(async () => (await rulesFor("builds@ci.example")).map((rule) => rule.actions.skip_agent)).toEqual([false]);

  const moved = (await post(request, "/api/queries/categories.list")).categories as { name: string; ai_reads?: boolean }[];
  expect(moved.find((folder) => folder.name === "Build bot")?.ai_reads).toBe(true);

  // Opened again, the page shows that, not what it showed before.
  await page.goto("/mail/sort");
  const read = page.locator('[data-testid="sort-folder"][data-side="reads"][data-folder="Build bot"]');
  await expect(read).toBeVisible({ timeout: 60_000 });
  open = await sendersOf(page, read);
  await expect(open.locator('[data-testid="sort-sender"][data-sort-key="builds@ci.example"]')).toHaveAttribute("data-side", "reads");
  await page.keyboard.press("Escape");
  // Kim goes the other way: hidden from the AI, with one rule.
  open = await sendersOf(page, inbox);
  await open.locator('[data-testid="sort-sender"][data-sort-key="kim@people.example"]').getByRole("button", { name: "Move kim@people.example to" }).click();
  await page.getByRole("menuitem", { name: "Hidden from AI · No folder" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await page.waitForURL("**/today");
  await expect.poll(async () => (await rulesFor("kim@people.example")).map((rule) => rule.actions.skip_agent)).toEqual([true]);
  expect((await rulesFor("builds@ci.example")).length).toBe(1);

  // Kim is put in a folder the AI reads from her details, mail and all.
  await page.goto("/mail/sort");
  const friends = page.locator('[data-testid="sort-folder"][data-side="reads"][data-folder="Build bot"]');
  await expect(friends).toBeVisible({ timeout: 60_000 });
  const automated = page.locator('[data-testid="sort-folder"][data-folder="Automated"]');
  open = await sendersOf(page, automated);
  const kim = open.locator('[data-testid="sort-sender"][data-sort-key="kim@people.example"]');
  await kim.getByRole("button", { name: "Move kim@people.example to" }).click();
  await page.getByRole("menuitem", { name: "Read by AI · Build bot" }).click();
  // Kim stays listed in the window, now read by the AI, until it closes.
  await expect(kim).toHaveAttribute("data-side", "reads");
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
  await expect(friends).toContainText("2 senders");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await page.waitForURL("**/today");
  await expect.poll(async () => (await rulesFor("kim@people.example")).map((rule) => [rule.actions.category, rule.actions.skip_agent])).toEqual([["Build bot", false]]);
  const rows = (await post(request, "/api/queries/threads.list", { folder: "all" })).threads as { subject: string; category: string | null }[];
  const hers = rows.filter((row) => /^About (the offsite|Friday's demo) \d+$/.test(row.subject));
  expect(hers.length).toBeGreaterThan(0);
  expect(hers.map((row) => row.category)).toEqual(hers.map(() => "Build bot"));
});
