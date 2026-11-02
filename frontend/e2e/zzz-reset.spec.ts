import { expect, test } from "@playwright/test";

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
  await expect(page.getByRole("heading", { name: "Save your recovery key" })).toBeVisible();
});
