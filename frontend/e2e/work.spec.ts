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

const deliver = async (page: Page, mail: Record<string, unknown>) => {
  const response = await page.request.post(CONTROL, { data: mail });
  expect(response.ok()).toBe(true);
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
  const saved = await request.post("/api/commands/mail.accounts.save", {
    data: {
      name: "worker",
      password: "test-password",
      profile: {
        label: "Worker",
        imap: { host: "127.0.0.1", port: 8143, secure: false },
        smtp: { host: "127.0.0.1", port: 8025, secure: false },
        auth: { type: "password", user: USER },
        mailboxes: ["INBOX"],
      },
    },
  });
  expect(saved.ok(), await saved.text()).toBe(true);
  // Mail that arrives during the first sync counts as old, so it wouldn't be judged. The status
  // can still describe the account before this one, so only seeing mail arrive proves it's synced.
  const probe = unique("Probe");
  await expect
    .poll(async () => ((await (await request.post("/api/queries/mail.status", { data: {} })).json()) as { state: string }).state, { timeout: 20_000 })
    .toBe("live");
  await request.post(CONTROL, { data: { subject: probe, body: "Just checking." } });
  await expect
    .poll(async () => ((await (await request.post("/api/queries/threads.list", { data: { folder: "all" } })).json()) as { threads: { subject: string }[] }).threads.some((thread) => thread.subject === probe), { timeout: 20_000 })
    .toBe(true);
});

test.afterAll(async ({ request }) => {
  await request.post("/api/commands/mail.accounts.remove", { data: { name: "worker" } });
  await request.post("/api/commands/models.disconnect", { data: {} });
});

test("new mail is judged, and reaches Today, the thread and the channel", async ({ page }) => {
  await page.goto("/today");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await noViolations(page);
  const subject = unique("Urgent question");
  await deliver(page, { subject, body: "Urgent: please add a task, keep a draft, remember me, and answer my question." });

  const row = page.getByTestId("today-thread").filter({ hasText: subject });
  await expect(row).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("question-card").first()).toContainText("Is this urgent for you?", { timeout: 20_000 });
  await noViolations(page);

  const question = page.getByTestId("question-card").filter({ hasText: "Is this urgent for you?" }).first();
  await question.getByRole("textbox").fill("Yes it is");
  await question.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByTestId("question-card").filter({ hasText: "Is this urgent for you?" })).toHaveCount(0);

  await row.click();
  await expect(page.getByRole("heading", { name: subject })).toBeVisible();
  await page.getByRole("button", { name: "Details" }).click();
  await expect(page.getByTestId("triage-run").first()).toContainText("Someone needs a reply.");
  await noViolations(page);
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "Summarize" }).click();
  await expect(page.getByTestId("summary-text")).toContainText("They want the numbers by Friday.");
  await page.reload();
  await expect(page.getByTestId("summary-text")).toContainText("They want the numbers by Friday.");

  await page.getByRole("button", { name: "Ask agent" }).click();
  await expect(page.getByTestId("assistant-dock")).toBeVisible();
  await expect(page.getByTestId("context-chip")).toContainText(subject);
  await page.getByRole("button", { name: /^Remove / }).click();
  await expect(page.getByTestId("context-chip")).toHaveCount(0);
});

test("a proposed task is accepted, finished, and removed", async ({ page }) => {
  await page.goto("/planner/tasks");
  await page.getByRole("radio", { name: /^Suggested/ }).click();
  const proposed = page.getByTestId("task").filter({ hasText: "Reply to this mail" }).first();
  await expect(proposed).toBeVisible();
  await noViolations(page);
  await proposed.getByRole("button", { name: "Accept" }).click();
  await expect(page.getByRole("button", { name: "Accept" })).toHaveCount(0);
  await page.getByRole("radio", { name: /^To do/ }).click();

  const title = unique("Send the report");
  await page.getByRole("textbox", { name: "New task" }).fill(title);
  await page.getByRole("button", { name: "Add task" }).click();
  const mine = page.getByTestId("task").filter({ hasText: title });
  await expect(mine).toBeVisible();

  await mine.getByRole("checkbox").click();
  await expect(mine).toHaveCount(0);
  await page.getByRole("radio", { name: /^Done/ }).click();
  await expect(mine).toBeVisible();
  await mine.getByRole("button", { name: `Open ${title}` }).click();
  await expect(mine.getByTestId("task-times")).toContainText("Added");
  await expect(mine.getByTestId("task-times")).toContainText("finished");
  await mine.getByRole("button", { name: `Remove ${title}` }).click();
  await expect(mine).toHaveCount(0);

  await page.getByRole("radio", { name: /^To do/ }).click();
  const accepted = page.getByTestId("task").filter({ hasText: "Reply to this mail" }).first();
  await accepted.getByRole("button", { name: "Open Reply to this mail" }).click();
  await accepted.getByRole("button", { name: "Do it for me" }).click();
  await expect(page.getByTestId("assistant-dock")).toBeVisible();
  await expect(page.getByTestId("user-message")).toContainText("Please do this task for me.");
});

test("a reminder is added and snoozed", async ({ page }) => {
  await page.goto("/planner/reminders");
  const title = unique("Call the vendor");
  await page.getByRole("textbox", { name: "Remind me to" }).fill(title);
  await page.getByRole("button", { name: "Tomorrow morning" }).click();
  await page.getByLabel("When").fill("2031-05-01T09:00");
  await page.getByRole("button", { name: "Add reminder" }).click();
  const row = page.getByTestId("reminder").filter({ hasText: title });
  await expect(row).toBeVisible();
  await noViolations(page);
  const before = await row.textContent();
  await row.getByRole("button", { name: "Snooze" }).click();
  await page.getByRole("menuitem", { name: "In an hour" }).click();
  await expect.poll(() => row.textContent()).not.toBe(before);
  await row.getByRole("button", { name: `Open ${title}` }).click();
  await expect(row.getByTestId("reminder-times")).toContainText("Added");
  await row.getByRole("button", { name: `Remove ${title}` }).click();
  await expect(row).toHaveCount(0);
});

test("a schedule is created and runs on demand", async ({ page }) => {
  await page.goto("/agent/schedules");
  await page.getByRole("button", { name: "Add daily prep at 6:00" }).click();
  await expect(page.getByTestId("schedule").filter({ hasText: "Daily prep" })).toBeVisible();

  const title = unique("Weekly note");
  await page.getByRole("textbox", { name: "Name" }).fill(title);
  await page.getByRole("textbox", { name: "What should the agent do?" }).fill("Say hello");
  await page.getByRole("button", { name: "Create schedule" }).click();
  const row = page.getByTestId("schedule").filter({ hasText: title });
  await expect(row).toBeVisible();
  await noViolations(page);
  await row.getByRole("button", { name: "Run now" }).click();
  await expect(row.getByRole("link", { name: "Last run" })).toBeVisible({ timeout: 20_000 });

  // Daily prep's time and its nightly limit are the person's to set.
  const prep = page.getByTestId("schedule").filter({ hasText: "Daily prep" });
  await prep.getByRole("button", { name: "Edit Daily prep" }).click();
  await noViolations(page);
  await prep.getByLabel("Time").fill("05:30");
  await prep.getByRole("spinbutton", { name: "Token limit for each run" }).fill("20000");
  await prep.getByRole("button", { name: "Save" }).click();
  await expect(prep).toContainText("Limit: 20,000 tokens");
  await expect(prep).toContainText("5:30");

  await page.getByRole("switch", { name: "Time check for reminders and deadlines" }).click();
  await page.reload();
  await expect(page.getByRole("switch", { name: "Time check for reminders and deadlines" })).not.toBeChecked();
  await page.getByRole("switch", { name: "Time check for reminders and deadlines" }).click();
});

test("agent screens open cleanly and memory proposals are decided", async ({ page }) => {
  for (const path of ["/agent/background", "/agent/activity", "/agent/channel"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await noViolations(page);
  }
  await page.goto("/agent/memory");
  await page.getByRole("tab", { name: "Memory" }).click();
  const proposal = page.getByTestId("memory-proposal").filter({ hasText: "Remember this person." }).first();
  await expect(proposal).toBeVisible();
  await noViolations(page);
  await proposal.getByRole("button", { name: "Keep" }).click();
  await expect(page.getByTestId("memory-file").filter({ hasText: /note|memory|proposal/i }).first()).toBeVisible();

  const note = unique("Prefers short mails");
  await page.getByRole("textbox", { name: "Add something to remember" }).fill(note);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByTestId("memory-file").filter({ has: page.locator(`textarea:text-is("${note}")`) })).toBeVisible();

  await page.getByRole("tab", { name: "Prompts" }).click();
  await expect(page.getByRole("textbox").first()).toBeVisible();
  await noViolations(page);
});

test("the new settings sections save, and the guard masks a sample", async ({ page }) => {
  await page.goto("/settings?section=permissions");
  await page.getByRole("combobox", { name: "Run commands" }).click();
  await page.getByRole("option", { name: "Off" }).click();
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Run commands" })).toHaveText(/Off/);
  await page.getByRole("combobox", { name: "Run commands" }).click();
  await page.getByRole("option", { name: "Ask first" }).click();
  // Sending always asks, so allowing it isn't offered.
  await page.getByRole("combobox", { name: "Send mail" }).click();
  await expect(page.getByRole("option", { name: "Allow" })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await noViolations(page);

  await page.goto("/settings?section=guard");
  await page.getByRole("button", { name: "Test rules" }).click();
  await expect(page.getByTestId("guard-result")).toContainText("<EMAIL_1>");
  await expect(page.getByTestId("guard-result")).not.toContainText("kim.j@samsung.com");
  await noViolations(page);

  await page.goto("/settings?section=usage");
  await expect(page.getByTestId("usage-total")).toContainText("tokens today");
  await noViolations(page);

  await page.goto("/settings?section=notifications");
  await page.getByRole("switch", { name: "Quiet hours" }).click();
  await page.reload();
  await expect(page.getByRole("switch", { name: "Quiet hours" })).toBeChecked();
  await noViolations(page);

  await page.goto("/settings?section=models");
  await page.getByRole("radio", { name: "Internal server" }).click();
  await expect(page.getByRole("textbox", { name: "Server address" })).toBeVisible();
  await noViolations(page);
  await page.getByRole("radio", { name: "ChatGPT" }).click();
  await expect(page.getByRole("textbox", { name: "Server address" })).toHaveCount(0);
});

test("a send warns about a missing attachment, and can be undone", async ({ page }) => {
  await page.goto("/settings?section=send-checks");
  await page.getByRole("spinbutton", { name: "Seconds to undo a send" }).fill("3");
  await page.reload();
  await expect(page.getByRole("spinbutton", { name: "Seconds to undo a send" })).toHaveValue("3");

  await page.goto("/mail/all");
  await page.getByRole("button", { name: "New message" }).click();
  await page.getByRole("textbox", { name: "To", exact: true }).fill("someone@example.com");
  await page.getByRole("textbox", { name: "Subject" }).fill(unique("Report"));
  await page.getByRole("textbox", { name: "Message" }).fill("See the attached report.");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByTestId("send-checks")).toContainText(/attach/i);
  await noViolations(page);

  await page.getByRole("button", { name: "Send anyway" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Sending in" })).toBeVisible();
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Sending in" })).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue("See the attached report.");
});

test("typing on Today starts a session and sends it", async ({ page }) => {
  await page.goto("/today");
  await page.getByRole("textbox", { name: "Ask the agent to do something" }).fill("Hello from Today");
  await page.getByRole("button", { name: "Send" }).click();
  const dock = page.getByTestId("assistant-dock");
  await expect(dock.getByTestId("agent-message")).toContainText("Hello from gpt-best");
  await page.reload();
  await expect(page.getByTestId("assistant-dock").getByTestId("agent-message")).toContainText("Hello from gpt-best");
  await expect(page.getByTestId("user-message")).toContainText("Hello from Today");
  await expect(page.getByTestId("agent-message")).toHaveCount(1);
});

test("only the app's own pages get through to the backend", async ({ page, request }) => {
  await page.goto("/today");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  const direct = await request.post("http://127.0.0.1:8765/api/queries/settings.get", { data: {} });
  expect(direct.status()).toBe(401);
  const otherSite = await request.post("/api/queries/settings.get", { data: {}, headers: { "sec-fetch-site": "cross-site" } });
  expect(otherSite.status()).toBe(403);
  const otherOrigin = await request.post("/api/commands/settings.update", { data: { theme: "nexus-dark" }, headers: { origin: "https://evil.example" } });
  expect(otherOrigin.status()).toBe(403);
});

test("a large upload arrives whole through the token proxy", async ({ page }) => {
  await page.goto("/documents/all");
  const size = 12 * 1024 * 1024;
  const response = await page.request.post("/api/documents/upload?name=large-upload.txt", { data: Buffer.alloc(size, "a"), headers: { "content-type": "application/octet-stream" } });
  expect(response.ok(), await response.text()).toBe(true);
  expect(((await response.json()) as { size: number }).size).toBe(size);
});

test("a new recovery key can be made in Settings, and is only shown until saved", async ({ page }) => {
  // Setup shows the first one, and this file's setup skips that step.
  await page.request.post("/api/home/recovery-key/confirm", { data: {} });
  await page.goto("/settings?section=home");
  await page.getByRole("button", { name: "Create a new recovery key" }).click();
  await noViolations(page);
  await page.getByRole("button", { name: "Replace my key" }).click();
  await expect(page.getByTestId("recovery-key")).toHaveText(/^([0-9A-Z]{4}-){7}[0-9A-Z]{4}$/);
  await noViolations(page);
  await expect(page.getByRole("button", { name: "Done" })).toBeDisabled();
  await page.getByRole("checkbox", { name: "I've saved my recovery key somewhere safe" }).click();
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByTestId("recovery-key")).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("button", { name: "Create a new recovery key" })).toBeVisible();
  await expect(page.getByTestId("recovery-key")).toHaveCount(0);
});
