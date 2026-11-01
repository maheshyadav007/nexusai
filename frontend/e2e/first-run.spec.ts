import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const noViolations = async (page: Page) => {
  const { violations } = await new AxeBuilder({ page }).analyze();
  expect(violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
};

// Runs before the other files: the backend starts with no Home, as on a new computer.
test("a new person goes from landing through setup into the app, and setup resumes", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/welcome$/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await noViolations(page);
  for (const path of ["/today", "/settings"]) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/welcome$/);
  }

  await page.getByRole("button", { name: "Get started" }).click();
  await expect(page).toHaveURL(/\/setup$/);
  await expect(page.getByRole("heading", { name: "Where should NexusAI keep your data?" })).toBeVisible();
  await noViolations(page);

  const field = page.getByRole("textbox", { name: "Folder" });
  await field.fill(`${process.env.E2E_HOME}/NexusAI`);
  await expect(page.getByText(/free on this drive/)).toBeVisible();
  await page.getByRole("button", { name: "Use this folder" }).click();

  await expect(page.getByRole("heading", { name: "Choose how it looks" })).toBeVisible();
  await noViolations(page);
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByRole("heading", { name: "Tell NexusAI about you" })).toBeVisible();
  await page.getByRole("textbox", { name: "Name" }).fill("Asha Rao");
  await noViolations(page);
  await page.getByRole("button", { name: "Continue" }).click();

  // Closing midway resumes at the same step.
  await expect(page.getByRole("heading", { name: "Connect a model" })).toBeVisible();
  await page.goto("/");
  await expect(page).toHaveURL(/\/setup$/);
  await expect(page.getByRole("heading", { name: "Connect a model" })).toBeVisible();
  await noViolations(page);

  await page.getByRole("button", { name: "Back" }).click();
  await expect(page.getByRole("textbox", { name: "Name" })).toHaveValue("Asha Rao");
  await page.getByRole("button", { name: "Continue" }).click();

  await page.getByRole("button", { name: "Enter NexusAI" }).click();
  await expect(page).toHaveURL(/\/today$/);

  // Returning people go straight in.
  await page.goto("/");
  await expect(page).toHaveURL(/\/today$/);
  await page.goto("/welcome");
  await expect(page).toHaveURL(/\/today$/);
  await page.goto("/setup");
  await expect(page).toHaveURL(/\/today$/);
});

test("the folder chooser shows problems and browses folders", async ({ page }) => {
  await page.route("**/api/home/status", (route) => route.fulfill({ json: { state: "unset", default_path: "/tmp", path: null, message: null } }));
  await page.route("**/api/home/check", (route) => route.fulfill({ json: { path: "/net/x", ok: false, problems: ["That's a network drive. Choose a folder on this computer."], warnings: [], free_bytes: null, is_existing_home: false } }));
  await page.goto("/setup");
  await expect(page.getByText("That's a network drive")).toBeVisible();
  await expect(page.getByRole("button", { name: "Use this folder" })).toBeDisabled();

  await page.getByRole("button", { name: "Browse" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("button", { name: "Up one level" })).toBeVisible();
  await noViolations(page);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
});

test("a missing Home shows recovery and is never recreated silently", async ({ page }) => {
  const status = { state: "missing", default_path: "/tmp/NexusAI", path: "/Volumes/Gone/NexusAI", message: "NexusAI can't find your Home at this location." };
  await page.route("**/api/home/status", (route) => route.fulfill({ json: status }));
  await page.route("**/api/home/check", (route) => route.fulfill({ json: { path: "/Volumes/Gone/NexusAI", ok: true, problems: [], warnings: [], free_bytes: 1, is_existing_home: false } }));
  await page.goto("/today");
  await expect(page).toHaveURL(/\/recover$/);
  await expect(page.getByText("/Volumes/Gone/NexusAI")).toBeVisible();
  await expect(page.getByText("This folder isn't a NexusAI Home")).toBeVisible();
  await expect(page.getByRole("button", { name: "Open this Home" })).toBeDisabled();
  await noViolations(page);

  await page.getByRole("button", { name: "Start with a new Home instead" }).click();
  await expect(page.getByRole("button", { name: "Create new Home" })).toBeVisible();
});
