import { expect, test } from "@playwright/test";

const background = (page: import("@playwright/test").Page) =>
  page.evaluate(() => getComputedStyle(document.body).backgroundColor);

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
