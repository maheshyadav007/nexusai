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
  await page.getByRole("link", { name: "Connect mail in Settings" }).click();
  await expect(page).toHaveURL(/section=accounts/);

  await page.getByRole("radio", { name: "Other" }).click();
  await page.getByRole("textbox", { name: "Email address" }).fill(USER);
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("textbox", { name: "IMAP server" }).fill("127.0.0.1");
  await page.getByRole("textbox", { name: "IMAP port" }).fill("8143");
  await page.getByRole("textbox", { name: "SMTP server" }).fill("127.0.0.1");
  await page.getByRole("textbox", { name: "SMTP port" }).fill("8025");
  await page.getByRole("switch", { name: "Encrypted connection" }).click();
  await noViolations(page);

  await page.getByRole("button", { name: "Test connection" }).click();
  await expect(page.getByTestId("connection-results")).toContainText("refused that username or password");

  await page.getByLabel("Password").fill("test-password");
  await page.getByRole("button", { name: "Test connection" }).click();
  await expect(page.getByTestId("connection-results").getByText("Connected")).toHaveCount(2);

  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByTestId("mail-state")).toContainText("Up to date", { timeout: 20_000 });
  await expect(page.getByText(USER)).toBeVisible();
  await expect(page.getByLabel("Password")).toHaveCount(0);
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
  expect(tracker).toEqual([]);
  await expect(page.getByText("Remote images are blocked")).toBeVisible();
  await noViolations(page);

  await page.goto("/mail/all");
  await expect(page.getByTestId("thread-row").filter({ hasText: subject }).locator("span.bg-accent-default")).toHaveCount(0);
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

  await page.getByRole("searchbox").fill(word);
  await page.getByRole("searchbox").press("Enter");
  await expect(page).toHaveURL(/\/search\?q=/);
  await expect(page.getByTestId("search-hit")).toHaveCount(1);
  await noViolations(page);
  await page.getByRole("textbox", { name: "From" }).fill("nobody-matches");
  await expect(page.getByText("Nothing found")).toBeVisible();
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
  await expect(page.getByTestId("thread-row").filter({ hasText: subject })).toHaveCount(0);
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

  await row.click();
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
  await page.goto("/settings?section=archive");
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

test("search says what it's doing about meaning, and words still work without the model", async ({ page }) => {
  await page.goto("/search?q=budget");
  await expect(page.getByTestId("meaning-notice")).toContainText("word matches");
  await noViolations(page);
  await page.goto("/settings?section=local-models");
  await expect(page.getByRole("heading", { name: "Search by meaning" })).toBeVisible();
  await expect(page.getByTestId("local-model").getByRole("alert")).toContainText(/mirror/);
  // A failed download opens the other ways to get it, without being asked.
  await expect(page.getByLabel("Use files you already have")).toBeVisible();
  await noViolations(page);
});
