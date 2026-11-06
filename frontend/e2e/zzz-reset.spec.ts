import { expect, test } from "@playwright/test";

test("reset explains the new learning state and keeps failure details visible", async ({ page }) => {
  await page.goto("/settings?section=reset");
  let release!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/home/reset", async (route) => {
    await pending;
    await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ code: "home.reset_incomplete", message: "Close held.docx before removing the remaining folder." }) });
  });
  await page.getByRole("button", { name: "Reset NexusAI" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(/learned sender groups, interviews/)).toBeVisible();
  await dialog.getByRole("textbox", { name: "Type RESET to confirm" }).fill("RESET");
  await dialog.getByRole("button", { name: "Remove everything" }).click();
  await expect(dialog.getByRole("checkbox", { name: "Keep downloaded search models" })).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeVisible();
  release();
  await expect(dialog.getByText("Close held.docx before removing the remaining folder.")).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Remove everything" })).toBeEnabled();
});

// Last of all, because it removes the Home every other file uses.
test("reset removes everything from the browser, and setup starts again", async ({ page }) => {
  await page.goto("/settings?section=reset");
  await page.evaluate(() => localStorage.setItem("left-behind", "yes"));
  await page.getByRole("button", { name: "Reset NexusAI" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox", { name: "Type RESET to confirm" }).fill("RESET");
  await dialog.getByRole("button", { name: "Remove everything" }).click();
  await expect(page).toHaveURL(/\/welcome$/, { timeout: 30_000 });
  expect(await page.evaluate(() => localStorage.getItem("left-behind"))).toBeNull();
  const status = (await (await page.request.post("/api/home/status", { data: {} })).json()) as { state: string };
  expect(status.state).toBe("unset");
  await page.getByRole("button", { name: "Get started" }).click();
  await page.getByRole("textbox", { name: "Folder" }).fill(`${process.env.E2E_HOME}/AfterReset`);
  await expect(page.getByText(/free on this drive/)).toBeVisible();
  await page.getByRole("button", { name: "Use this folder" }).click();
  await expect(page.getByRole("heading", { name: "Tell NexusAI about you" })).toBeVisible();
});
