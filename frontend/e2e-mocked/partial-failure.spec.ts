import { expect, test } from "@playwright/test";
import { launchJob, waitForTerminal } from "./helpers";

test("a partial provider failure still surfaces the successful findings", async ({ page }) => {
  // crt.sh is scripted to always fail in the mocked backend (run_e2e_server_mocked.py).
  await launchJob(page, ["rdap", "dns_doh", "crtsh"]);
  await waitForTerminal(page);

  await expect(page.getByText(/status:\s*completed with warnings/i)).toBeVisible();
  await expect(page.getByText(/this job failed/i)).not.toBeVisible();

  const crtshRow = page.getByRole("row", { name: /crtsh/i });
  await expect(crtshRow).toContainText(/failed/i);
  // A plain-English reason is shown, not a raw exception.
  await expect(crtshRow).not.toContainText(/traceback/i);

  await expect(page.getByRole("row", { name: /^rdap /i })).toContainText(/done/i);
  await expect(page.getByText(/registrar: example registrar inc\./i)).toBeVisible();
});
