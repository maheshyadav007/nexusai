import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const FAKE = "http://127.0.0.1:8766/__sent";

const connect = async (request: APIRequestContext) => {
  await request.post("/api/commands/models.login.start", { data: {} });
  await expect
    .poll(async () => ((await (await request.post("/api/queries/models.status", { data: {} })).json()) as { connected: boolean }).connected, { timeout: 20_000 })
    .toBe(true);
  await request.post("/api/commands/models.select", { data: { model: "gpt-best" } });
};

/**
 * The desktop shell, as far as the box can tell: the shortcut's open event and the calls back.
 * window.__open(selection) is the shortcut being pressed; window.__calls records what came back.
 */
const asDesktop = (page: Page) =>
  page.addInitScript(() => {
    const calls: [string, unknown][] = [];
    let listener: ((detail: { selection: string; shortcut: string }) => void) | null = null;
    // Like the real shell, a press made before the page listens waits to be taken.
    let pending: { selection: string; shortcut: string } | null = null;
    Object.assign(window, {
      __calls: calls,
      __open: (selection: string) => { pending = { selection, shortcut: "Control+Alt+Space" }; listener?.(pending); },
      nexusDesktop: {
        platform: "win32",
        caption: async () => undefined,
        status: async () => ({}),
        action: async () => ({}),
        notify: async () => true,
        quick: async (action: string, value?: unknown) => {
          calls.push([action, value]);
          if (action !== "take") return null;
          const detail = pending;
          pending = null;
          return detail;
        },
        onQuickOpen: (next: typeof listener) => { listener = next; return () => { listener = null; }; },
      },
    });
  });

const calls = async (page: Page) => (await page.evaluate(() => (window as unknown as { __calls: [string, unknown][] }).__calls)).filter(([action]) => action !== "take");
const press = (page: Page, selection: string) => page.evaluate((text) => (window as unknown as { __open: (s: string) => void }).__open(text), selection);

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ request }) => {
  await request.post("/api/home/choose", { data: { path: `${process.env.E2E_HOME}/NexusAI` } });
  await request.post("/api/commands/onboarding.finish", { data: {} });
  await connect(request);
});

test.afterAll(async ({ request }) => {
  await request.post("/api/commands/models.disconnect", { data: {} });
});

test("a question from the shortcut starts a new chat that answers in the box", async ({ page }) => {
  await asDesktop(page);
  await page.goto("/quick");
  const box = page.getByRole("region", { name: /^Ask / });
  await expect(box.getByRole("textbox")).toBeFocused();
  await press(page, "");
  const { violations } = await new AxeBuilder({ page }).include("section").analyze();
  expect(violations.map((v) => v.id)).toEqual([]);

  await box.getByRole("textbox").fill("Quick hello");
  await box.getByRole("textbox").press("Enter");
  await expect(page.getByTestId("agent-message")).toContainText("Hello from gpt-best");
  await expect(page.getByTestId("user-message")).toContainText("Quick hello");
  // The window grew to fit the conversation.
  expect((await calls(page)).filter(([action]) => action === "resize").length).toBeGreaterThan(0);

  // It's an ordinary chat, kept with the others.
  const link = (await calls(page)).length;
  await box.getByRole("button", { name: "Open in NexusAI" }).click();
  const opened = (await calls(page)).slice(link).find(([action]) => action === "open-in-app");
  expect(opened?.[1]).toMatch(/^\/agent\/sessions\/[0-9a-f]{32}\?view=full$/);

  // Pressing the shortcut again is a new question, and the last chat is a click away.
  await press(page, "");
  await expect(box.getByRole("textbox")).toHaveValue("");
  await box.getByRole("button", { name: "Last chat" }).click();
  await expect(page.getByTestId("user-message")).toContainText("Quick hello");

  // It plays its way out, then the window hides.
  await page.keyboard.press("Escape");
  await expect.poll(async () => (await calls(page)).at(-1)?.[0]).toBe("hide");
});

test("text selected in another app is quoted with the question", async ({ page }) => {
  await asDesktop(page);
  await page.goto("/quick");
  await press(page, "The PLM release moves to Friday.\nQA signs off Thursday.");
  const box = page.getByRole("region", { name: /^Ask / });
  await expect(box.getByTestId("quick-selection")).toContainText("The PLM release moves to Friday.");
  await expect(box.getByRole("textbox")).toHaveAttribute("placeholder", "Ask about the selected text");
  // Once it has glided to its new height, nothing in it is cut off.
  await expect.poll(() => box.evaluate((element) => element.scrollHeight - element.clientHeight)).toBeLessThanOrEqual(0);

  // Left out, it isn't sent.
  await box.getByRole("button", { name: "Leave out the selected text" }).click();
  await expect(box.getByTestId("quick-selection")).toHaveCount(0);

  await press(page, "The PLM release moves to Friday.\nQA signs off Thursday.");
  await box.getByRole("textbox").fill("When does QA sign off?");
  await box.getByRole("button", { name: "Send" }).click();
  await expect(page.getByTestId("agent-message")).toContainText("Hello from");
  await expect(page.getByTestId("user-message")).toContainText("When does QA sign off?");
  const sent = JSON.stringify(await (await page.request.get(FAKE)).json());
  expect(sent).toContain("> The PLM release moves to Friday.");
  expect(sent).toContain("> QA signs off Thursday.");
  expect(sent).toContain("When does QA sign off?");
});

test("selected text alone is enough to ask about it, even on the first press", async ({ page }) => {
  await asDesktop(page);
  // The shell presses before the page has loaded, as on the first shortcut after starting.
  await page.addInitScript(() => (window as unknown as { __open: (s: string) => void }).__open("ECO-4471 approved"));
  await page.goto("/quick");
  const box = page.getByRole("region", { name: /^Ask / });
  await expect(box.getByRole("button", { name: "Send" })).toBeEnabled();
  await box.getByRole("textbox").press("Enter");
  await expect(page.getByTestId("user-message")).toContainText("Explain this.");
});

test("links in an answer open in the app, not in the small box", async ({ page }) => {
  await asDesktop(page);
  await page.goto("/quick");
  await expect(page.getByRole("region", { name: /^Ask / }).getByRole("textbox")).toBeFocused();
  await page.evaluate(() => {
    const link = document.createElement("a");
    link.href = "/mail/thread/7";
    link.textContent = "a thread";
    document.querySelector("section")?.append(link);
  });
  await page.getByRole("link", { name: "a thread" }).click();
  expect((await calls(page)).at(-1)).toEqual(["open-in-app", "/mail/thread/7"]);
  await expect(page).toHaveURL(/\/quick$/);
});

test("the shortcut can be changed in Settings, and one another app holds is refused", async ({ page }) => {
  await page.addInitScript(() => {
    let status = { shortcut: "Control+Alt+Space", enabled: true, selection: true, registered: true, selectionAllowed: false, platform: "darwin", visible: false };
    Object.assign(window, {
      nexusDesktop: {
        platform: "darwin",
        caption: async () => undefined,
        status: async () => ({}),
        action: async () => ({}),
        notify: async () => true,
        quick: async (action: string, value?: { shortcut?: string; enabled?: boolean }) => {
          if (action === "update") {
            if (value?.shortcut === "Alt+Space") return { ...status, error: "taken" };
            status = { ...status, ...value };
          }
          return status;
        },
      },
    });
  });
  await page.goto("/settings?section=preferences");
  const card = page.locator("section", { has: page.getByRole("heading", { name: "Quick ask" }) });
  await expect(card.getByTestId("quick-shortcut")).toHaveText("⌃⌥Space");
  await expect(card.getByText("Allow access").first()).toBeVisible();
  await page.screenshot({ path: "test-results/quick-settings.png", fullPage: true });

  await card.getByRole("button", { name: "Change" }).click();
  await page.keyboard.press("Alt+Space");
  await expect(card.getByRole("alert")).toHaveText("Another app already uses that shortcut. Choose a different one.");
  await expect(card.getByTestId("quick-shortcut")).toHaveText("⌃⌥Space");

  await card.getByRole("button", { name: "Change" }).click();
  await page.keyboard.press("KeyK");
  await expect(card.getByRole("alert")).toHaveText("Hold Ctrl, Alt, Command or the Windows key as well.");
  await page.keyboard.press("Meta+Shift+KeyK");
  await expect(card.getByTestId("quick-shortcut")).toHaveText("⇧⌘K");
  await card.getByRole("button", { name: "Use the default" }).click();
  await expect(card.getByTestId("quick-shortcut")).toHaveText("⌃⌥Space");

  await card.getByRole("switch", { name: "Keyboard shortcut" }).click();
  await expect(card.getByTestId("quick-shortcut")).toHaveCount(0);
});

test("in a browser, with no desktop app, Settings shows no shortcut", async ({ page }) => {
  await page.goto("/settings?section=preferences");
  await expect(page.getByText("Open to").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Quick ask" })).toHaveCount(0);
});
