import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const CONTROL = "http://127.0.0.1:8767/";
const USER = "tester@example.com";
const unique = (word: string) => `${word} ${Date.now()}${Math.floor(Math.random() * 1000)}`;

const noViolations = async (page: Page) => {
  // Cards fade in, and contrast can't be judged halfway through.
  await page.waitForTimeout(300);
  const { violations } = await new AxeBuilder({ page }).exclude("iframe").analyze();
  expect(violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
};

const openFresh = async (page: Page) => {
  await page.goto("/agent/sessions");
  await page.getByRole("button", { name: "New session" }).click();
  await expect(page).toHaveURL(/\/agent\/sessions\/[0-9a-f]{32}$/);
};

const say = async (page: Page, text: string) => {
  await page.getByRole("textbox", { name: "Message the agent" }).fill(text);
  await page.getByRole("button", { name: "Send" }).click();
};

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ request }) => {
  await request.post("/api/home/choose", { data: { path: `${process.env.E2E_HOME}/NexusAI` } });
  await request.post("/api/commands/onboarding.finish", { data: {} });
  await request.post("/api/commands/models.login.start", { data: {} });
  await expect
    .poll(async () => ((await (await request.post("/api/queries/models.status", { data: {} })).json()) as { connected: boolean }).connected, { timeout: 20_000 })
    .toBe(true);
  await request.post("/api/commands/models.select", { data: { model: "gpt-best" } });
  await request.post("/api/commands/mail.accounts.save", {
    data: {
      name: "chat",
      password: "test-password",
      profile: { label: "Chat", imap: { host: "127.0.0.1", port: 8143, secure: false }, smtp: { host: "127.0.0.1", port: 8025, secure: false }, auth: { type: "password", user: USER }, mailboxes: ["INBOX"] },
    },
  });
  await expect
    .poll(async () => ((await (await request.post("/api/queries/mail.status", { data: {} })).json()) as { state: string }).state, { timeout: 20_000 })
    .toBe("live");
});

test.afterAll(async ({ request }) => {
  await request.post("/api/commands/mail.accounts.remove", { data: { name: "chat" } });
  await request.post("/api/commands/models.disconnect", { data: {} });
});

test("a question appears as choices in the chat, and picking one carries on", async ({ page }) => {
  await openFresh(page);
  await say(page, "ask me something");
  const card = page.getByTestId("question-card");
  await expect(card).toContainText("Which day works?");
  await expect(page.getByTestId("session-status")).toContainText("Waiting");
  await noViolations(page);
  await card.getByRole("radio", { name: "Tuesday" }).click();
  await expect(page.getByTestId("answered-question")).toContainText("Tuesday");
  await expect(page.getByTestId("session-status")).toContainText("Done");
  await expect(page.getByTestId("agent-message")).toContainText("Tool said: They answered: Tuesday");
});

test("while asked, the message box answers it instead of hanging", async ({ page }) => {
  await openFresh(page);
  await say(page, "ask me something");
  await expect(page.getByTestId("question-card")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Message the agent" })).toHaveAttribute("placeholder", "Type your answer");
  await say(page, "Whenever suits");
  await expect(page.getByTestId("agent-message")).toContainText("They answered: Whenever suits");
});

test("several choices wait for Continue, and a reload doesn't lose the question", async ({ page }) => {
  await openFresh(page);
  await say(page, "ask me something with several answers");
  await expect(page.getByTestId("question-card")).toBeVisible();
  await page.reload();
  const card = page.getByTestId("question-card");
  await card.getByRole("checkbox", { name: "Monday" }).click();
  await card.getByRole("checkbox", { name: "Tuesday" }).click();
  await expect(page.getByTestId("answered-question")).toHaveCount(0);
  await card.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByTestId("answered-question")).toContainText("Monday, Tuesday");
});

test("a reply shows formatted, with copy, a time and clickable next steps", async ({ page }) => {
  await openFresh(page);
  await say(page, "offer next steps");
  const reply = page.getByTestId("agent-message");
  await expect(reply.locator("strong")).toHaveText("answer");
  await expect(reply).not.toContainText("followups");
  await expect(reply.getByRole("button", { name: "Copy" })).toHaveCount(1);
  await expect(reply.locator("time")).toHaveCount(1);
  const rows = page.getByRole("list", { name: "Suggested next steps" });
  await expect(rows.getByRole("button")).toHaveCount(2);
  await noViolations(page);
  await rows.getByRole("button", { name: "Tell me more" }).click();
  await expect(page.getByTestId("user-message").last()).toContainText("Tell me more");
  await expect(page.getByRole("list", { name: "Suggested next steps" })).toHaveCount(0);
});

test("a message can be copied and edited, and the conversation goes back to it", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await openFresh(page);
  await say(page, "Hello first");
  await expect(page.getByTestId("agent-message")).toContainText("Hello from");
  await say(page, "Hello second");
  await expect(page.getByTestId("agent-message")).toHaveCount(2);
  const mine = page.getByTestId("user-message").first();
  await mine.hover();
  await mine.getByRole("button", { name: "Copy" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("Hello first");
  await mine.getByRole("button", { name: "Edit" }).click();
  await page.getByRole("textbox", { name: "Edit" }).fill("Hello edited");
  await page.getByTestId("user-message-edit").getByRole("button", { name: "Send" }).click();
  await expect(page.getByTestId("user-message")).toHaveCount(1);
  await expect(page.getByTestId("user-message")).toContainText("Hello edited");
  await expect(page.getByTestId("agent-message")).toHaveCount(1);
  await page.reload();
  await expect(page.getByTestId("user-message")).toContainText("Hello edited");
});

test("work folds behind a thinking line that opens to each step", async ({ page }) => {
  await openFresh(page);
  await say(page, "run a command");
  const approval = page.getByTestId("approval");
  await expect(approval).toBeVisible();
  await noViolations(page);
  await approval.getByRole("button", { name: "Allow once" }).click();
  await expect(page.getByTestId("agent-message")).toContainText("Tool said:");
  const thinking = page.getByTestId("thinking");
  await expect(thinking).toContainText("1 step");
  await expect(page.getByTestId("tool-call")).toHaveCount(0);
  await thinking.getByRole("button").first().click();
  await expect(page.getByTestId("tool-call")).toContainText("Ran command");
});

test("a reminder asked for is set, and shows as a card that links to it", async ({ page }) => {
  await openFresh(page);
  await say(page, "remind me to call");
  const card = page.getByTestId("result-card");
  await expect(card).toContainText("Call the vendor");
  await card.getByRole("link", { name: "Open reminders" }).click();
  await expect(page.getByTestId("reminder").filter({ hasText: "Call the vendor" })).toBeVisible();
  await expect(page.getByTestId("reminder").filter({ hasText: "Call the vendor" }).getByRole("button", { name: "Accept" })).toHaveCount(0);
});

test("sending mail shows the mail itself, and nothing goes without a yes", async ({ page }) => {
  await openFresh(page);
  await say(page, "send an email");
  const card = page.getByTestId("mail-card");
  await expect(card).toContainText("sam@example.com");
  await expect(card).toContainText("Here they are.");
  await noViolations(page);
  await card.getByRole("button", { name: "Don't send" }).click();
  await expect(card).toContainText("Not sent");
  const sent = (await (await page.request.get(CONTROL)).json()) as { raw: string }[];
  expect(sent.filter((item) => item.raw.includes("Here they are."))).toEqual([]);
});

test("many requests at once are one decision, and one can be left out", async ({ page, request }) => {
  const current = await (await request.post("/api/queries/permissions.get", { data: {} })).json();
  await request.post("/api/commands/permissions.save", { data: { ...current, tools: { ...current.tools, create_tasks: "ask" } } });
  await openFresh(page);
  await say(page, "add three tasks");
  const group = page.getByTestId("approval-group");
  await expect(group).toContainText("3 requests");
  await expect(page.getByTestId("approval")).toHaveCount(0);
  await noViolations(page);
  await group.getByRole("checkbox", { name: "Second task" }).click();
  await group.getByRole("button", { name: "Allow 2" }).click();
  await expect(page.getByTestId("session-status")).toContainText("Done");
  await page.goto("/planner/tasks");
  await expect(page.getByTestId("task").filter({ hasText: "First task" })).toBeVisible();
  await expect(page.getByTestId("task").filter({ hasText: "Third task" })).toBeVisible();
  await expect(page.getByTestId("task").filter({ hasText: "Second task" })).toHaveCount(0);

  await openFresh(page);
  await say(page, "add three tasks");
  await page.getByTestId("approval-group").getByRole("button", { name: "Allow for this session" }).click();
  await expect(page.getByTestId("session-status")).toContainText("Done");
  await expect(page.getByTestId("approval-group")).toHaveCount(0);
  await request.post("/api/commands/permissions.save", { data: current });
});

test("the chat follows you around, minimizes to a pill, and remembers", async ({ page }) => {
  await page.goto("/today");
  await page.getByTestId("assistant-pill").click();
  const dock = page.getByTestId("assistant-dock");
  await expect(dock).toBeVisible();
  await noViolations(page);
  await dock.getByRole("button", { name: "Set a reminder for me" }).click();
  await expect(dock.getByTestId("user-message")).toContainText("Set a reminder for me");
  await expect(dock.getByTestId("agent-message")).toBeVisible();

  await page.goto("/mail/all");
  await expect(page.getByTestId("assistant-dock").getByTestId("user-message")).toContainText("Set a reminder for me");
  await page.getByRole("button", { name: "Minimize" }).click();
  await expect(page.getByTestId("assistant-dock")).toHaveCount(0);
  await expect(page.getByTestId("assistant-pill")).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("assistant-pill")).toBeVisible();
});

test("what an agent asks elsewhere pops up at the bottom right, and opens the chat", async ({ page, request }) => {
  await page.goto("/mail/all");
  await expect(page.getByTestId("assistant-pill")).toBeVisible();
  const session = ((await (await request.post("/api/commands/session.create", { data: { title: "Elsewhere" } })).json()) as { id: string }).id;
  void request.post("/api/sessions/chat", { data: { id: session, text: "ask me something" } }).catch(() => undefined);
  const toast = page.getByTestId("agent-toast").filter({ hasText: "Which day works?" });
  await expect(toast).toBeVisible({ timeout: 15_000 });
  await noViolations(page);
  await expect(page.getByRole("link", { name: "Sessions" })).toContainText("1");
  await toast.getByRole("button", { name: "Answer" }).click();
  await expect(page.getByTestId("assistant-dock").getByTestId("question-card")).toContainText("Which day works?");
  await page.getByTestId("assistant-dock").getByRole("radio", { name: "Monday" }).click();
  await expect(page.getByTestId("assistant-dock").getByTestId("answered-question")).toContainText("Monday");
  await page.getByRole("button", { name: "Minimize" }).click();
});

test("a session waiting on you is first in the list and says so at the top", async ({ page, request }) => {
  const session = ((await (await request.post("/api/commands/session.create", { data: { title: "Waiting one" } })).json()) as { id: string }).id;
  void request.post("/api/sessions/chat", { data: { id: session, text: "ask me something" } }).catch(() => undefined);
  await page.goto("/agent/sessions");
  const group = page.getByRole("region", { name: "Waiting on you" });
  await expect(group.getByTestId("session-row").filter({ hasText: "Waiting one" })).toBeVisible({ timeout: 15_000 });
  await noViolations(page);
  await group.getByTestId("session-row").filter({ hasText: "Waiting one" }).click();
  const place = page.getByRole("navigation", { name: "Where you are" });
  await expect(place.getByRole("link", { name: "Sessions" })).toBeVisible();
  await expect(place).toContainText("Waiting one");
  await expect(page.getByTestId("session-status")).toContainText("Waiting");
  await page.getByTestId("question-card").getByRole("radio", { name: "Monday" }).click();
  await expect(page.getByTestId("session-status")).toContainText("Done");
});

test("the Mail agent's record can't be messaged", async ({ page }) => {
  await page.request.post(CONTROL, { data: { subject: unique("Readonly"), body: "Please review." } });
  await page.goto("/agent/sessions/mail-agent");
  await expect(page.getByText("This agent works by itself")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("textbox", { name: "Message the agent" })).toHaveCount(0);
});

test("mail has folders, a reading pane, and categories people make", async ({ page }) => {
  const subject = unique("Invoice");
  await page.goto("/mail/all");
  await page.request.post(CONTROL, { data: { subject, body: "Your invoice.", sender: "Billing <billing@vendor.example>" } });
  const row = page.getByTestId("thread-row").filter({ hasText: subject });
  await expect(row).toBeVisible({ timeout: 15_000 });
  await noViolations(page);
  await row.getByRole("link").click();
  await expect(page).toHaveURL(/\/mail\/all\/\d+$/);
  // The list stays beside what's being read.
  await expect(page.getByTestId("thread-row").filter({ hasText: subject })).toBeVisible();
  await expect(page.getByRole("heading", { name: subject })).toBeVisible();
  await noViolations(page);

  await page.getByRole("button", { name: "New category" }).click();
  await noViolations(page);
  await page.getByRole("textbox", { name: "Name" }).fill("Invoices");
  await page.getByRole("textbox", { name: "File mail automatically from" }).fill("vendor.example");
  await page.getByRole("checkbox", { name: "Show in Priority inbox" }).click();
  await page.getByRole("button", { name: "Create category" }).click();
  const link = page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "Invoices" });
  await expect(link).toBeVisible();
  await link.click();
  await expect(page.getByRole("heading", { name: "Invoices" })).toBeVisible();
  await expect(page.getByTestId("thread-row").filter({ hasText: subject })).toBeVisible();
  await page.goto("/mail/priority");
  await expect(page.getByTestId("thread-row").filter({ hasText: subject })).toBeVisible();

  // Renaming in Settings carries the mail with it, and the sidebar follows from the event alone.
  await page.goto("/settings?section=categories");
  const category = page.getByTestId("category").filter({ hasText: "Invoices" });
  await category.getByRole("button", { name: "Open Invoices" }).click();
  await expect(category).toContainText("Made by you");
  await noViolations(page);
  let asked = 0;
  await page.route("**/api/queries/categories.list", (route) => {
    asked += 1;
    return route.continue();
  });
  await category.getByRole("textbox", { name: "Name" }).fill("Bills");
  await category.getByRole("textbox", { name: "Name" }).blur();
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  await expect(nav.getByRole("link", { name: "Bills" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Invoices" })).toHaveCount(0);
  expect(asked).toBe(0);
  await page.goto("/mail/category/Bills");
  await expect(page.getByTestId("thread-row").filter({ hasText: subject })).toBeVisible();
});

test("counts in the sidebar change the moment mail moves, without asking the server", async ({ page, request }) => {
  await request.post("/api/commands/categories.save", { data: { name: "Moved here" } });
  await page.goto("/mail/all");
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  await expect(nav.getByRole("link", { name: "Moved here" })).toBeVisible();
  let asked = 0;
  await page.route("**/api/queries/categories.list", (route) => {
    asked += 1;
    return route.continue();
  });
  const threads = (await (await request.post("/api/queries/threads.list", { data: { folder: "all" } })).json()) as { threads: { id: number; unread_count: number }[] };
  const thread = threads.threads[0];
  await request.post("/api/commands/thread.setRead", { data: { id: thread?.id, read: false } });
  await request.post("/api/commands/thread.setCategory", { data: { id: thread?.id, category: "Moved here" } });
  await expect(nav.getByRole("link", { name: "Moved here" })).toContainText("1");
  expect(asked).toBe(0);
});

test("the chat can be attached to the right, slides in, and keeps the conversation", async ({ page }) => {
  await page.goto("/today");
  await page.getByTestId("assistant-pill").click();
  const dock = page.getByTestId("assistant-dock");
  await expect(dock).toHaveAttribute("data-pinned", "false");
  const session = dock.getByRole("combobox", { name: "Switch conversation" });
  const title = await session.textContent();
  await dock.getByRole("button", { name: "Attach to the right" }).click();
  await expect(dock).toHaveAttribute("data-pinned", "true");
  await expect(session).toHaveText(title ?? "");
  // The page moves over rather than sitting underneath.
  await expect.poll(async () => {
    const main = await page.locator("main").boundingBox();
    const chat = await dock.boundingBox();
    return main && chat ? main.x + main.width <= chat.x + 1 : false;
  }).toBe(true);
  await noViolations(page);
  await page.reload();
  await expect(page.getByTestId("assistant-dock")).toHaveAttribute("data-pinned", "true");
  await page.getByRole("button", { name: "Float instead" }).click();
  await expect(page.getByTestId("assistant-dock")).toHaveAttribute("data-pinned", "false");
  await page.getByRole("button", { name: "Minimize" }).click();
});
