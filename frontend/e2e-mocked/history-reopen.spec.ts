import { expect, test } from "@playwright/test";
import { launchJob, waitForTerminal } from "./helpers";

test("reopening a job from history restores its evidence", async ({ page }) => {
  await launchJob(page, ["rdap", "dns_doh"]);
  await waitForTerminal(page);

  await page.getByRole("button", { name: /^new job$/i }).click();
  await page.getByRole("button", { name: /^history$/i }).click();

  // History lists newest first, and this job was just created, so it's the
  // first "example.com" row regardless of what earlier spec files left behind.
  await page.getByRole("button", { name: /example\.com/i }).first().click();

  await waitForTerminal(page);
  await expect(page.getByText(/registrar: example registrar inc\./i)).toBeVisible();
});
