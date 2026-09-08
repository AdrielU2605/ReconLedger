import { expect, test } from "@playwright/test";
import { launchJob, waitForTerminal } from "./helpers";

test("a job with every selected source succeeding reaches completed and shows its evidence", async ({ page }) => {
  await launchJob(page, ["rdap", "dns_doh"]);
  await waitForTerminal(page);

  await expect(page.getByText(/status:\s*completed/i)).toBeVisible();
  await expect(page.getByRole("row", { name: /rdap/i })).toContainText(/done/i);
  await expect(page.getByRole("row", { name: /dns_doh/i })).toContainText(/done/i);

  // The scripted RDAP record's registrar shows up as real evidence content,
  // not just a status label.
  await expect(page.getByText(/registrar: example registrar inc\./i)).toBeVisible();
});
