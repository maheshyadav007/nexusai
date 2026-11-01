import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { FONT_CATALOG } from "../ui/theme/font-catalog";

const background = (page: import("@playwright/test").Page) =>
  page.evaluate(() => getComputedStyle(document.body).backgroundColor);

const SCREENS = ["/today", "/settings", "/mail/inbox", "/gallery", "/gallery/shell"];

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

test("an unknown path is a real 404", async ({ page }) => {
  const response = await page.goto("/no-such-screen");
  expect(response?.status()).toBe(404);
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
  await expect(page.getByTestId("event-row").first()).toContainText("settings.changed");
  await expect(page.getByTestId("event-row").first()).toContainText("nexus-dark");

  // The second window was told by an event; it did not ask.
  await expect(other.getByRole("radio", { name: "Nexus Dark" })).toBeChecked();
  await expect.poll(() => background(other)).not.toBe(lightBackground);
  await expect(other.getByTestId("event-row").first()).toContainText("settings.changed");

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
  await page.goto("/settings");
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
