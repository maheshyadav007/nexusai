import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const noViolations = async (page: Page) => {
  const { violations } = await new AxeBuilder({ page }).analyze();
  expect(violations.map((v) => ({ rule: v.id, nodes: v.nodes.map((n) => ({ target: n.target, html: n.html, reason: n.failureSummary })) }))).toEqual([]);
};

// Runs before the other files: the backend starts with no Home, as on a new computer.
test("a new person goes from landing through setup into the app, and setup resumes", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
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

  await expect(page.getByRole("heading", { name: "Tell NexusAI about you" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Important people" })).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "About me" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Continue", exact: true })).toBeInViewport({ ratio: 1 });
  await page.screenshot({ path: "test-results/review-profile.png" });
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("Asha Rao");
  await noViolations(page);
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByRole("heading", { name: "Connect your mail" })).toBeVisible();
  await noViolations(page);
  await page.getByRole("button", { name: "Skip for now" }).click();

  // Closing midway resumes at the same step.
  await expect(page.getByRole("heading", { name: "Find things by what they're about" })).toBeVisible();
  await page.goto("/");
  await expect(page).toHaveURL(/\/setup$/);
  await expect(page.getByRole("heading", { name: "Find things by what they're about" })).toBeVisible();
  await noViolations(page);

  await page.getByRole("button", { name: "Back" }).click();
  await expect(page.getByRole("heading", { name: "Connect your mail" })).toBeVisible();
  await page.getByRole("button", { name: "Back" }).click();
  await expect(page.getByRole("textbox", { name: "Name", exact: true })).toHaveValue("Asha Rao");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Connect your mail" })).toBeVisible();
  await page.getByRole("button", { name: "Skip for now" }).click();

  // Nothing downloads until asked. Downloads are blocked in this test environment, so this also
  // shows what a blocked corporate network sees, and skipping still moves on.
  await expect(page.getByRole("heading", { name: "Find things by what they're about" })).toBeVisible();
  await expect(page.getByTestId("local-model").getByRole("alert")).toHaveCount(0);
  await page.getByTestId("local-model").getByRole("button", { name: /Download/ }).click();
  await expect(page.getByTestId("local-model").getByRole("alert")).toContainText(/mirror/);
  await expect(page.getByLabel("Download from your company's mirror")).toBeVisible();
  await noViolations(page);
  await page.getByRole("button", { name: "Skip for now" }).click();
  await expect(page.getByRole("heading", { name: "What may the agent do?" })).toBeVisible();
  await expect(page.getByRole("radio", { name: /Balanced/ })).toBeChecked();
  await noViolations(page);
  await page.getByRole("button", { name: "Enter NexusAI" }).click();
  await expect(page).toHaveURL(/\/today$/);
  await expect(page.getByTestId("posty-guide")).toHaveCount(0);

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

test("the folder picker can make a folder, jump to a place, and always has a way out", async ({ page }) => {
  await page.route("**/api/home/status", (route) => route.fulfill({ json: { state: "unset", default_path: "/tmp", path: null, message: null } }));
  await page.goto("/setup");
  await page.getByRole("button", { name: "Browse" }).click();
  const shown = page.getByTestId("picker-path");
  await expect(shown).not.toHaveText("");

  // A folder that can't be opened says so, and leaves Up and the other places working.
  await page.route("**/api/home/browse", (route) => route.fulfill({ json: { path: "/locked", parent: "/", folders: [], files: [], drives: [], problem: "You don't have permission to open this folder." } }));
  await page.getByTestId("picker-go").fill("/locked");
  await page.getByTestId("picker-go").press("Enter");
  await expect(page.getByTestId("picker-problem")).toBeVisible();
  await expect(page.getByRole("button", { name: "Up one level" })).toBeVisible();
  await noViolations(page);

  // Even a failed request leaves a way back.
  await page.route("**/api/home/browse", (route) => route.fulfill({ status: 500, body: "Internal Server Error" }));
  await page.getByTestId("picker-go").fill("/broken/here");
  await page.getByTestId("picker-go").press("Enter");
  await expect(page.getByText("Couldn't open that folder")).toBeVisible();
  await expect(page.getByRole("button", { name: "Up one level" })).toBeVisible();
  await page.unroute("**/api/home/browse");

  await page.getByTestId("picker-home").click();
  await expect(page.getByRole("button", { name: "Use this folder" }).last()).toBeEnabled();
  await page.getByTestId("picker-current").click();
  await expect(shown).not.toHaveText(".");

  await page.getByTestId("picker-go").fill("/tmp");
  await page.getByTestId("picker-go").press("Enter");
  const name = `nexusai-e2e-${Date.now()}`;
  await page.getByTestId("picker-new").click();
  await page.getByTestId("picker-new-name").fill(name);
  await page.getByRole("button", { name: "Create" }).click();
  await expect(shown).toContainText(name);
  await page.keyboard.press("Escape");
  await page.getByTestId("use-current-folder").click();
  await expect(page.getByRole("textbox", { name: "Folder" })).not.toHaveValue("/tmp");
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
