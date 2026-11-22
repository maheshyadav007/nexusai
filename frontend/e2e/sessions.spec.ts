import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const FAKE = "http://127.0.0.1:8766/__sent";

const noViolations = async (page: Page) => {
  // Cards fade in, and contrast can't be judged halfway through.
  await page.waitForTimeout(300);
  const { violations } = await new AxeBuilder({ page }).analyze();
  expect(violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
};

// A new chat on its own page. The session itself starts with the first message.
const newSession = async (page: Page) => {
  await page.goto("/agent/sessions/new?view=full");
  await expect(page.getByRole("textbox", { name: "Message the agent" })).toBeVisible();
};

const SESSION_PAGE = /\/agent\/sessions\/[0-9a-f]{32}\?view=full$/;

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
  await expect(page).toHaveURL(SESSION_PAGE);
  const reply = page.getByTestId("agent-message");
  await expect(reply).toContainText("Hello from gpt-best");
  await expect(page.getByTestId("session-status")).toContainText("Done");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Hello there");
  await noViolations(page);

  await page.reload();
  await expect(page.getByTestId("user-message")).toContainText("Hello there");
  await expect(page.getByTestId("agent-message")).toContainText("Hello from gpt-best");

  await page.goto("/agent/sessions");
  // Finished, it shows the start of its reply under the title.
  const row = page.getByTestId("session-row").filter({ hasText: "Hello there" });
  await expect(row).toHaveAttribute("data-state", "done");
  await expect(row).toContainText("Hello from gpt-best");
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

  await approval.getByRole("button", { name: "Approve once" }).click();
  await expect(page.getByTestId("agent-message").last()).toContainText("Tool said: from-the-agent");
  await page.getByTestId("thinking").getByRole("button").first().click();
  await expect(page.getByTestId("tool-call")).toContainText("Ran command");
  await expect(page.getByTestId("session-status")).toContainText("Done");
});

test("approvals can be answered from the top bar, and a denied command never runs", async ({ page }) => {
  await newSession(page);
  await say(page, "please run a command");
  await expect(page.getByTestId("approval")).toBeVisible();

  await page.goto("/today");
  // The shield holds everything waiting for the person: approvals, questions and suggestions.
  await page.getByRole("button", { name: /^Waiting for you, \d+$/ }).click();
  const waiting = page.getByRole("dialog", { name: "Waiting for you" });
  await expect(waiting.getByRole("button", { name: "Deny" })).toBeVisible();
  await noViolations(page);
  // Today shows the same approval, so this answers the one in the top bar's list.
  await waiting.getByRole("button", { name: "Deny" }).click();
  await expect(waiting.getByRole("button", { name: "Deny" })).toHaveCount(0);

  await page.goto("/agent/sessions");
  // Agent chats are listed first now, so pick this conversation by what was said.
  await page.getByTestId("session-row").filter({ hasText: "please run a command" }).first().click();
  await expect(page.getByTestId("agent-message").last()).toContainText("Tool said: The person declined this.");
  await page.getByTestId("thinking").getByRole("button").first().click();
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
  await say(page, "another slow answer");
  await expect(page).toHaveURL(SESSION_PAGE);
  const url = page.url();
  await expect(page.getByTestId("agent-message")).toContainText("word1", { timeout: 10_000 });
  await page.goto("/today");
  await page.goto(url);
  await expect(page.getByTestId("agent-message")).toContainText("word29", { timeout: 15_000 });
});

test("stop ends the work, and the session can carry on", async ({ page }) => {
  await newSession(page);
  await say(page, "slow one to stop");
  await expect(page.getByTestId("agent-message")).toContainText("word1", { timeout: 10_000 });
  await page.getByRole("button", { name: "Stop", exact: true }).click();
  await expect(page.getByTestId("session-status")).toContainText("Stopped", { timeout: 10_000 });
  const text = await page.getByTestId("agent-message").innerText();
  expect(text).not.toContain("word29");
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
  await say(page, "Hello again");
  await expect(page.getByTestId("agent-message").last()).toContainText("Hello from");
});
