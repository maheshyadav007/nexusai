import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// Your folders hold the person's own categories and their labels on the server; More holds only
// the system folders.
const categories = ["Action needed", "Projects", "Finance", "People", "Travel", "Newsletters", "Team updates", "Reference", ...Array.from({ length: 12 }, (_, i) => `Project ${i + 1}`)].map((name) => ({ name, source: "user", in_priority: false, proposed: false, count: 3, unread: 0 }));
const folders = Array.from({ length: 2 }, (_, i) => ({ name: `Server ${i + 1}`, label: `Server ${i + 1}`, role: "other", here: 4, on_server: 4, unread: 0 }));
const screenshots = "../output/sidebar-review-2026-11-05";

test.beforeAll(async ({ request }) => {
  await request.post("/api/home/choose", { data: { path: `${process.env.E2E_HOME}/NexusAI` } });
  await request.post("/api/commands/onboarding.finish", { data: {} });
});

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.route("**/api/queries/categories.list", (route) => route.fulfill({ json: { categories } }));
  await page.route("**/api/queries/mail.folders", (route) => route.fulfill({ json: { folders, counts: {} } }));
});

test("five custom rows expand within a scroll area and collapse with the selected folder visible", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/queries/profile.get", (route) => route.fulfill({ json: { name: "Mahesh Yadav", role: "", tone: "friendly" } }));
  await page.goto("/today");
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  // The categories, the first five of them until shown all; the server's labels sit below them.
  const rows = nav.locator('[data-testid="nav-category"]');
  const list = nav.getByRole("region", { name: "Categories and custom folders" });
  const today = nav.getByRole("link", { name: "Today", exact: true });
  const priority = nav.getByRole("link", { name: "Inbox", exact: true });
  await expect(rows).toHaveCount(5);
  await expect(nav.locator('[data-testid="nav-folder"]')).toHaveCount(2);
  await expect(today).toHaveAttribute("aria-current", "page");
  const homeBox = await today.boundingBox();
  const mailBox = await priority.boundingBox();
  expect(mailBox!.y - homeBox!.y - homeBox!.height).toBeGreaterThanOrEqual(16);
  await page.screenshot({ path: `${screenshots}/collapsed-light.png` });
  await nav.getByRole("button", { name: "Show all (20)", exact: true }).click();
  await expect(rows).toHaveCount(20);
  await expect(nav.getByRole("button", { name: "Show less", exact: true })).toHaveAttribute("aria-expanded", "true");
  const size = await list.evaluate((node) => ({ visible: node.clientHeight, content: node.scrollHeight }));
  expect(size.content).toBeGreaterThan(size.visible);
  await page.screenshot({ path: `${screenshots}/show-all-top.png` });
  await list.hover();
  await page.mouse.wheel(0, 1000);
  await expect(nav.getByRole("link", { name: "Project 12", exact: true })).toBeInViewport();
  await expect(nav.getByRole("button", { name: "Show less", exact: true })).toBeInViewport();
  await expect(nav.getByRole("link", { name: "Tasks", exact: true })).toBeInViewport();
  await page.screenshot({ path: `${screenshots}/expanded-light.png` });
  await nav.getByRole("link", { name: "Project 12", exact: true }).click();
  await nav.getByRole("button", { name: "Show less", exact: true }).click();
  await expect(rows).toHaveCount(5);
  const active = nav.getByRole("link", { name: "Project 12", exact: true });
  await expect(active).toHaveAttribute("aria-current", "page");
  await expect(active).toBeInViewport();
  expect(await list.evaluate((node) => node.scrollTop)).toBe(0);
  await expect(nav.getByRole("link", { name: "Travel", exact: true })).toHaveCount(0);
  await today.click();
  await expect(nav.getByRole("link", { name: "Travel", exact: true })).toBeVisible();
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "nexus-dark"));
  await page.screenshot({ path: `${screenshots}/collapsed-dark.png` });
  await nav.getByRole("button", { name: "Show all (20)", exact: true }).click();
  await page.screenshot({ path: `${screenshots}/expanded-dark.png` });
  for (const height of [768, 640]) {
    await page.setViewportSize({ width: 1366, height });
    await list.scrollIntoViewIfNeeded();
    await expect(list).toBeInViewport();
    expect(await list.evaluate((node) => node.clientHeight)).toBeGreaterThan(0);
    await expect(nav.getByRole("button", { name: "Show less", exact: true })).toBeInViewport();
    await nav.getByRole("link", { name: "Sessions", exact: true }).scrollIntoViewIfNeeded();
    await expect(nav.getByRole("link", { name: "Sessions", exact: true })).toBeInViewport();
    await nav.getByRole("link", { name: "Tasks", exact: true }).scrollIntoViewIfNeeded();
    await expect(nav.getByRole("link", { name: "Tasks", exact: true })).toBeInViewport();
    await expect(today).toBeInViewport();
  }
  await nav.getByRole("button", { name: "Collapse sidebar", exact: true }).click();
  await expect(today).toBeVisible();
  await expect(nav.getByRole("button", { name: "Show less", exact: true })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("five or fewer custom folders need no expansion button", async ({ page }) => {
  await page.route("**/api/queries/categories.list", (route) => route.fulfill({ json: { categories: categories.slice(0, 3) } }));
  // Gmail's own Starred and Important are the app's views of those names, so they don't show twice.
  const gmail = ["Starred", "Important"].map((label) => ({ name: `[Gmail]/${label}`, label, role: "other", here: 4, on_server: 4, unread: 0, shown_elsewhere: true }));
  await page.route("**/api/queries/mail.folders", (route) => route.fulfill({ json: { folders: [...folders.slice(0, 2), ...gmail], counts: {} } }));
  await page.goto("/today");
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  await expect(nav.locator('[data-testid="nav-category"]')).toHaveCount(3);
  await expect(nav.getByRole("button", { name: /Show all|Show less/ })).toHaveCount(0);
  // The server's own labels show with the person's folders, not folded under More.
  await expect(nav.locator('[data-testid="nav-folder"]')).toHaveCount(2);
  await nav.getByRole("button", { name: "More" }).click();
  await expect(nav.locator('[data-testid="nav-folder"]')).toHaveCount(2);
  await expect(nav.getByRole("link", { name: "All mail", exact: true })).toBeVisible();
  // More isn't remembered open: after a reload it starts folded again.
  await page.reload();
  await expect(nav.getByRole("button", { name: "More" })).toHaveAttribute("aria-expanded", "false");
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
  // Name, what goes in it, and whether the AI reads it, together.
  await nav.getByRole("link", { name: /^Finance/ }).click({ button: "right" });
  await page.getByRole("menuitem", { name: "Edit folder…" }).click();
  const dialog = page.getByRole("dialog", { name: "Edit folder" });
  await expect(dialog.getByRole("textbox", { name: "What goes here" })).toBeVisible();
  await expect(dialog.getByRole("radio", { name: "AI reads" })).toBeChecked();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
  await request.post("/api/commands/sidebar.reset", { data: {} });
});
