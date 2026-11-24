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

  // A click previews it over Today; Cmd or Ctrl and a click opens the email itself.
  await row.click();
  const preview = page.getByTestId("thread-preview");
  await expect(preview.getByRole("heading", { name: subject })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(preview).toHaveCount(0);
  await row.click({ modifiers: ["ControlOrMeta"] });
  await expect(page).toHaveURL(/\/mail\/all\/\d+$/);
  await expect(page.getByRole("heading", { name: subject })).toBeVisible();
  await page.getByRole("button", { name: "Details" }).click();
  await expect(page.getByTestId("triage-run").first()).toContainText("Someone needs a reply.");
  await noViolations(page);
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "Summarize" }).click();
  await expect(page.getByTestId("summary-text")).toContainText("They want the numbers by Friday.");
  await page.reload();
  await expect(page.getByTestId("summary-text")).toContainText("They want the numbers by Friday.");

  await page.getByTestId("draft-reply").click();
  // The agent already wrote one for this mail, so it opens that and the model isn't asked again.
  await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue(/Thanks, I'll look at this/);
  await page.reload();

  await page.getByRole("button", { name: "Ask agent" }).click();
  await expect(page.getByTestId("assistant-dock")).toBeVisible();
  await expect(page.getByTestId("context-chip")).toContainText(subject);
  await page.getByRole("button", { name: /^Remove (?!from )/ }).click();
  await expect(page.getByTestId("context-chip")).toHaveCount(0);
});

test("Today shows one matter per thing, as a brief, a week and a timeline", async ({ page }) => {
  const shots = process.env.E2E_SHOTS;
  // The page scrolls inside its frame, so a tall window shows all of it in one picture.
  if (shots) await page.setViewportSize({ width: 1440, height: 1700 });
  const ticket = `INC-${Math.floor(1000 + Math.random() * 8000)}`;
  const first = unique(`${ticket} VPN drops`);
  await deliver(page, { subject: first, body: "The VPN drops every hour." });
  await deliver(page, { subject: unique(`Update on ${ticket}`), sender: "Helpdesk <helpdesk@example.com>", body: "Still looking. Could you send logs?" });
  await page.goto("/today");
  const row = page.getByTestId("matter-row").filter({ hasText: first });
  await expect(row).toBeVisible({ timeout: 30_000 });
  await expect(row).toContainText("2 emails", { timeout: 30_000 });
  // New since the person last looked: counted at the top and marked on the matter itself.
  await expect(row.getByTestId("matter-changed")).toBeVisible();
  await expect(page.getByTestId("since-changed")).toBeVisible();
  // A Brief row has no Done button: it's in the row's menu.
  await expect(row.getByRole("button", { name: "Done" })).toHaveCount(0);
  await row.click({ button: "right" });
  await expect(page.getByRole("menuitem", { name: "Done" })).toBeVisible();
  await page.keyboard.press("Escape");
  await noViolations(page);
  if (shots) await page.screenshot({ path: `${shots}/brief.png`, fullPage: true });

  await page.getByRole("tab", { name: "Week" }).click();
  await expect(page).toHaveURL(/view=week/);
  await expect(page.getByTestId("week-lane").filter({ hasText: first })).toBeVisible();
  await noViolations(page);
  if (shots) await page.screenshot({ path: `${shots}/week.png`, fullPage: true });

  await page.getByTestId("week-lane").filter({ hasText: first }).getByRole("button").first().click();
  await expect(page).toHaveURL(/view=matters&matter=\d+/);
  const header = page.getByTestId("matter-header");
  await expect(header).toContainText(first);
  await expect(page.getByTestId("matter-timeline")).toContainText(`Both mention ${ticket.replace("-", "")}`);
  // The timeline reads top to bottom as it happened: it starts with the first email.
  const timeline = page.getByTestId("matter-timeline");
  await expect(timeline.getByText("Started").first()).toBeVisible();
  const order = await timeline.evaluate((list) => list.textContent ?? "");
  expect(order.indexOf("Started")).toBeGreaterThan(-1);
  expect(order.indexOf("Started")).toBeLessThan(order.indexOf("Linked"));

  // Two to-dos in one matter. Finishing one asks about the other, which had its own ask.
  const id = Number(new URL(page.url()).searchParams.get("matter"));
  const detail = await (await page.request.post("/api/queries/matters.get", { data: { id } })).json();
  const [one, two] = detail.threads.map((thread: { id: number }) => thread.id);
  const send = unique("Send the VPN logs");
  const check = unique("Check the new VPN client");
  await page.request.post("/api/commands/tasks.save", { data: { title: send, thread: two } });
  await page.request.post("/api/commands/tasks.save", { data: { title: check, thread: one } });
  await page.reload();
  await page.getByRole("checkbox", { name: send }).click();
  const sheet = page.getByRole("dialog", { name: /^Also in/ });
  await expect(sheet).toBeVisible();
  await expect(sheet.getByRole("checkbox", { name: check })).not.toBeChecked();
  await noViolations(page);
  if (shots) await page.screenshot({ path: `${shots}/rest-of-matter.png` });
  await sheet.getByRole("checkbox", { name: check }).click();
  await sheet.getByTestId("rest-close").click();
  await expect(page.getByText("Closed 1 more.")).toBeVisible();
  await expect(page.getByRole("checkbox", { name: check })).toHaveCount(0);

  await noViolations(page);
  if (shots) {
    await page.screenshot({ path: `${shots}/matter.png`, fullPage: true });
    await page.emulateMedia({ colorScheme: "dark" });
    await page.screenshot({ path: `${shots}/matter-dark.png`, fullPage: true });
    await page.getByRole("tab", { name: "Week" }).click();
    await page.screenshot({ path: `${shots}/week-dark.png`, fullPage: true });
    await page.getByRole("tab", { name: "Matters" }).click();
    await page.emulateMedia({ colorScheme: "light" });
  }

  // Done is the one button; everything else done to a matter is in its menu.
  await expect(header.getByRole("button", { name: "Hide from AI" })).toHaveCount(0);
  await header.click({ button: "right" });
  for (const item of ["Done", "Merge with…", "Go to the start", "Hide from AI"]) await expect(page.getByRole("menuitem", { name: item })).toBeVisible();
  await page.keyboard.press("Escape");
  // So is what's done to one email on its timeline.
  await expect(page.getByRole("button", { name: "Jump to start" })).toHaveCount(0);
  await page.getByTestId("timeline-entry").last().click({ button: "right" });
  for (const item of ["Open the email", "Go to the start", "Hide from AI"]) await expect(page.getByRole("menuitem", { name: item })).toBeVisible();
  await page.keyboard.press("Escape");
  // The same matter menu on the list beside it.
  await page.getByTestId("matter-list-item").filter({ hasText: first }).click({ button: "right" });
  await expect(page.getByRole("menuitem", { name: "Open" })).toBeVisible();
  await page.keyboard.press("Escape");

  await header.getByTestId("matter-done").click();
  // Two toasts can offer Undo now; the matter's own button is the one meant here.
  await header.getByRole("button", { name: "Undo" }).click();
  await expect(header.getByTestId("matter-done")).toBeVisible();
});

test("a proposed task is accepted, finished, and removed", async ({ page }) => {
  await page.goto("/planner/tasks");
  await page.getByRole("radio", { name: /^Suggested/ }).click();
  const proposed = page.getByTestId("task").filter({ hasText: "Reply to this mail" }).first();
  await expect(proposed).toBeVisible();
  await noViolations(page);
  // Accepting one takes it out of Suggested. Others from earlier tests are accepted too, so
  // the tests after this start with none waiting.
  const accept = page.getByRole("button", { name: "Accept" });
  const waiting = await accept.count();
  await proposed.getByRole("button", { name: "Accept" }).click();
  await expect(accept).toHaveCount(waiting - 1);
  while ((await accept.count()) > 0) {
    const left = await accept.count();
    await accept.first().click();
    await expect(accept).toHaveCount(left - 1);
  }
  await page.getByRole("radio", { name: /^To do/ }).click();

  const title = unique("Send the report");
  const bar = page.getByTestId("add-bar");
  await bar.getByRole("textbox", { name: "New task" }).fill(title);
  // One quiet date button opens one picker; the day picked shows on the button.
  await bar.getByRole("button", { name: "No date, change the due date" }).click();
  await page.getByRole("dialog", { name: "Due" }).getByRole("button", { name: /^Tomorrow/ }).click();
  await expect(bar.getByRole("button", { name: /^(?!No date).*, change the due date$/ })).toBeVisible();
  await bar.getByRole("button", { name: "Add", exact: true }).click();
  const mine = page.getByTestId("task").filter({ hasText: title });
  await expect(mine).toBeVisible();
  await noViolations(page);

  await mine.getByRole("checkbox").click();
  await expect(mine).toHaveCount(0);
  // Done sits closed at the bottom, struck through, and can be opened again from there.
  const done = page.getByTestId("tasks-done");
  await done.getByRole("button", { name: /^Done/ }).click();
  const finished = done.getByTestId("task-done").filter({ hasText: title });
  await expect(finished).toBeVisible();
  await noViolations(page);
  await finished.getByRole("button", { name: "Mark not done" }).click();
  await expect(mine).toBeVisible();
  await mine.getByRole("button", { name: `Open ${title}` }).click();
  await expect(mine.getByTestId("task-times")).toContainText("Added");
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
  const bar = page.getByTestId("add-bar");
  await bar.getByRole("textbox", { name: "Remind me to" }).fill(title);
  await bar.getByRole("button", { name: /, change when$/ }).click();
  const picker = page.getByRole("dialog", { name: "When" });
  await picker.getByLabel("Day").fill("2031-05-01");
  await picker.getByLabel("Time").fill("09:00");
  await page.keyboard.press("Escape");
  await bar.getByRole("button", { name: "Add", exact: true }).click();
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
  const drawer = page.getByRole("dialog");
  // A template fills the form, and nothing is saved until the person says so.
  await page.getByRole("button", { name: "New", exact: true }).click();
  await drawer.getByRole("button", { name: "Daily prep" }).click();
  await expect(drawer.getByRole("textbox", { name: "Name", exact: true })).toHaveValue("Daily prep");
  await drawer.getByRole("button", { name: "Create schedule" }).click();
  await expect(drawer).toHaveCount(0);
  await expect(page.getByTestId("schedule").filter({ hasText: "Daily prep" })).toBeVisible();

  const title = unique("Weekly note");
  await page.getByRole("button", { name: "New", exact: true }).click();
  await drawer.getByRole("textbox", { name: "Name", exact: true }).fill(title);
  await drawer.getByRole("textbox", { name: "What should the agent do?" }).fill("Say hello");
  await drawer.getByRole("combobox", { name: "How often" }).click();
  await page.getByRole("option", { name: "Every month" }).click();
  await drawer.getByRole("combobox", { name: "Day of the month" }).click();
  await page.getByRole("option", { name: "Last day" }).click();
  await drawer.getByRole("button", { name: "Create schedule" }).click();
  const row = page.getByTestId("schedule").filter({ hasText: title });
  await expect(row).toContainText("Monthly on the last day at");
  await noViolations(page);
  await row.getByRole("button").click();
  await drawer.getByRole("button", { name: "Run now" }).click();
  await expect(drawer.getByRole("button", { name: "Last run" })).toBeVisible({ timeout: 20_000 });
  await page.keyboard.press("Escape");

  // Daily prep's time and its nightly limit are the person's to set.
  const prep = page.getByTestId("schedule").filter({ hasText: "Daily prep" });
  await prep.getByRole("button").click();
  await noViolations(page);
  await drawer.getByLabel("Time", { exact: true }).fill("05:30");
  await drawer.getByRole("button", { name: "More options" }).click();
  await drawer.getByRole("spinbutton", { name: "Token limit for each run" }).fill("20000");
  await drawer.getByRole("button", { name: "Save" }).click();
  await expect(prep).toContainText("5:30");
  await prep.getByRole("button").click();
  await drawer.getByRole("button", { name: "More options" }).click();
  await expect(drawer.getByRole("spinbutton", { name: "Token limit for each run" })).toHaveValue("20000");
  await page.keyboard.press("Escape");

  await page.getByRole("switch", { name: "Time check for reminders and deadlines" }).click();
  await page.reload();
  await expect(page.getByRole("switch", { name: "Time check for reminders and deadlines" })).not.toBeChecked();
  await page.getByRole("switch", { name: "Time check for reminders and deadlines" }).click();
});

test("what the agent knows, and is told, can be seen and it asks before moving mail", async ({ page }) => {
  await page.goto("/agent/memory");
  await expect(page.getByRole("tab", { name: "What it knows" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: "Learned from your mail" })).toBeVisible();
  const layers = page.getByRole("list", { name: "Everything it's told, in order" });
  await expect(layers.getByTestId("knowledge-layer").first()).toContainText("System prompt");
  await layers.getByRole("button", { name: "Open Mail agent's instructions" }).click();
  await expect(layers.getByText("You look after the person's email")).toBeVisible();
  await noViolations(page);
  await page.getByRole("switch", { name: "Your brief" }).click();
  await expect(page.getByRole("switch", { name: "Your brief" })).not.toBeChecked();
  await page.getByRole("switch", { name: "Your brief" }).click();
  await expect(page.getByRole("switch", { name: "Your brief" })).toBeChecked();
  await page.getByRole("tab", { name: "What it sees" }).click();
  await expect(page.getByText("calls no model")).toBeVisible();
  await noViolations(page);
});

test("agent screens open cleanly and what Posty learned is kept without asking", async ({ page }) => {
  for (const path of ["/cockpit", "/agent/activity", "/agent/channel"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await noViolations(page);
  }
  await page.goto("/agent/memory");
  await page.getByRole("tab", { name: "Memory" }).click();
  // Learned from mail, it's kept at once with its source, with nothing waiting to be approved.
  await expect(page.getByTestId("memory-proposal")).toHaveCount(0);
  const kept = (await (await page.request.post("/api/queries/memory.list", { data: { query: "" } })).json()) as { files: { content: string }[] };
  expect(kept.files.some((file) => file.content.includes("Remember this person."))).toBe(true);
  await noViolations(page);

  const note = unique("Prefers short mails");
  await page.getByRole("textbox", { name: "Add something to remember" }).fill(note);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByTestId("memory-file").filter({ has: page.locator(`textarea:text-is("${note}")`) })).toBeVisible();

  await page.getByRole("tab", { name: "Prompts" }).click();
  await page.getByRole("button", { name: "Open About me" }).click();
  await expect(page.getByRole("textbox", { name: "About me" })).toBeVisible();
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
  const saved = page.waitForResponse("**/api/commands/sendChecks.save");
  await page.getByRole("spinbutton", { name: "Seconds to undo a send" }).fill("3");
  await saved;
  await page.reload();
  await expect(page.getByRole("spinbutton", { name: "Seconds to undo a send" })).toHaveValue("3");

  await page.goto("/mail/all");
  await page.getByRole("button", { name: "New message" }).click();
  await page.getByRole("combobox", { name: "To", exact: true }).fill("someone@example.com");
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

test("the chat opens from Today, starts a session and sends it", async ({ page }) => {
  await page.goto("/today");
  await page.getByTestId("assistant-pill").click();
  const dock = page.getByTestId("assistant-dock");
  await dock.getByRole("button", { name: "New chat" }).click();
  await dock.getByRole("textbox", { name: "Message the agent" }).fill("Hello from Today");
  await dock.getByRole("button", { name: "Send" }).click();
  await expect(dock.getByTestId("agent-message")).toContainText("Hello from gpt-best");
  await page.reload();
  await expect(page.getByTestId("assistant-dock").getByTestId("agent-message")).toContainText("Hello from gpt-best");
  await expect(page.getByTestId("assistant-dock").getByTestId("user-message").last()).toContainText("Hello from Today");
});

test("only the app's own pages get through to the backend", async ({ page, request }) => {
  await page.goto("/today");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  const direct = await request.post("http://127.0.0.1:4100/api/queries/settings.get", { data: {} });
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

test("the page itself never scrolls, so the sidebar stays put", async ({ page }) => {
  await page.goto("/agent/schedules");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForTimeout(500);
  const sizes = await page.evaluate(() => [document.documentElement.scrollHeight, window.innerHeight]);
  expect(sizes[0]).toBeLessThanOrEqual(sizes[1] as number);
});

test("switches animate from one place and keep their state", async ({ page }) => {
  await page.goto("/agent/memory");
  const toggle = page.getByRole("switch").first();
  await expect(toggle).toBeVisible();
  const before = await toggle.getAttribute("aria-checked");
  await toggle.click();
  await expect(toggle).toHaveClass(/is-init/);
  await expect(toggle).not.toHaveAttribute("aria-checked", before as string);
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", before as string);
});

test("the agent list says what each one runs on and when it runs next", async ({ page }) => {
  await page.goto("/agent/channel");
  await page.getByRole("tab", { name: "Schedules" }).click();
  const rows = page.getByTestId("agent-entry");
  await expect(rows.filter({ hasText: "Judges your mail" })).toBeVisible();
  await expect(rows.filter({ hasText: "Writes your morning brief" }).getByTestId("agent-next")).toBeVisible();
  await noViolations(page);
});

test("a search result opens with the results still beside it", async ({ page }) => {
  const word = unique("Quarterzz").replace(/\s/g, "");
  await deliver(page, { subject: `${word} first`, sender: "ann@example.com", body: "One" });
  await deliver(page, { subject: `${word} second`, sender: "ann@example.com", body: "Two" });
  await page.goto(`/search?q=${word}`);
  await expect(page.getByTestId("search-hit")).toHaveCount(2, { timeout: 20_000 });
  await page.getByTestId("search-hit").first().getByRole("link").first().click();
  await expect(page).toHaveURL(/\/search\/\d+/);
  await expect(page.getByTestId("thread-row")).toHaveCount(2);
  await noViolations(page);
  await page.getByRole("link", { name: "Back to results" }).click();
  await expect(page).toHaveURL(/\/search\?/);
  await expect(page.getByRole("searchbox", { name: "Search for" })).toHaveValue(word);
});

test("a long prompt opens large from its own box", async ({ page }) => {
  await page.goto("/agent/memory");
  await page.getByRole("tab", { name: "Prompts" }).click();
  await page.getByRole("button", { name: /open/i }).first().click();
  await page.getByTestId("view-expand").first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await noViolations(page);
});

test("About names the team, and no third party", async ({ page }) => {
  await page.goto("/settings?section=about");
  await expect(page.getByTestId("team-member")).toHaveText("Mahesh Yadav");
  await expect(page.getByRole("link", { name: /unslop/i })).toHaveCount(0);
});

const proposeTask = async (page: Page, title: string) => {
  // Made by hand it's already accepted, so it's turned back into what an agent would propose.
  expect((await page.request.post("/api/commands/tasks.save", { data: { title } })).ok()).toBe(true);
  const listed = (await (await page.request.post("/api/queries/tasks.list", { data: {} })).json()) as { tasks: { id: number; title: string }[] };
  const made = listed.tasks.find((task) => task.title === title);
  expect((await page.request.post("/api/commands/tasks.save", { data: { id: made?.id, title, proposed: true } })).ok()).toBe(true);
};

test("an action on Needs you blocks its row while it runs, and a failure can be tried again", async ({ page }) => {
  const title = unique("Slow task");
  await proposeTask(page, title);
  await page.goto("/today");
  const row = page.getByTestId("proposal").filter({ hasText: title });
  await expect(row).toBeVisible();
  let fail = true;
  await page.route("**/api/commands/tasks.remove", async (route) => {
    await new Promise((done) => setTimeout(done, 400));
    if (fail) await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ code: "x", message: "It broke" }) });
    else await route.continue();
  });
  await row.getByRole("button", { name: "Decline" }).click();
  await expect(row).toHaveAttribute("data-state", "running");
  await expect(row.getByRole("button", { name: "Accept" })).toBeDisabled();
  await expect(row.getByRole("alert")).toContainText("It broke");
  await expect(row).toHaveAttribute("data-state", "failed");
  fail = false;
  await row.getByRole("button", { name: "Try again" }).click();
  await expect(row).toHaveCount(0);
});

test("several things on Needs you can be done or declined together", async ({ page }) => {
  const [one, two, three] = [unique("Bulk one"), unique("Bulk two"), unique("Bulk three")];
  for (const title of [one, two, three]) await proposeTask(page, title);
  await page.goto("/today");
  // Selecting unfolds the list, however many suggestions earlier tests left.
  await page.getByTestId("bulk-select").click();
  await expect(page.getByTestId("proposal").filter({ hasText: three })).toBeVisible();
  await page.getByRole("checkbox", { name: `Select ${one}` }).click();
  await page.getByRole("checkbox", { name: `Select ${two}` }).click();
  await noViolations(page);
  await page.getByTestId("bulk-bar").getByRole("button", { name: "Do it (2)" }).click();
  await expect(page.getByTestId("proposal").filter({ hasText: one })).toHaveCount(0);
  await expect(page.getByTestId("proposal").filter({ hasText: two })).toHaveCount(0);
  await expect(page.getByTestId("bulk-bar")).toHaveCount(0);
  const row = page.getByTestId("proposal").filter({ hasText: three });
  await row.getByRole("button", { name: "Decline" }).click();
  await expect(row).toHaveCount(0);
  await page.goto("/planner/tasks");
  await expect(page.getByText(one)).toBeVisible();
  await expect(page.getByText(three)).toHaveCount(0);
});

test("the team shows calm cards, and the chosen agent's details beside them", async ({ page }) => {
  await page.goto("/agent/channel?tab=team");
  const cards = page.getByTestId("agent-card");
  await expect(cards.first()).toBeVisible();
  const organizer = cards.filter({ hasText: "@organizer" });
  await organizer.locator("[aria-pressed]").click();
  const detail = page.getByTestId("agent-detail");
  await expect(detail).toContainText("@organizer");
  await expect(detail.getByRole("button", { name: "Rename" })).toBeVisible();
  // Talk sits in the card's footer, inside the card, whatever the agent's name.
  const talk = organizer.getByRole("button", { name: /^Talk to / });
  const card = await organizer.boundingBox();
  const button = await talk.boundingBox();
  expect(card && button && button.x + button.width <= card.x + card.width).toBeTruthy();
  await noViolations(page);
});
