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

  await expect(page.getByRole("heading", { name: "Save your recovery key" })).toBeVisible();
  await expect(page.getByTestId("recovery-key")).toHaveText(/^([0-9A-Z]{4}-){7}[0-9A-Z]{4}$/);
  await noViolations(page);
  // There's no way past it without saying it's saved, and then it can't be shown again.
  await expect(page.getByRole("button", { name: "Continue" })).toBeDisabled();
  await page.getByRole("checkbox", { name: "I've saved my recovery key somewhere safe" }).click();
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByRole("heading", { name: "Tell NexusAI about you" })).toBeVisible();
  // How it looks is chosen here too, and takes effect right away.
  await expect(page.getByRole("radiogroup", { name: "Theme" })).toBeVisible();
  await page.getByRole("textbox", { name: "Name" }).fill("Asha Rao");
  await noViolations(page);
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByRole("heading", { name: "Connect your mail" })).toBeVisible();
  await noViolations(page);
  await page.getByRole("button", { name: "Continue" }).click();

  // Closing midway resumes at the same step.
  await expect(page.getByRole("heading", { name: "Connect a model" })).toBeVisible();
  await page.goto("/");
  await expect(page).toHaveURL(/\/setup$/);
  await expect(page.getByRole("heading", { name: "Connect a model" })).toBeVisible();
  await noViolations(page);

  await page.getByRole("button", { name: "Back" }).click();
  await expect(page.getByRole("heading", { name: "Connect your mail" })).toBeVisible();
  await page.getByRole("button", { name: "Back" }).click();
  await expect(page.getByRole("textbox", { name: "Name" })).toHaveValue("Asha Rao");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Connect your mail" })).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();

  await page.getByRole("button", { name: "Continue" }).click();
  // Getting there starts the download, and the next step doesn't wait for it. Downloads are blocked
  // in this test environment, so this also shows what a blocked corporate network sees.
  await expect(page.getByRole("heading", { name: "Find things by what they're about" })).toBeVisible();
  await expect(page.getByTestId("local-model").getByRole("alert")).toContainText(/mirror/);
  await expect(page.getByLabel("Download from your company's mirror")).toBeVisible();
  await noViolations(page);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "What may the agent do?" })).toBeVisible();
  await expect(page.getByRole("radio", { name: /Balanced/ })).toBeChecked();
  await noViolations(page);
  await page.getByRole("button", { name: "Enter NexusAI" }).click();
  await expect(page).toHaveURL(/\/today$/);

  // What setup skipped waits here, and goes away when asked.
  const checklist = page.getByTestId("finish-setup");
  await expect(checklist.getByText("Let the agent get to know you")).toBeVisible();
  await expect(checklist.getByText("Bring in old mail")).toBeVisible();
  await noViolations(page);

  // Returning people go straight in.
  await page.goto("/");
  await expect(page).toHaveURL(/\/today$/);
  await page.goto("/welcome");
  await expect(page).toHaveURL(/\/today$/);
  await page.goto("/setup");
  await expect(page).toHaveURL(/\/today$/);
});

test("a locked Home asks for its recovery key and says when it's wrong", async ({ page }) => {
  await page.route("**/api/home/status", (route) => route.fulfill({ json: { state: "locked", default_path: "/tmp", path: "/moved/NexusAI", message: "This Home is encrypted. Enter its recovery key to open it on this computer." } }));
  await page.route("**/api/home/unlock", (route) => route.fulfill({ status: 422, json: { code: "home.wrong_key", message: "That recovery key doesn't match this Home." } }));
  await page.goto("/today");
  await expect(page).toHaveURL(/\/recover$/);
  await expect(page.getByText("This Home is encrypted")).toBeVisible();
  await noViolations(page);
  await page.getByRole("textbox", { name: "Recovery key" }).fill("AAAA-BBBB");
  await page.getByRole("button", { name: "Open my data" }).click();
  await expect(page.getByText("That recovery key doesn't match this Home.")).toBeVisible();
  await noViolations(page);
});

test("a damaged Home offers its backups, and says when there are none", async ({ page }) => {
  await page.route("**/api/home/status", (route) => route.fulfill({ json: { state: "damaged", default_path: "/tmp", path: "/here/NexusAI", message: "NexusAI can't read its database, which may be damaged." } }));
  let rows = [{ name: "20261101-060000-000000-daily", reason: "daily", time: "2026-11-01T06:00:00+00:00", size: 1000 }];
  await page.route("**/api/home/backups", (route) => route.fulfill({ json: { backups: rows } }));
  await page.goto("/today");
  await expect(page).toHaveURL(/\/recover$/);
  await expect(page.getByTestId("backup").getByRole("button", { name: "Restore" })).toBeVisible();
  await noViolations(page);
  rows = [];
  await page.reload();
  await expect(page.getByText("There are no backups to restore from.")).toBeVisible();
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
