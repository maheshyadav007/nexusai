import { expect, test } from "@playwright/test";

test.beforeAll(async ({ request }) => {
  await request.post("/api/home/choose", { data: { path: `${process.env.E2E_HOME}/NexusAI` } });
  await request.post("/api/commands/onboarding.finish", { data: {} });
});

test("password visibility toggles without changing the secret", async ({ page }) => {
  await page.goto("/connectors");
  await page.getByRole("button", { name: /^Email / }).click();
  const password = page.getByLabel("Password", { exact: true });
  await password.fill("test-only-secret");
  await expect(password).toHaveAttribute("type", "password");
  await page.getByRole("button", { name: "Show password", exact: true }).click();
  await expect(password).toHaveAttribute("type", "text");
  await expect(password).toHaveValue("test-only-secret");
  await page.getByRole("button", { name: "Hide password", exact: true }).click();
  await expect(password).toHaveAttribute("type", "password");
});

test("desktop header integrates actions and exposes staged update controls", async ({ page }) => {
  await page.addInitScript(() => {
    let phase: "idle" | "available" | "ready" = "idle";
    const status = async () => ({ state: phase, version: "0.1.0", availableVersion: phase === "idle" ? null : "0.1.1", percent: phase === "ready" ? 100 : 0, error: null, configured: true });
    window.nexusDesktop = {
      platform: "win32", caption: async () => {}, status,
      action: async action => { if (action === "check") phase = "available"; if (action === "download") phase = "ready"; return status(); },
      notify: async () => true,
    };
  });
  await page.route("**/api/queries/categories.list", route => route.fulfill({ json: { categories: Array.from({ length: 25 }, (_, index) => ({ name: `Category ${index + 1}`, in_priority: false, proposed: false, count: 1, unread: 0 })) } }));
  await page.goto("/today");
  await expect(page.locator(".desktop-caption")).toBeVisible();
  await expect(page.locator("#nexus-window-tools")).not.toBeEmpty();
  await expect(page.locator("header.h-topbar")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Categories and custom folders" })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  await nav.getByRole("link", { name: "Tasks", exact: true }).scrollIntoViewIfNeeded();
  await expect(nav.getByRole("link", { name: "Tasks", exact: true })).toBeInViewport();
  await nav.getByRole("link", { name: "Sessions", exact: true }).scrollIntoViewIfNeeded();
  await expect(nav.getByRole("link", { name: "Sessions", exact: true })).toBeInViewport();
  await expect(nav.getByRole("link", { name: "Today", exact: true })).toBeInViewport();
  await page.screenshot({ path: "test-results/beta-today-desktop.png", fullPage: true });
  await page.getByTestId("assistant-pill").click();
  const caption = await page.locator(".desktop-caption").boundingBox();
  await expect(page.getByTestId("assistant-dock")).toHaveCSS("top", `${caption!.y + caption!.height}px`);
  await page.getByRole("button", { name: "Minimize", exact: true }).click();
  await page.getByTestId("account-menu-trigger").click();
  await expect(page.getByRole("menuitem", { name: "Restart NexusAI" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "Quit NexusAI" })).toBeVisible();
  await page.getByRole("menuitem", { name: "About & Updates" }).click();
  await page.getByRole("button", { name: "Check for updates", exact: true }).click();
  await expect(page.getByRole("button", { name: "Download update", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Download update", exact: true }).click();
  await expect(page.getByRole("button", { name: "Restart to install", exact: true })).toBeVisible();
  await page.screenshot({ path: "test-results/beta-about-updates.png", fullPage: true });
});

test("chat launcher stays fixed at the right and the document does not scroll", async ({ page }) => {
  await page.setViewportSize({ width: 1080, height: 720 });
  await page.goto("/today");
  const pill = page.getByTestId("assistant-pill");
  await expect(pill).toBeInViewport({ ratio: 1 });
  await expect(pill).toHaveCSS("position", "fixed");
  const box = await pill.boundingBox();
  expect(box!.x).toBeGreaterThan(800);
  expect(box!.y + box!.height).toBeLessThanOrEqual(720);
  expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBeLessThanOrEqual(720);
  await expect(page.locator("html")).toHaveCSS("overscroll-behavior", "none");
  await page.mouse.move(900, 400);
  await page.mouse.wheel(0, 1000);
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  await expect(pill).toBeInViewport({ ratio: 1 });
  await page.screenshot({ path: "test-results/review-today.png" });
});

test("empty categories remain in the sidebar after creating another and navigating away", async ({ page }) => {
  await page.goto("/today");
  const names = [`Review empty A ${Date.now()}`, `Review empty B ${Date.now()}`];
  for (const name of names) {
    await page.getByRole("button", { name: "New category", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("textbox", { name: "Name", exact: true }).fill(name);
    await dialog.getByRole("button", { name: "Create category", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(encodeURIComponent(name) + "$"));
  }
  await page.getByRole("link", { name: "Today", exact: true }).click();
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  for (const name of names) await expect(nav.getByRole("link", { name, exact: true })).toBeVisible();
  await page.reload();
  for (const name of names) await expect(nav.getByRole("link", { name, exact: true })).toBeVisible();
});

test("web settings offer browser actions instead of desktop process controls", async ({ page }) => {
  await page.goto("/today");
  await page.getByTestId("account-menu-trigger").click();
  await expect(page.getByRole("menuitem", { name: "Close tab", exact: true })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "Quit NexusAI" })).toHaveCount(0);
  await page.getByRole("menuitem", { name: "Reload tab", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
});
