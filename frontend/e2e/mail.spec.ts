import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const CONTROL = "http://127.0.0.1:8767/";
const USER = "tester@example.com";
const unique = (word: string) => `${word} ${Date.now()}${Math.floor(Math.random() * 1000)}`;

const deliver = async (page: Page, mail: Record<string, unknown>) => {
  const response = await page.request.post(CONTROL, { data: mail });
  expect(response.ok()).toBe(true);
};

const noViolations = async (page: Page) => {
  // Cards fade in, and contrast can't be judged halfway through.
  await page.waitForTimeout(300);
  // Mail is the sender's content, and its sandbox rightly stops axe from running inside it.
  const { violations } = await new AxeBuilder({ page }).exclude("iframe").analyze();
  expect(violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
};

test.beforeAll(async ({ request }) => {
  await request.post("/api/home/choose", { data: { path: `${process.env.E2E_HOME}/NexusAI` } });
  await request.post("/api/commands/onboarding.finish", { data: {} });
});

test.describe.configure({ mode: "serial" });

test("a mail account can be tested, and a wrong password says so", async ({ page }) => {
  await page.goto("/mail/all");
  await expect(page.getByText("No mail account connected")).toBeVisible();
  await page.getByRole("link", { name: "Connect your mail" }).click();
  await expect(page).toHaveURL(/\/connectors$/);

  // A known provider fills in its server, and its details are there to check.
  await page.getByRole("textbox", { name: "Username" }).fill("someone@gmail.com");
  await expect(page.getByRole("textbox", { name: "Server name" })).toHaveValue("imap.gmail.com");
  await expect(page.getByText("Use a Google App Password")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "IMAP port" })).toHaveCount(0);
  await page.getByRole("button", { name: "Server details" }).click();
  await expect(page.getByRole("textbox", { name: "Sending server" })).toHaveValue("smtp.gmail.com");
  await expect(page.getByRole("textbox", { name: "SMTP port" })).toHaveValue("465");

  await page.getByRole("textbox", { name: "Server name" }).fill("127.0.0.1");
  await page.getByRole("textbox", { name: "Username" }).fill(USER);
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("textbox", { name: "IMAP port" }).fill("8143");
  await page.getByRole("textbox", { name: "Sending server" }).fill("127.0.0.1");
  await page.getByRole("textbox", { name: "SMTP port" }).fill("8025");
  await page.getByRole("switch", { name: "Encrypted connection" }).click();
  await noViolations(page);

  // Connecting tries the login first, and nothing is saved if it's refused.
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByTestId("connection-results")).toContainText("refused that username or password");

  // Once it's in, it says how much is there and asks how much of that to download.
  for (const number of [1, 2, 3]) await deliver(page, { subject: `Waiting on the server ${number}` });
  await page.getByLabel("Password").fill("test-password");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByTestId("connection-results").getByText("Connected")).toHaveCount(2);
  const chooser = page.getByTestId("pull-chooser");
  await expect(chooser).toContainText("3 emails on the server");
  await expect(chooser).toContainText("Inbox 3");
  await expect(chooser.getByRole("spinbutton", { name: "How many to download" })).toHaveValue("3");
  await chooser.getByRole("spinbutton", { name: "How many to download" }).fill("2");
  await noViolations(page);

  await page.getByRole("button", { name: "Start download" }).click();
  await expect(page.getByTestId("mail-state")).toContainText("Up to date", { timeout: 20_000 });
  await expect(page.getByText(USER)).toBeVisible();
  await expect(page.getByLabel("Password")).toHaveCount(0);
  const sync = page.getByTestId("pipeline").filter({ hasText: "Mail sync" });
  await expect(sync).toContainText("Finished");
  await expect(page.getByRole("switch", { name: "Never delete anything on the server" })).toBeChecked();

  // Getting more fetches what the first choice left behind.
  await sync.getByRole("button", { name: "Get more" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("1 older emails");
  await noViolations(page);
  await dialog.getByRole("button", { name: "All 1" }).click();
  await expect(sync.getByRole("button", { name: "Get more" })).toHaveCount(0, { timeout: 20_000 });
});

test("mail sync shows on the Schedules page and the Cockpit, and can be paused from each", async ({ page }) => {
  await page.goto("/agent/schedules");
  const row = page.getByTestId("pipeline").filter({ hasText: "Mail sync" });
  await expect(row).toContainText("Every minute");
  await expect(row).toContainText("On the server");
  await expect(row).toContainText("Last checked");
  await noViolations(page);

  const subject = unique("Held while paused");
  await row.getByRole("button", { name: "Pause" }).click();
  await expect(row).toContainText("Paused.");
  await deliver(page, { subject });

  await page.goto("/cockpit");
  const again = page.getByTestId("pipeline").filter({ hasText: "Mail sync" });
  await expect(again).toContainText("Paused.");
  await expect(page.getByTestId("health-mail")).toContainText("Paused");
  await noViolations(page);

  await page.goto("/connectors");
  await expect(page.getByTestId("mail-state")).toContainText("Paused");
  await page.getByRole("button", { name: "Resume" }).click();
  await expect(page.getByTestId("mail-state")).toContainText("Up to date", { timeout: 20_000 });

  // What came in while it was stopped is reported once it's going again.
  await page.goto("/cockpit");
  await expect(page.getByTestId("cockpit-event").filter({ hasText: "Found 1 new, pulled 1" }).first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("pipeline").filter({ hasText: "Mail sync" })).toContainText("Found 1, pulled 1");
});

test("new mail appears by itself, opens safely, and reads as read", async ({ page }) => {
  await page.goto("/mail/all");
  const subject = unique("Contract review");
  await deliver(page, {
    subject,
    body: "Please review the contract.",
    html: '<p>Please review the contract.</p><script>window.parent.document.title="HACKED"</script><img src="https://tracker.example/pixel.png">',
  });
  const row = page.getByTestId("thread-row").filter({ hasText: subject });
  // No reload: the screen is told by an event.
  await expect(row).toBeVisible({ timeout: 15_000 });
  await noViolations(page);

  const tracker: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("tracker.example")) tracker.push(request.url());
  });
  await row.getByRole("link").click();
  await expect(page.getByRole("heading", { name: subject })).toBeVisible();
  const frame = page.frameLocator("iframe");
  await expect(frame.locator("p")).toHaveText("Please review the contract.");
  expect(await page.title()).not.toBe("HACKED");
  // A tracking pixel never loads, whatever the setting, and leaves nothing to ask about.
  expect(tracker).toEqual([]);
  await noViolations(page);

  await page.goto("/mail/all");
  await expect(page.getByTestId("thread-row").filter({ hasText: subject }).locator("span.bg-accent-default")).toHaveCount(0);
});

test("mail keeps its styling, its images load, and either can be turned off", async ({ page, request }) => {
  await page.goto("/mail/all");
  const subject = unique("Styled mail");
  const loaded: string[] = [];
  await page.route("https://cdn.example/**", async (route) => {
    loaded.push(route.request().url());
    await route.fulfill({ status: 200, contentType: "image/png", body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEBgIApD5fRAAAAABJRU5ErkJggg==", "base64") });
  });
  await deliver(page, { subject, body: "Sale", html: '<html><head><title>Hidden</title><style>.big{font-size:40px}</style></head><body bgcolor="#eeeeee"><p class="big">Big text</p><img src="https://cdn.example/banner.png" width="300" height="100" alt="Banner"></body></html>' });
  const row = page.getByTestId("thread-row").filter({ hasText: subject });
  await expect(row).toBeVisible({ timeout: 15_000 });
  await row.getByRole("link").click();
  const frame = page.frameLocator("iframe");
  await expect(frame.locator("p.big")).toHaveCSS("font-size", "40px");
  await expect(frame.getByText("Hidden")).toHaveCount(0);
  await expect.poll(() => loaded.length).toBeGreaterThan(0);

  // Blocking is a setting, and a blocked image is a quiet tile with no broken icon.
  await request.post("/api/commands/settings.update", { data: { remote_images: "block" } });
  await page.reload();
  await expect(page.getByText("Images are off for this sender")).toBeVisible();
  const image = page.frameLocator("iframe").locator("img");
  await expect(image).toHaveAttribute("src", /^data:image\/gif/);
  await expect(image).toHaveAttribute("data-blocked-src", "https://cdn.example/banner.png");
  await noViolations(page);
  await page.getByRole("button", { name: "Show images" }).click();
  await expect(page.frameLocator("iframe").locator("img")).toHaveAttribute("src", "https://cdn.example/banner.png");
  await request.post("/api/commands/settings.update", { data: { remote_images: "load" } });
});

test("the sidebar runs from mail to planner, and every folder shows what's unread", async ({ page }) => {
  await page.goto("/mail/all");
  const nav = page.getByRole("navigation", { name: "Main navigation" });
  await expect(nav.getByRole("link", { name: "Today" })).toBeVisible();
  const labels = await nav.getByRole("link").allInnerTexts();
  const first = (name: string) => labels.findIndex((label) => label.startsWith(name));
  expect(first("Today")).toBe(0);
  expect(first("All mail")).toBeLessThan(first("Archive"));
  expect(first("Archive")).toBeLessThan(first("Trash"));
  expect(first("Trash")).toBeLessThan(first("Documents"));
  expect(first("Documents")).toBeLessThan(first("Sessions"));
  expect(first("Tasks")).toBeLessThan(first("Schedules"));
  await expect(nav.getByTestId("account-menu-trigger")).toBeVisible();
  await expect(nav.getByRole("heading", { name: "Mail" })).toHaveCount(0);
  await noViolations(page);
});

test("Settings opens frosted over the page, and a direct link gets the full page", async ({ page }) => {
  await page.goto("/mail/all");
  await page.getByTestId("account-menu-trigger").click();
  await page.getByRole("menuitem", { name: "Settings", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog).toBeVisible();
  await expect(page.getByTestId("thread-row").first()).toBeAttached();
  // The build once kept only the -webkit- version, which Chrome ignores, so this guards the real thing.
  const blur = await dialog.evaluate((node) => getComputedStyle(node.parentElement as Element).backdropFilter);
  expect(blur).toContain("blur");
  await expect(page).toHaveURL(/\/settings/);
  await noViolations(page);
  await dialog.getByRole("link", { name: "Preferences" }).click();
  await expect(dialog.getByText("Images in mail")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(page).toHaveURL(/\/mail\/all$/);

  await page.goto("/settings?section=preferences");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
});

test("sounds can be muted altogether or kind by kind", async ({ page }) => {
  await page.goto("/settings?section=notifications");
  const all = page.getByRole("switch", { name: "Play sounds" });
  await expect(all).toBeChecked();
  const reminders = page.getByRole("switch", { name: "Reminders" });
  await reminders.click();
  await expect(reminders).not.toBeChecked();
  await noViolations(page);
  await page.reload();
  await expect(page.getByRole("switch", { name: "Reminders" })).not.toBeChecked();
  await page.getByRole("switch", { name: "Reminders" }).click();
  await page.getByRole("button", { name: /^1?\s*Notifications|Notifications/ }).first().click();
  await page.getByRole("button", { name: "Mute sounds" }).click();
  await expect(page.getByRole("button", { name: "Turn sounds on" })).toBeVisible();
  await page.getByRole("button", { name: "Turn sounds on" }).click();
  await page.keyboard.press("Escape");
});

test("right-clicking a conversation offers what can be done to it", async ({ page }) => {
  await page.goto("/mail/all");
  const subject = unique("Right click me");
  await deliver(page, { subject });
  const row = page.getByTestId("thread-row").filter({ hasText: subject });
  await expect(row).toBeVisible({ timeout: 15_000 });
  await row.getByRole("link").click({ button: "right" });
  const menu = page.getByRole("menu");
  await expect(menu.getByRole("menuitem", { name: "Open" })).toBeVisible();
  // A menu floats outside the page's landmarks by nature, so it's checked on its own.
  const { violations } = await new AxeBuilder({ page }).include('[role="menu"]').analyze();
  expect(violations.map((v) => v.id)).toEqual([]);
  await menu.getByRole("menuitem", { name: "Mark read" }).click();
  await expect(menu).toHaveCount(0);
  await expect(row.locator("span.bg-accent-default")).toHaveCount(0);
  await row.getByRole("link").click({ button: "right" });
  await expect(page.getByRole("menuitem", { name: "Mark unread" })).toBeVisible();
  await page.keyboard.press("Escape");
});

test("the chat tucks to the edge while reading, comes out on hover, and returns afterwards", async ({ page }) => {
  await page.goto("/mail/all");
  const subject = unique("Needs the room");
  await deliver(page, { subject });
  const row = page.getByTestId("thread-row").filter({ hasText: subject });
  await expect(row).toBeVisible({ timeout: 15_000 });
  await page.getByTestId("assistant-pill").click();
  const dock = page.getByTestId("assistant-dock");
  await expect(dock).toBeVisible();

  await row.getByRole("link").click();
  await expect(page.getByRole("heading", { name: subject })).toBeVisible();
  await expect(dock).toHaveCount(0);
  const aura = page.getByTestId("assistant-aura");
  await expect(aura).toBeVisible();
  await noViolations(page);

  await aura.hover();
  await expect(dock).toBeVisible();
  await page.mouse.move(10, 400);
  await expect(dock).toHaveCount(0);

  // Leaving brings it back as it was, because tucking away never changed that.
  await page.goBack();
  await expect(page).toHaveURL(/\/mail\/all$/);
  await expect(dock).toBeVisible();

  // Pinned, it stays, because the person said so.
  await dock.getByRole("button", { name: "Attach to the right" }).click();
  await row.getByRole("link").click();
  await expect(page.getByRole("heading", { name: subject })).toBeVisible();
  await expect(dock).toBeVisible();
  await expect(aura).toHaveCount(0);
  await dock.getByRole("button", { name: "Float instead" }).click();
});

test("replying goes out with the right people and joins the conversation", async ({ page }) => {
  await page.goto("/mail/all");
  const subject = unique("Budget question");
  await deliver(page, { subject, to: `${USER}, sam@example.com`, cc: "lee@example.com", body: "Can you confirm the numbers?" });
  await page.getByTestId("thread-row").filter({ hasText: subject }).getByRole("link").click();

  await page.getByRole("button", { name: "Reply", exact: true }).click();
  await expect(page.getByText("This reply leaves out")).toContainText("sam@example.com");
  await expect(page.getByRole("textbox", { name: "To", exact: true })).toHaveValue("priya@example.com");
  await page.getByRole("button", { name: "Discard" }).click();

  await page.getByRole("button", { name: "Reply all" }).click();
  await expect(page.getByRole("textbox", { name: "Cc", exact: true })).toHaveValue("sam@example.com, lee@example.com");
  await page.getByRole("textbox", { name: "Message" }).fill("Numbers confirmed.");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  // There's a short window to undo before it goes.
  await expect(page.getByText("Message sent").first()).toBeVisible({ timeout: 15_000 });

  const sent = (await (await page.request.get(CONTROL)).json()) as { to: string[]; raw: string }[];
  const mine = sent.find((item) => item.raw.includes("Numbers confirmed."));
  expect(mine?.to.sort()).toEqual(["lee@example.com", "priya@example.com", "sam@example.com"]);
  expect(mine?.raw).toContain("In-Reply-To:");
  await expect(page.getByTestId("message")).toHaveCount(2, { timeout: 15_000 });
});

test("a bad address blocks sending, and a saved draft can be reopened", async ({ page }) => {
  await page.goto("/mail/all");
  await page.getByRole("button", { name: "New message" }).click();
  await page.getByRole("textbox", { name: "To", exact: true }).fill("not-an-address");
  await expect(page.getByText("isn't a valid address")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send", exact: true })).toBeDisabled();

  const subject = unique("Draft for later");
  await page.getByRole("textbox", { name: "To", exact: true }).fill("someone@example.com");
  await page.getByRole("textbox", { name: "Subject" }).fill(subject);
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByText("Draft saved").first()).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();

  await page.goto("/mail/drafts");
  await page.getByTestId("draft-row").filter({ hasText: subject }).click();
  await expect(page.getByRole("textbox", { name: "Subject" })).toHaveValue(subject);
  await page.getByRole("button", { name: "Discard" }).click();
  await expect(page.getByTestId("draft-row").filter({ hasText: subject })).toHaveCount(0);
});

test("search finds mail from the top bar and filters narrow it", async ({ page }) => {
  await page.goto("/mail/all");
  const word = `zebra${Date.now()}`;
  await deliver(page, { subject: `About ${word}`, body: `The ${word} report.` });
  await expect(page.getByTestId("thread-row").filter({ hasText: word })).toBeVisible({ timeout: 15_000 });

  // Instant results over the page, from the keyboard.
  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: "Search" });
  await page.getByRole("searchbox").fill(word);
  await expect(palette.getByTestId("palette-result").filter({ hasText: word })).toBeVisible();
  await noViolations(page);
  await page.getByRole("searchbox").press("Enter");
  await expect(page).toHaveURL(/\/search\?q=/);
  await expect(page.getByTestId("search-hit")).toHaveCount(1);
  await expect(page.getByTestId("search-hit").locator("mark").first()).toContainText(word);
  await noViolations(page);

  // Filters are chips, and from: can be typed straight in.
  await page.getByRole("button", { name: "From", exact: true }).click();
  await page.getByRole("textbox", { name: "From" }).fill("nobody-matches");
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page.getByText("Nothing found")).toBeVisible();
  await page.getByRole("button", { name: "Clear From" }).click();
  await expect(page.getByTestId("search-hit")).toHaveCount(1);
  await page.getByRole("searchbox").fill(`${word} from:nobody-matches`);
  await expect(page.getByText("Nothing found")).toBeVisible();
  await page.getByRole("searchbox").fill(word);

  // The same box looks through documents, and there's a filter inside any folder.
  await page.getByRole("radio", { name: "Documents" }).click();
  await expect(page).toHaveURL(/in=documents/);
  await expect(page.getByRole("button", { name: "Type", exact: true })).toBeVisible();
  await noViolations(page);
  await page.goto("/mail/all");
  await page.getByRole("searchbox", { name: "Filter this folder" }).fill(word);
  await expect(page.getByTestId("thread-row")).toHaveCount(1);
});

test("a rule files new mail, and the reason is shown", async ({ page }) => {
  await page.goto("/settings?section=rules");
  await page.getByRole("button", { name: "Add rule" }).click();
  await page.getByRole("textbox", { name: "Rule name" }).fill("Invoices");
  await page.getByRole("textbox", { name: "Contains" }).fill("invoice");
  await page.getByRole("textbox", { name: "Category" }).fill("Finance");
  await noViolations(page);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Rules saved").first()).toBeVisible();

  await page.goto("/mail/all");
  const subject = unique("Invoice");
  await deliver(page, { subject });
  const row = page.getByTestId("thread-row").filter({ hasText: subject });
  await expect(row).toContainText("Finance", { timeout: 15_000 });
  await row.getByRole("link").click();
  await expect(page.getByText("Matched the rule “Invoices”").first()).toBeVisible();
});

test("status and flag are kept, and archive removes it from the inbox", async ({ page }) => {
  await page.goto("/mail/all");
  const subject = unique("Archive this");
  await deliver(page, { subject });
  await page.getByTestId("thread-row").filter({ hasText: subject }).getByRole("link").click();

  await page.getByRole("button", { name: "Flag", exact: true }).click();
  await expect(page.getByRole("button", { name: "Remove flag" })).toBeVisible();
  await page.getByRole("combobox", { name: "Status" }).click();
  await page.getByRole("option", { name: "Waiting on others" }).click();
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Status" })).toHaveText("Waiting on others");

  await page.getByRole("button", { name: "Archive" }).click();
  await expect(page).toHaveURL(/\/mail\/all$/);
  await page.goto("/mail/archive");
  await expect(page.getByTestId("thread-row").filter({ hasText: subject })).toBeVisible();
});

test("the inbox stays fast and scrollable with many threads", async ({ page, request }) => {
  await page.goto("/mail/all");
  await page.setViewportSize({ width: 1366, height: 768 });
  const rendered = await page.getByTestId("thread-row").count();
  expect(rendered).toBeLessThan(60);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBe(0);
  expect((await request.post("/api/queries/mail.status", { data: {} })).ok()).toBe(true);
});

test("a document uploads, opens with its text, and can be filed, tagged and removed", async ({ page }) => {
  await page.goto("/documents/all");
  const name = `${unique("notes").replace(" ", "-")}.txt`;
  await page.getByTestId("file-input").setInputFiles({ name, mimeType: "text/plain", buffer: Buffer.from("The walrus budget is approved.") });
  const row = page.getByTestId("document-row").filter({ hasText: name });
  await expect(row).toBeVisible();
  await noViolations(page);

  // The text is read in the background, and the row catches up by itself.
  await expect(row.getByTestId("document-status")).toHaveCount(0);
  await page.getByRole("textbox", { name: "Search documents" }).fill("walrus");
  await expect(row).toBeVisible();
  await page.getByRole("textbox", { name: "Search documents" }).fill("giraffe-nothing");
  await expect(row).toHaveCount(0);
  await page.getByRole("textbox", { name: "Search documents" }).fill("");

  await page.getByRole("textbox", { name: "New folder" }).fill("Legal");
  await page.getByRole("textbox", { name: "New folder" }).press("Enter");
  await expect(page.getByRole("navigation", { name: "Folders" }).getByRole("button", { name: "Legal", exact: true })).toBeVisible();

  // One click shows the file itself, with its details one step further.
  await row.click();
  const preview = page.getByTestId("document-preview");
  await expect(preview).toContainText("The walrus budget is approved.");
  await noViolations(page);
  await preview.getByRole("button", { name: "Info" }).click();
  await expect(page.getByTestId("document-text")).toHaveText("The walrus budget is approved.");
  await page.getByRole("textbox", { name: "Add a tag" }).fill("urgent");
  await page.getByRole("textbox", { name: "Add a tag" }).press("Enter");
  await expect(page.getByRole("button", { name: "Remove tag urgent" })).toBeVisible();
  await page.getByRole("combobox", { name: "Folder" }).click();
  await page.getByRole("option", { name: "Legal" }).click();
  // Until it has finished closing, Escape would go to the list rather than the drawer.
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(row).toContainText("Legal");
  await expect(row).toContainText("urgent");

  await row.click();
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  await expect(row).toHaveCount(0);
});

test("PST imports show progress and can be paused and resumed", async ({ page }) => {
  await page.goto("/connectors");
  await page.getByRole("textbox", { name: "PST file" }).fill("/no/such/file.pst");
  await page.getByRole("button", { name: "Import" }).click();
  await expect(page.getByText("That file doesn't exist")).toBeVisible();
  await noViolations(page);

  const job = { id: 1, name: "old.pst", path: "/x/old.pst", total: 100, position: 40, imported: 38, duplicates: 2, failed: 0, error: null };
  let status = "running";
  await page.route("**/api/queries/pst.imports", (route) => route.fulfill({ json: { imports: [{ ...job, status }] } }));
  await page.route("**/api/commands/pst.pause", (route) => {
    status = "paused";
    return route.fulfill({ json: { imports: [{ ...job, status }] } });
  });
  await page.route("**/api/commands/pst.resume", (route) => {
    status = "running";
    return route.fulfill({ json: { imports: [{ ...job, status }] } });
  });
  await page.reload();
  const card = page.getByTestId("pst-import");
  await expect(card).toContainText("40 of 100 read, 38 added, 2 already here");
  await card.getByRole("button", { name: "Pause" }).click();
  await expect(card).toContainText("Paused");
  await card.getByRole("button", { name: "Resume" }).click();
  await expect(card).toContainText("Importing");
});

test("a PST file can be sent up, and picks up again after a dropped connection", async ({ page }) => {
  await page.goto("/connectors");
  let dropped = 0;
  await page.route("**/api/pst/upload/**", (route) => {
    // The second piece fails twice, as if the connection dropped.
    if (route.request().url().includes(`offset=${8 * 1024 * 1024}`) && dropped < 2) {
      dropped += 1;
      return route.abort();
    }
    return route.continue();
  });
  const name = `sent-${Date.now()}.pst`;
  await page.getByTestId("pst-input").setInputFiles({ name, mimeType: "application/octet-stream", buffer: Buffer.alloc(20 * 1024 * 1024, 1) });
  await expect(page.getByTestId("pst-import").filter({ hasText: name })).toBeVisible({ timeout: 30_000 });
  expect(dropped).toBe(2);
  await expect(page.getByTestId("pst-upload")).toHaveCount(0);
  await noViolations(page);
});

test("the Connectors page lists Email and takes an MCP server by its address", async ({ page }) => {
  await page.goto("/connectors");
  await expect(page.getByRole("heading", { level: 1, name: "Connectors" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Email" })).toBeVisible();
  await page.getByRole("button", { name: "Add a server" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox", { name: "Name" }).fill("Nothing there");
  await dialog.getByRole("textbox", { name: "Web address" }).fill("http://127.0.0.1:9/mcp");
  await expect(dialog.getByText("This address isn't encrypted")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Add", exact: true })).toBeDisabled();
  await dialog.getByRole("button", { name: "Test" }).click();
  await expect(dialog.getByText("Couldn't reach that server")).toBeVisible();
  await noViolations(page);
});

test("panels show live results, and can be added, resized, reordered and reset", async ({ page }) => {
  await page.goto("/panels");
  await expect(page.getByTestId("panel")).toHaveCount(4);
  await noViolations(page);

  const person = `person${Date.now()}@example.com`;
  await page.getByRole("button", { name: "Add panel" }).click();
  await page.getByRole("textbox", { name: "Name" }).fill("From this person");
  await page.getByRole("textbox", { name: "From" }).fill(person);
  await page.getByRole("button", { name: "Create panel" }).click();
  const panel = page.getByRole("region", { name: "From this person" });
  await expect(panel).toContainText("Nothing here right now");

  await deliver(page, { subject: "Panel mail", sender: person });
  await expect(panel).toContainText("Panel mail", { timeout: 15_000 });

  await panel.getByRole("combobox", { name: "Size" }).click();
  await page.getByRole("option", { name: "Large" }).click();
  await expect(panel.getByRole("combobox", { name: "Size" })).toHaveText(/Large/);
  await page.getByRole("button", { name: "Move From this person up" }).click();
  await page.reload();
  await expect(page.getByTestId("panel").nth(3)).toHaveAttribute("aria-label", "From this person");
  await expect(page.getByRole("region", { name: "From this person" }).getByRole("combobox", { name: "Size" })).toHaveText(/Large/);

  await page.getByRole("button", { name: "Reset panels" }).click();
  await expect(page.getByTestId("panel")).toHaveCount(4);
});

test("adding many files shows how each one went, and says why one can't be read", async ({ page }) => {
  await page.goto("/documents/all");
  const scan = `${unique("scan").replace(" ", "-")}.png`;
  const same = `${unique("same").replace(" ", "-")}.txt`;
  const again = `${unique("again").replace(" ", "-")}.txt`;
  const text = Buffer.from(`the same content ${scan}`);
  await page.getByTestId("file-input").setInputFiles([
    { name: scan, mimeType: "image/png", buffer: Buffer.from("\x89PNG\r\n\x1a\n") },
    { name: "setup.exe", mimeType: "application/octet-stream", buffer: Buffer.from("MZ") },
    { name: "nothing.txt", mimeType: "text/plain", buffer: Buffer.alloc(0) },
    { name: same, mimeType: "text/plain", buffer: text },
  ]);

  // The two refused stay on screen with their reason. The other two are kept.
  const refused = page.getByTestId("upload-row");
  await expect(refused.filter({ hasText: "setup.exe" }).getByRole("alert")).toContainText("can run programs");
  await expect(refused.filter({ hasText: "nothing.txt" }).getByRole("alert")).toContainText("empty");
  await noViolations(page);
  await page.getByRole("button", { name: "Dismiss setup.exe" }).click();
  await expect(refused.filter({ hasText: "setup.exe" })).toHaveCount(0);

  // A picture can't be read yet, and it says so instead of quietly being unsearchable.
  const row = page.getByTestId("document-row").filter({ hasText: scan });
  await expect(row.getByTestId("document-status")).toHaveText("Picture, not read");
  await row.click();
  await page.getByTestId("document-preview").getByRole("button", { name: "Info" }).click();
  await expect(page.getByTestId("document-reason")).toBeVisible();
  await expect(page.getByRole("button", { name: "Read it again" })).toBeVisible();
  await noViolations(page);
  await page.keyboard.press("Escape");

  // The same content twice stays one document, and the person is told.
  await expect(page.getByTestId("document-row").filter({ hasText: same })).toBeVisible();
  await page.getByTestId("file-input").setInputFiles({ name: again, mimeType: "text/plain", buffer: text });
  await expect(page.getByText(`${same} is already here`, { exact: true })).toBeVisible();
  await expect(page.getByTestId("document-row").filter({ hasText: again })).toHaveCount(0);
});

test("Documents filters by where things came from, and shows the Home folder", async ({ page }) => {
  await page.goto("/documents/all");
  await page.getByRole("radio", { name: "Home folder" }).click();
  await expect(page).toHaveURL(/\/documents\/home$/);
  const folders = page.getByTestId("home-entry");
  await expect(folders.filter({ hasText: "scratch" })).toBeVisible();
  await expect(folders.filter({ hasText: "system" })).toHaveCount(0);
  await noViolations(page);
  await page.getByRole("radio", { name: "Email attachments" }).click();
  await expect(page).toHaveURL(/\/documents\/from-email$/);
});

test("a file opens straight away, arrows move between files, and right-click has the same actions", async ({ page }) => {
  const first = `${unique("first").replace(" ", "-")}.txt`;
  const second = `${unique("second").replace(" ", "-")}.txt`;
  await page.goto("/documents/all");
  await page.getByTestId("file-input").setInputFiles({ name: first, mimeType: "text/plain", buffer: Buffer.from("First file text.") });
  await expect(page.getByTestId("document-row").filter({ hasText: first })).toBeVisible();
  await page.getByTestId("file-input").setInputFiles({ name: second, mimeType: "text/plain", buffer: Buffer.from("Second file text.") });
  const newest = page.getByTestId("document-row").filter({ hasText: second });
  await expect(newest).toBeVisible();

  await newest.click();
  const preview = page.getByTestId("document-preview");
  await expect(preview).toContainText("Second file text.");
  await expect(page.getByTestId("assistant-pill")).toHaveCount(0);
  await page.getByRole("button", { name: "Next file" }).click();
  await expect(preview).toContainText("First file text.");
  await page.keyboard.press("ArrowLeft");
  await expect(preview).toContainText("Second file text.");
  await page.keyboard.press("Escape");
  await expect(preview).toHaveCount(0);

  await newest.click({ button: "right" });
  const menu = page.getByRole("menu");
  for (const name of ["Open", "Download", "Ask the agent about this"]) await expect(menu.getByRole("menuitem", { name })).toBeVisible();
  await menu.getByRole("menuitem", { name: "Open" }).click();
  await expect(preview).toContainText("Second file text.");
  await page.keyboard.press("Escape");
});

test("each kind of file opens the way it reads best", async ({ page }) => {
  const upload = async (name: string, body: string) => {
    const response = await page.request.post(`/api/documents/upload?name=${name}`, { data: Buffer.from(body), headers: { "content-type": "application/octet-stream" } });
    const row = (await response.json()) as { key: string };
    await expect
      .poll(async () => ((await (await page.request.post("/api/queries/documents.get", { data: { key: row.key } })).json()) as { document: { status: string } }).document.status)
      .not.toBe("pending");
    return row.key;
  };
  const stamp = Date.now();
  const code = await upload(`script-${stamp}.py`, "print('one')\nprint('two')");
  await page.goto(`/documents/view?key=${encodeURIComponent(code)}`);
  const lines = page.getByRole("region", { name: `script-${stamp}.py` });
  await expect(lines).toContainText("print('two')");
  await expect(lines.getByRole("row")).toHaveCount(2);
  await noViolations(page);

  const sheet = await upload(`table-${stamp}.csv`, "Item,Cost\nServers,1200");
  await page.goto(`/documents/view?key=${encodeURIComponent(sheet)}`);
  await expect(page.getByRole("columnheader", { name: "Cost" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "1200" })).toBeVisible();
  await noViolations(page);

  const note = await upload(`note-${stamp}.md`, "# Heading\n\nSome **bold** words.");
  await page.goto(`/documents/view?key=${encodeURIComponent(note)}`);
  await expect(page.getByTestId("reader-text").getByRole("heading", { name: "Heading" })).toBeVisible();

  const page_ = await upload(`page-${stamp}.html`, "<h1>Safe title</h1><script>document.title='HACKED'</script>");
  await page.goto(`/documents/view?key=${encodeURIComponent(page_)}`);
  await expect(page.frameLocator("iframe").getByText("Safe title")).toBeVisible();
  await expect(page).not.toHaveTitle("HACKED");
});

test("search says what it's doing about meaning, and words still work without the model", async ({ page }) => {
  await page.goto("/search?q=budget");
  await expect(page.getByTestId("meaning-notice")).toContainText("word matches");
  await noViolations(page);
  await page.goto("/settings?section=local-models");
  await expect(page.getByRole("heading", { name: "Search by meaning" })).toBeVisible();
  await expect(page.getByTestId("local-model").getByRole("alert")).toContainText(/mirror/);
  // A failed download opens the other ways to get it, without being asked.
  await expect(page.getByLabel("Use files you already have")).toBeVisible();
  await expect(page.getByTestId("index-mail")).toContainText("Off");
  await expect(page.getByTestId("index-document")).toContainText("Revision");
  await noViolations(page);
});
