import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// Priority, then the two homes: Inbox with the folders the AI reads, Kept from the AI with the
// rest. Each shows its biggest three; More holds the system folders and the server's labels.
const categories = ["Action needed", "Projects", "Finance", "People", "Travel", "Newsletters", "Team updates", "Reference", ...Array.from({ length: 12 }, (_, i) => `Project ${i + 1}`)].map((name, index) => ({ name, source: "user", in_priority: false, proposed: false, count: 40 - index, unread: 0 }));
const folders = Array.from({ length: 2 }, (_, i) => ({ name: `Server ${i + 1}`, label: `Server ${i + 1}`, role: "other", here: 4, on_server: 4, unread: 0 }));
const screenshots = "../output/sidebar-review-2026-11-23";

test.beforeAll(async ({ request }) => {
  await request.post("/api/home/choose", { data: { path: `${process.env.E2E_HOME}/NexusAI` } });
  await request.post("/api/commands/onboarding.finish", { data: {} });
});

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.route("**/api/queries/categories.list", (route) => route.fulfill({ json: { categories } }));
  await page.route("**/api/queries/mail.folders", (route) => route.fulfill({ json: { folders, counts: {} } }));
});

test("each home shows its three biggest folders, and Show all keeps the open one in view", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/queries/profile.get", (route) => route.fulfill({ json: { name: "Mahesh Yadav", role: "", tone: "friendly" } }));
  await page.goto("/today");
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  const inbox = nav.getByTestId("nav-home-reads");
  const rows = inbox.locator('[data-testid="nav-category"]');
  const today = nav.getByRole("link", { name: "Today", exact: true });
  const priority = nav.getByRole("link", { name: "Priority", exact: true });
  await expect(rows).toHaveCount(3);
  await expect(rows.first()).toContainText("Action needed");
  await expect(inbox.getByRole("link", { name: "Inbox", exact: true })).toBeVisible();
  // The server's labels wait under More.
  await expect(nav.locator('[data-testid="nav-folder"]')).toHaveCount(0);
  await expect(today).toHaveAttribute("aria-current", "page");
  const homeBox = await today.boundingBox();
  const mailBox = await priority.boundingBox();
  expect(mailBox!.y - homeBox!.y - homeBox!.height).toBeGreaterThanOrEqual(16);
  // Priority, then the Inbox, then Starred.
  const order = await nav.getByRole("link").evaluateAll((links) => links.map((link) => link.textContent?.trim() ?? ""));
  expect(order.findIndex((name) => name.startsWith("Priority"))).toBeLessThan(order.findIndex((name) => name.startsWith("Inbox")));
  expect(order.findIndex((name) => name.startsWith("Inbox"))).toBeLessThan(order.findIndex((name) => name.startsWith("Starred")));
  await page.screenshot({ path: `${screenshots}/homes-light.png` });
  await inbox.getByRole("button", { name: "Show all (20)", exact: true }).click();
  await expect(rows).toHaveCount(20);
  await expect(inbox.getByRole("button", { name: "Show less", exact: true })).toHaveAttribute("aria-expanded", "true");
  await nav.getByRole("link", { name: "Project 12", exact: true }).scrollIntoViewIfNeeded();
  await nav.getByRole("link", { name: "Project 12", exact: true }).click();
  await inbox.getByRole("button", { name: "Show less", exact: true }).click();
  // The three biggest, and the open one.
  await expect(rows).toHaveCount(4);
  const active = nav.getByRole("link", { name: "Project 12", exact: true });
  await expect(active).toHaveAttribute("aria-current", "page");
  await expect(active).toBeInViewport();
  await today.click();
  await expect(rows).toHaveCount(3);
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "nexus-dark"));
  await page.screenshot({ path: `${screenshots}/homes-dark.png` });
  for (const height of [768, 640]) {
    await page.setViewportSize({ width: 1366, height });
    await nav.getByRole("link", { name: "Sessions", exact: true }).scrollIntoViewIfNeeded();
    await expect(nav.getByRole("link", { name: "Sessions", exact: true })).toBeInViewport();
    await expect(today).toBeInViewport();
  }
  await nav.getByRole("button", { name: "Collapse sidebar", exact: true }).click();
  await expect(today).toBeVisible();
  await expect(nav.getByRole("button", { name: /Show all|Show less/ })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("three or fewer folders need no Show all, and the server's labels are under More", async ({ page }) => {
  await page.route("**/api/queries/categories.list", (route) => route.fulfill({ json: { categories: categories.slice(0, 3) } }));
  // Gmail's own Starred and Important are the app's views of those names, so they don't show twice.
  const gmail = ["Starred", "Important"].map((label) => ({ name: `[Gmail]/${label}`, label, role: "other", here: 4, on_server: 4, unread: 0, shown_elsewhere: true }));
  await page.route("**/api/queries/mail.folders", (route) => route.fulfill({ json: { folders: [...folders.slice(0, 2), ...gmail], counts: {} } }));
  await page.goto("/today");
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  await expect(nav.locator('[data-testid="nav-category"]')).toHaveCount(3);
  await expect(nav.getByRole("button", { name: /Show all|Show less/ })).toHaveCount(0);
  await expect(nav.locator('[data-testid="nav-folder"]')).toHaveCount(0);
  await nav.getByRole("button", { name: "More" }).click();
  await expect(nav.locator('[data-testid="nav-folder"]')).toHaveCount(2);
  await expect(nav.getByRole("heading", { name: "Labels from your mail account" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "All mail", exact: true })).toBeVisible();
  // More isn't remembered open: after a reload it starts folded again.
  await page.reload();
  await expect(nav.getByRole("button", { name: "More" })).toHaveAttribute("aria-expanded", "false");
});

test("folders sit inside folders, each home holds its own side, and a parent counts what's in it", async ({ page }) => {
  const tree = [
    { name: "Automated", source: "rule", in_priority: false, proposed: false, count: 90, unread: 9, ai_reads: false },
    { name: "Projects", source: "user", in_priority: false, proposed: false, count: 2, unread: 1, ai_reads: true },
    { name: "Alpha", source: "user", in_priority: false, proposed: false, count: 5, unread: 2, ai_reads: true, parent: "Projects" },
    { name: "Finance", source: "user", in_priority: true, proposed: false, count: 3, unread: 0, ai_reads: true },
    { name: "linkedin", source: "user", in_priority: false, proposed: false, count: 30, unread: 28, ai_reads: false, mode: "exact" },
    { name: "beehiiv", source: "user", in_priority: false, proposed: false, count: 5, unread: 4, ai_reads: false, mode: "exact" },
  ];
  await page.route("**/api/queries/categories.list", (route) => route.fulfill({ json: { categories: tree } }));
  await page.route("**/api/queries/mail.folders", (route) => route.fulfill({ json: { folders: [], counts: { priority: 22, reads: 7, kept: 41 } } }));
  await page.goto("/today");
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  const inbox = nav.getByTestId("nav-home-reads");
  const kept = nav.getByTestId("nav-home-kept");
  await expect(nav.getByRole("link", { name: "Priority", exact: true })).toContainText("22");
  await expect(inbox.getByRole("link", { name: "Inbox", exact: true })).toContainText("7");
  await expect(kept.getByRole("link", { name: "Kept from the AI", exact: true })).toContainText("41");
  // Automated, the catch-all, is never listed; its mail is simply kept.
  await expect(kept.locator('[data-testid="nav-category"]')).toHaveText([/linkedin/, /beehiiv/]);
  await expect(nav.getByRole("link", { name: "Automated", exact: true })).toHaveCount(0);
  // Projects, the biggest with Alpha in it, counts Alpha's unread too, and folds it away.
  const projects = inbox.getByRole("link", { name: "Projects", exact: true });
  await expect(projects).toContainText("3");
  await expect(inbox.getByRole("link", { name: "Alpha", exact: true })).toHaveCount(0);
  await inbox.getByRole("button", { name: "Show what's in Projects" }).click();
  await expect(inbox.getByRole("link", { name: "Alpha", exact: true })).toBeVisible();
  // A home's menu makes a folder for that side.
  await kept.getByRole("link", { name: "Kept from the AI", exact: true }).click({ button: "right" });
  await expect(page.getByRole("menuitem")).toHaveText(["Open", "Mark downloaded mail as read", "New folder…", "Sort senders…"]);
  await page.getByRole("menuitem", { name: "New folder…" }).click();
  const dialog = page.getByRole("dialog", { name: "New folder" });
  await expect(dialog.getByRole("combobox", { name: "Inside" })).toHaveText(/Kept from the AI/);
  await expect(dialog.getByRole("radio", { name: "The AI decides" })).toBeDisabled();
  await dialog.getByRole("textbox", { name: "Name" }).fill("LinkedIn");
  await expect(dialog.getByRole("alert")).toHaveText("There's already a folder called linkedin, in Kept from the AI.");
  await expect(dialog.getByRole("button", { name: "Create folder" })).toBeDisabled();
  await page.screenshot({ path: `${screenshots}/new-folder.png` });
  await page.keyboard.press("Escape");
  // Every folder has Show in Priority, and wording says folder.
  await projects.click({ button: "right" });
  for (const item of ["Show in Priority", "Rename folder…", "Folder settings…", "New folder inside…", "Remove folder…"]) await expect(page.getByRole("menuitem", { name: item })).toBeVisible();
  await page.keyboard.press("Escape");
});

test("Today counts decisions, matters waiting on you and on others, and Due stays hidden until ticked", async ({ page }) => {
  await page.goto("/today");
  const stats = page.getByRole("navigation", { name: "Your day at a glance" });
  await expect(stats).toContainText("For your decision");
  await expect(stats).toContainText("Waiting on you");
  await expect(stats).toContainText("Waiting on others");
  await expect(stats).not.toContainText("Due");
  await page.getByRole("button", { name: "Customize", exact: true }).click();
  await page.getByRole("checkbox", { name: "Due today" }).click();
  await expect(stats).toContainText("Due");
  await page.reload();
  await expect(stats).toContainText("Due");
  await page.getByRole("button", { name: "Customize", exact: true }).click();
  await page.getByRole("checkbox", { name: "Due today" }).click();
  await expect(stats).not.toContainText("Due");
  // The shield opens what's waiting, or says nothing is.
  await page.getByTestId("waiting-inbox").click();
  await expect(page.getByRole("dialog", { name: "Waiting for you" })).toBeVisible();
});

test("account menu aligns above the user button and supports keyboard and collapsed navigation", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.route("**/api/queries/profile.get", (route) => route.fulfill({ json: { name: "Mahesh Yadav", role: "", tone: "friendly" } }));
  await page.goto("/today");
  const trigger = page.getByTestId("account-menu-trigger");
  await expect(trigger).toHaveAccessibleName("Account menu for MY Mahesh Yadav");
  await expect(trigger).toContainText("MY");
  await expect(trigger).toContainText("Mahesh Yadav");
  await trigger.click();
  const menu = page.getByRole("menu", { name: "Account menu for MY Mahesh Yadav" });
  await expect(menu).toHaveAttribute("data-side", "top");
  await expect(menu).toHaveCSS("animation-name", "account-menu-in");
  await menu.evaluate((node) => Promise.all(node.getAnimations().map((animation) => animation.finished)));
  const anchor = await trigger.boundingBox();
  const popup = await menu.boundingBox();
  expect(Math.abs(anchor!.x - popup!.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(anchor!.width - popup!.width)).toBeLessThanOrEqual(1);
  expect(popup!.y + popup!.height).toBeLessThan(anchor!.y);
  const settings = menu.getByRole("menuitem", { name: "Settings", exact: true });
  expect((await settings.boundingBox())!.height).toBeGreaterThanOrEqual(32);
  await page.screenshot({ path: `${screenshots}/account-menu-light.png` });
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(trigger).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(menu).toBeVisible();
  await settings.click();
  await expect(page.getByRole("dialog", { name: "Settings", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Collapse sidebar", exact: true }).click();
  await expect(trigger).toHaveAccessibleName("Account menu for MY Mahesh Yadav");
  const { violations } = await new AxeBuilder({ page }).include('[data-testid="account-menu-trigger"]').withRules(["label-content-name-mismatch"]).analyze();
  expect(violations).toEqual([]);
  await trigger.click();
  await expect(menu).toHaveAttribute("data-side", "top");
  await menu.evaluate((node) => Promise.all(node.getAnimations().map((animation) => animation.finished)));
  const rail = await trigger.boundingBox();
  const railMenu = await menu.boundingBox();
  expect(railMenu!.width).toBeGreaterThan(rail!.width);
  expect(Math.abs(railMenu!.x - rail!.x)).toBeLessThanOrEqual(1);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Expand sidebar", exact: true }).click();
  await expect(page.locator('nav a[href="/today"] > span.absolute')).toHaveCSS("transform", "none");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "nexus-dark"));
  await trigger.click();
  await expect(menu).toHaveCSS("animation-duration", "0s");
  await page.screenshot({ path: `${screenshots}/account-menu-dark.png` });
});

test("long user names stay inside the footer and an empty profile has a usable fallback", async ({ page }) => {
  await page.route("**/api/queries/profile.get", (route) => route.fulfill({ json: { name: "Alexandra Catherine Montgomery Wellington", role: "", tone: "friendly" } }));
  await page.goto("/today");
  const trigger = page.getByTestId("account-menu-trigger");
  await expect(trigger).toHaveAccessibleName("Account menu for AC Alexandra Catherine Montgomery Wellington");
  expect(await trigger.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
  await page.route("**/api/queries/profile.get", (route) => route.fulfill({ json: { name: "  ", role: "", tone: "friendly" } }));
  await page.reload();
  await expect(trigger).toHaveAccessibleName("Account menu for Y You");
  await trigger.click();
  await expect(page.getByRole("menuitem", { name: "Settings", exact: true })).toBeVisible();
});

test("a folder can be hidden from the sidebar, waits under Show all, and is edited in one place", async ({ page, request }) => {
  await page.route("**/api/queries/categories.list", (route) => route.fulfill({ json: { categories: categories.slice(0, 3) } }));
  await page.goto("/today");
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  await expect(nav.locator('[data-testid="nav-category"]')).toHaveCount(3);
  await nav.getByRole("link", { name: /^Finance/ }).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Hide from sidebar" }).click();
  await expect(nav.locator('[data-testid="nav-category"]')).toHaveCount(2);
  // Hidden, not gone: one press away, and shown again from the same menu.
  await nav.getByRole("button", { name: /Show all/ }).click();
  await expect(nav.locator('[data-testid="nav-category"]')).toHaveCount(3);
  await nav.getByRole("link", { name: /^Finance/ }).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Show in sidebar" }).click();
  // Nothing hidden and only three: no button needed.
  await expect(nav.getByRole("button", { name: /Show all|Show less/ })).toHaveCount(0);
  await expect(nav.locator('[data-testid="nav-category"]')).toHaveCount(3);
  // Name, what goes in it, and where it is, which decides whether the AI reads it, together.
  await nav.getByRole("link", { name: /^Finance/ }).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Edit folder…" }).click();
  const dialog = page.getByRole("dialog", { name: "Edit folder" });
  await expect(dialog.getByRole("textbox", { name: "What goes here" })).toBeVisible();
  await expect(dialog.getByRole("combobox", { name: "Inside" })).toHaveText(/Inbox/);
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
  await request.post("/api/commands/sidebar.reset", { data: {} });
});
