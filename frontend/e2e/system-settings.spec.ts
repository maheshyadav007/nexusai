import { expect, test } from "@playwright/test";

// The servers themselves are proven against fake ones in backend/tests/test_system_settings.py.
const presets = [
  { domain: "gmail.com", label: "Gmail", imap_host: "imap.gmail.com", imap_port: 993, smtp_host: "smtp.gmail.com", smtp_port: 465, secure: true, protocol: "imap", system: false },
  { domain: "*", label: "Company mail", imap_host: "10.0.0.2", imap_port: 995, smtp_host: "10.0.0.2", smtp_port: 25, secure: true, protocol: "pop3", system: true, address_domain: "corp.example" },
];
const noAccount = { active: null, accounts: [] };
const tested = { ok: true, total: 0, counts: [], suggested_pull: 0, results: [] };

test("with system settings, a mail account only asks for a username and password", async ({ page }) => {
  await page.route("**/api/queries/mail.presets", (route) => route.fulfill({ json: { presets } }));
  await page.route("**/api/queries/mail.accounts", (route) => route.fulfill({ json: noAccount }));
  const sent: Array<{ profile: Record<string, unknown> }> = [];
  await page.route("**/api/commands/mail.accounts.test", (route) => {
    sent.push(route.request().postDataJSON());
    return route.fulfill({ json: tested });
  });
  await page.goto("/connectors");
  await expect(page.getByRole("textbox", { name: "Username" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Password" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Server" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Server details" })).toHaveCount(0);

  await page.getByRole("textbox", { name: "Username" }).fill("priya");
  await page.getByRole("textbox", { name: "Password" }).fill("secret");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect.poll(() => sent.length).toBe(1);
  expect(sent[0]?.profile).toMatchObject({ system: true, protocol: "pop3", address: "priya@corp.example" });

  // Gmail still goes to Gmail, however the company's server is set.
  await page.getByRole("textbox", { name: "Username" }).fill("priya@gmail.com");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect.poll(() => sent.length).toBe(2);
  expect(sent[1]?.profile).toMatchObject({ system: false, protocol: "imap", imap: { host: "imap.gmail.com" } });
});

test("with system settings, the model section only offers model names", async ({ page }) => {
  await page.route("**/api/queries/models.status", (route) => route.fulfill({ json: { connected: true, selected_model: "model-a", login: { state: "idle" }, managed: true } }));
  await page.route("**/api/queries/models.list", (route) => route.fulfill({ json: { models: [{ id: "model-a", name: "model-a" }, { id: "model-b", name: "model-b" }] } }));
  await page.goto("/settings?section=models");
  await expect(page.getByRole("combobox", { name: "Model" }).first()).toBeVisible();
  await expect(page.getByRole("radiogroup")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Disconnect" })).toHaveCount(0);
  await expect(page.getByText(/address|API key/i)).toHaveCount(0);
});
