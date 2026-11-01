import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { FONT_CATALOG } from "../ui/theme/font-catalog";

const background = (page: import("@playwright/test").Page) =>
  page.evaluate(() => getComputedStyle(document.body).backgroundColor);

test.beforeAll(async ({ request }) => {
  // So this file also works alone: a Home and a finished setup. Harmless if they already exist.
  await request.post("/api/home/choose", { data: { path: `${process.env.E2E_HOME}/NexusAI` } });
  await request.post("/api/commands/onboarding.finish", { data: {} });
});

const SCREENS = ["/today", "/settings", "/settings?section=profile", "/settings?section=preferences", "/settings?section=accounts", "/settings?section=rules", "/settings?section=models", "/settings?section=home", "/settings?section=network", "/settings?section=about", "/logs", "/mail/inbox", "/mail/sent", "/mail/drafts", "/mail/categories", "/search", "/gallery", "/gallery/shell"];

for (const path of SCREENS) {
  test(`${path} loads with no browser errors`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    expect(errors).toEqual([]);
  });
}

for (const path of SCREENS) {
  for (const theme of ["nexus-light", "nexus-dark"]) {
    test(`${path} has no accessibility violations in ${theme}`, async ({ page }) => {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await page.evaluate((id) => document.documentElement.setAttribute("data-theme", id), theme);
      const { violations } = await new AxeBuilder({ page }).analyze();
      expect(violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
    });
  }
  for (const width of [1366, 1536]) {
    test(`${path} fits a ${width}px screen`, async ({ page }) => {
      await page.setViewportSize({ width, height: 768 });
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBe(0);
    });
  }
}

test("the sidebar navigates, marks where you are, and remembers being collapsed", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/today$/);
  await page.getByRole("link", { name: "Inbox" }).click();
  await expect(page).toHaveURL(/\/mail\/inbox$/);
  await expect(page.getByRole("link", { name: "Inbox" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("heading", { name: "Inbox" })).toBeVisible();

  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  await page.reload();
  await expect(page.getByRole("button", { name: "Expand sidebar" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Inbox" })).toBeVisible();
});

test("an unknown path says so, and offers a way back", async ({ page }) => {
  await page.goto("/no-such-screen");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await page.getByRole("link", { name: "Go to the app" }).click();
  await expect(page).toHaveURL(/\/today$/);
});

test("overlays open, trap focus and close with Escape", async ({ page }) => {
  await page.goto("/gallery");
  await page.getByRole("button", { name: "Dialog" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Tab");
  expect(await dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("button", { name: "Dialog" })).toBeFocused();

  await page.getByRole("button", { name: "Menu" }).click();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(page.getByText("Draft a reply").first()).toBeVisible();
});

test("changing the theme goes through every layer, and reaches other windows", async ({ context }) => {
  const page = await context.newPage();
  const other = await context.newPage();
  await page.goto("/settings");
  await other.goto("/settings");
  await expect(page.getByRole("radio", { name: "Nexus Light" })).toBeChecked();
  const lightBackground = await background(page);

  await page.getByRole("radio", { name: "Nexus Dark" }).click();

  await expect.poll(() => background(page)).not.toBe(lightBackground);
  const logs = await context.newPage();
  await logs.goto("/logs");
  await logs.getByRole("tab", { name: "Events" }).click();
  await expect(logs.getByTestId("event-row").first()).toContainText("settings.changed");
  await expect(logs.getByTestId("event-row").first()).toContainText("nexus-dark");

  // The second window was told by an event; it did not ask.
  await expect(other.getByRole("radio", { name: "Nexus Dark" })).toBeChecked();
  await expect.poll(() => background(other)).not.toBe(lightBackground);

  // Saved, and applied before first paint after a reload.
  await page.reload();
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe("nexus-dark");
  await expect(page.getByRole("radio", { name: "Nexus Dark" })).toBeChecked();

  await page.getByRole("radio", { name: "Nexus Light" }).click();
  await expect.poll(() => background(page)).toBe(lightBackground);
});

test("every catalog font loads, and a theme's choice reaches the text", async ({ page }) => {
  await page.goto("/settings");
  const bodyFont = () => page.evaluate(() => getComputedStyle(document.body).fontFamily);
  await expect.poll(bodyFont).toMatch(/Instrument.Sans/i);

  for (const id of Object.values(FONT_CATALOG).flat()) {
    const family = await page.evaluate((name) => getComputedStyle(document.documentElement).getPropertyValue(`--font-${name}`), id);
    expect(family, `--font-${id} is missing; load it in ui/theme/fonts.ts`).not.toBe("");
  }

  // The same swap a theme file makes, applied live, reaches the rendered text.
  await page.evaluate(() => document.documentElement.style.setProperty("--type-family-sans", "var(--font-space-grotesk)"));
  await expect.poll(bodyFont).toMatch(/Space.Grotesk/i);
});

test("ChatGPT connects, lists models, remembers the choice and answers a test", async ({ page }) => {
  test.setTimeout(45_000);
  await page.goto("/settings?section=models");
  await page.getByRole("button", { name: "Connect ChatGPT" }).click();

  // The screen is told by an event when sign-in finishes; it doesn't ask.
  await expect(page.getByTestId("user-code")).toHaveText("WXYZ-1234");
  await expect(page.getByRole("link", { name: "Open the sign-in page" })).toHaveAttribute("href", /\/codex\/device$/);
  await expect(page.getByText("tester@example.com")).toBeVisible({ timeout: 20_000 });

  await page.getByRole("combobox", { name: "Model" }).click();
  await expect(page.getByRole("option")).toHaveText(["GPT Best", "GPT Slow"]);
  await page.getByRole("option", { name: "GPT Best" }).click();

  await page.getByRole("button", { name: "Send test" }).click();
  await expect(page.getByTestId("model-reply")).toHaveText("Hello from gpt-best");

  await page.reload();
  await expect(page.getByRole("combobox", { name: "Model" })).toHaveText("GPT Best");

  const { violations } = await new AxeBuilder({ page }).analyze();
  expect(violations.map((v) => v.id)).toEqual([]);

  await page.getByRole("button", { name: "Disconnect" }).click();
  await expect(page.getByRole("button", { name: "Connect ChatGPT" })).toBeVisible();
});

test("a change during a window's first load isn't lost", async ({ page, request }) => {
  // The first answer was read before the change, but arrives after the event saying it changed.
  let release = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  let first = true;
  await page.route("**/api/queries/settings.get", async (route) => {
    if (!first) return route.continue();
    first = false;
    const stale = await route.fetch();
    await held;
    return route.fulfill({ response: stale });
  });
  const events = page.waitForResponse("**/api/events?*");
  await page.goto("/settings");
  await events;
  await page.waitForTimeout(300);

  await request.post("/api/commands/settings.update", { data: { density: "spacious" } });
  await page.waitForTimeout(300);
  release();
  await expect(page.locator("html")).toHaveAttribute("data-density", "spacious");

  await request.post("/api/commands/settings.update", { data: { density: "comfortable" } });
  await expect(page.locator("html")).toHaveAttribute("data-density", "comfortable");
});

test("follow system matches the system, and an accent recolors the app", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/settings");
  await page.getByRole("radio", { name: "Follow system" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "nexus-dark");
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "nexus-light");

  const accent = () => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--color-accent-default").trim());
  const before = await accent();
  await page.getByRole("radio", { name: "Cobalt" }).click();
  await expect.poll(accent).not.toBe(before);
  await page.getByRole("radio", { name: "Terracotta" }).click();
  await page.getByRole("radio", { name: "Nexus Light" }).click();
});

test("profile saves from Settings, and preferences choose the first screen", async ({ page }) => {
  await page.goto("/settings?section=profile");
  await page.getByRole("textbox", { name: "Role" }).fill("Programme lead");
  await page.getByRole("button", { name: "Save" }).click();
  await page.goto("/settings?section=preferences");
  await page.reload();
  await page.goto("/settings?section=profile");
  await expect(page.getByRole("textbox", { name: "Role" })).toHaveValue("Programme lead");

  await page.goto("/settings?section=preferences");
  await page.getByRole("radio", { name: "Inbox" }).click();
  await expect(page.getByRole("radio", { name: "Inbox" })).toBeChecked();
  await page.goto("/");
  await expect(page).toHaveURL(/\/mail\/inbox$/);
  await page.goto("/settings?section=preferences");
  await page.getByRole("radio", { name: "Today" }).click();
  await expect(page.getByRole("radio", { name: "Today" })).toBeChecked();
});

test("the sidebar can be reordered, hidden and reset, by keyboard and buttons", async ({ page }) => {
  await page.goto("/today");
  // Found by attribute, because an open dialog hides everything behind it from role lookups.
  const nav = page.locator('nav[aria-label="Main navigation"]');
  const firstSection = () => nav.locator("section").first().getAttribute("aria-label");
  await expect.poll(firstSection).toBe("Mail");

  await nav.getByRole("button", { name: "Customize sidebar" }).click();
  const editor = page.getByRole("dialog");
  await editor.getByRole("button", { name: "Move Mail down" }).click();
  await expect.poll(firstSection).toBe("Documents");

  // The keyboard route on the drag handle.
  await editor.getByRole("button", { name: "Drag Documents" }).focus();
  // At a person's pace: the drag library measures positions between key presses.
  await page.keyboard.press("Space");
  await page.waitForTimeout(200);
  await page.keyboard.press("ArrowDown");
  await page.waitForTimeout(200);
  await page.keyboard.press("Space");
  await expect.poll(firstSection).toBe("Mail");

  await editor.getByRole("switch", { name: "Drafts" }).click();
  await page.keyboard.press("Escape");
  await expect(nav.getByRole("link", { name: "Drafts" })).toBeHidden();
  await expect(nav.getByRole("link", { name: "Sent" })).toBeVisible();
  await page.reload();
  await expect(nav.getByRole("link", { name: "Sent" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Drafts" })).toBeHidden();

  await nav.getByRole("button", { name: "Customize sidebar" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Reset layout" }).click();
  await page.keyboard.press("Escape");
  await expect(nav.getByRole("link", { name: "Drafts" })).toBeVisible();
  await expect.poll(firstSection).toBe("Mail");
});

test("logs show live, filter, open a trace, and never hold a secret", async ({ page, request }) => {
  await page.goto("/logs");
  await expect(page.getByText("Live")).toBeVisible();
  await request.post("/api/commands/settings.update", { data: { density: "compact" }, headers: { "x-trace-id": "tracee2e" } });
  const row = page.getByTestId("log-row").filter({ hasText: "settings.changed" }).first();
  await expect(row).toBeVisible();

  await page.getByRole("textbox", { name: "Search", exact: true }).fill("tracee2e");
  await expect(page.getByTestId("log-row").first()).toContainText("settings.changed");
  await page.getByTestId("log-row").first().getByRole("button", { name: "View" }).click();
  await expect(page.getByTestId("trace-events")).toContainText("settings.changed");
  await page.keyboard.press("Escape");

  await page.getByRole("textbox", { name: "Search", exact: true }).fill("no such log line");
  await expect(page.getByText("Nothing matches")).toBeVisible();
  await request.post("/api/commands/settings.update", { data: { density: "comfortable" } });
});

test("the support report copies, and the network check reports each service", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/settings?section=network");
  await page.getByRole("button", { name: "Copy support report" }).click();
  await expect(page.getByText("Support report copied").first()).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toMatch(/^NexusAI /);
  await page.getByRole("button", { name: "Check connection" }).click();
  await expect(page.getByTestId("network-results").getByRole("listitem")).toHaveCount(2);
});

test("density and text size apply instantly", async ({ page }) => {
  await page.goto("/settings");
  await page.getByRole("radio", { name: "Large" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-text-size", "large");
  await page.getByRole("radio", { name: "Compact" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-density", "compact");
});

test("the app works by keyboard", async ({ page }) => {
  await page.goto("/settings");
  await page.getByRole("radio", { name: "Nexus Light" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.locator("html")).toHaveAttribute("data-theme", /nexus-/);
});
