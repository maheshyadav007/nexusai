import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const FAKE = "http://127.0.0.1:8766/__sent";

const noViolations = async (page: Page) => {
  const { violations } = await new AxeBuilder({ page }).analyze();
  expect(violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
};

const newSession = async (page: Page) => {
  await page.goto("/agent/sessions");
  await page.getByRole("button", { name: "New session" }).click();
  await expect(page).toHaveURL(/\/agent\/sessions\/[0-9a-f]{32}$/);
};

const say = async (page: Page, text: string) => {
  await page.getByRole("textbox", { name: "Message the agent" }).fill(text);
  await page.getByRole("button", { name: "Send" }).click();
};

const connect = async (request: APIRequestContext) => {
  await request.post("/api/commands/models.login.start", { data: {} });
  await expect
    .poll(async () => ((await (await request.post("/api/queries/models.status", { data: {} })).json()) as { connected: boolean }).connected, { timeout: 20_000 })
    .toBe(true);
  await request.post("/api/commands/models.select", { data: { model: "gpt-best" } });
};

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ request }) => {
  await request.post("/api/home/choose", { data: { path: `${process.env.E2E_HOME}/NexusAI` } });
  await request.post("/api/commands/onboarding.finish", { data: {} });
  await connect(request);
});

test.afterAll(async ({ request }) => {
  await request.post("/api/commands/models.disconnect", { data: {} });
});

test("a reply streams in, and the session is kept", async ({ page }) => {
  await newSession(page);
  await noViolations(page);
  await say(page, "Hello there");
  const reply = page.getByTestId("agent-message");
  await expect(reply).toContainText("Hello from gpt-best");
  await expect(page.getByTestId("session-status")).toContainText("Done");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Hello there");
  await noViolations(page);

  await page.reload();
  await expect(page.getByTestId("user-message")).toContainText("Hello there");
  await expect(page.getByTestId("agent-message")).toContainText("Hello from gpt-best");

  await page.goto("/agent/sessions");
  await expect(page.getByTestId("session-row").filter({ hasText: "Hello there" })).toContainText("Done");
  await noViolations(page);
});

test("sensitive values stay on this computer, and the final prompt shows both versions", async ({ page }) => {
  await newSession(page);
  const secret = "kim.j@samsung.com";
  await say(page, `Please write to ${secret}`);
  await expect(page.getByTestId("agent-message")).toContainText("Hello from");
  const sent = JSON.stringify(await (await page.request.get(FAKE)).json());
  expect(sent).not.toContain(secret);
  expect(sent).toContain("<EMAIL_");
  await expect(page.getByTestId("user-message")).toContainText(secret);

  await page.getByRole("button", { name: "View final prompt" }).click();
  const task = page.getByTestId("prompt-layer").filter({ hasText: "Task content" });
  await expect(task).not.toContainText(secret);
  await expect(page.getByTestId("prompt-layer").first()).toContainText("System prompt");
  await page.getByRole("button", { name: "Show real values" }).click();
  await expect(task).toContainText(secret);
});

test("a command waits for approval in the session, then runs and finishes", async ({ page }) => {
  await newSession(page);
  await say(page, "please run a command");
  const approval = page.getByTestId("approval");
  await expect(approval).toContainText("Prove commands work");
  await expect(approval).toContainText("echo from-the-agent");
  await expect(page.getByTestId("session-status")).toContainText("Waiting for you");
  await noViolations(page);

  await approval.getByRole("button", { name: "Allow once" }).click();
  await expect(page.getByTestId("agent-message").last()).toContainText("Tool said: from-the-agent");
  await expect(page.getByTestId("tool-call")).toContainText("Done");
  await expect(page.getByTestId("session-status")).toContainText("Done");
});

test("approvals can be answered from the top bar, and a denied command never runs", async ({ page }) => {
  await newSession(page);
  await say(page, "please run a command");
  await expect(page.getByTestId("approval")).toBeVisible();

  await page.goto("/today");
  await page.getByRole("button", { name: "Approvals, 1 waiting" }).click();
  await noViolations(page);
  await page.getByRole("button", { name: "Deny" }).click();
  await expect(page.getByRole("button", { name: "Approvals", exact: true })).toBeVisible();

  await page.goto("/agent/sessions");
  await page.getByTestId("session-row").first().click();
  await expect(page.getByTestId("agent-message").last()).toContainText("Tool said: The person declined this.");
  await expect(page.getByTestId("tool-call")).toContainText("Declined");
});

test("reloading in the middle of a reply reconnects, and nothing is lost", async ({ page }) => {
  await newSession(page);
  await say(page, "a slow answer please");
  await expect(page.getByTestId("agent-message")).toContainText("word3", { timeout: 10_000 });
  await page.reload();
  // Back straight away, with what was already said, and it keeps coming.
  await expect(page.getByTestId("agent-message")).toContainText("word0 word1 word2", { timeout: 5_000 });
  await expect(page.getByTestId("agent-message")).toContainText("word29", { timeout: 15_000 });
  await expect(page.getByTestId("session-status")).toContainText("Done");
  const text = await page.getByTestId("agent-message").innerText();
  expect(text.match(/word0 /g)).toHaveLength(1);
});

test("leaving and coming back while it works shows the live reply", async ({ page }) => {
  await newSession(page);
  const url = page.url();
  await say(page, "another slow answer");
  await expect(page.getByTestId("agent-message")).toContainText("word1", { timeout: 10_000 });
  await page.goto("/today");
  await page.goto(url);
  await expect(page.getByTestId("agent-message")).toContainText("word29", { timeout: 15_000 });
});

test("stop ends the work, and the session can carry on", async ({ page }) => {
  await newSession(page);
  await say(page, "slow one to stop");
  await expect(page.getByTestId("agent-message")).toContainText("word1", { timeout: 10_000 });
  await page.getByRole("button", { name: "Stop" }).click();
  await expect(page.getByTestId("session-status")).toContainText("Stopped", { timeout: 10_000 });
  const text = await page.getByTestId("agent-message").innerText();
  expect(text).not.toContain("word29");
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
  await say(page, "Hello again");
  await expect(page.getByTestId("agent-message").last()).toContainText("Hello from");
});
