import { expect, test } from "@playwright/test";
import { launchJob, waitForTerminal } from "./helpers";

test("comparing two identical runs of the same target shows them as unchanged", async ({ page }) => {
  const [jobAResponse] = await Promise.all([
    page.waitForResponse((r) => r.url().endsWith("/api/jobs") && r.request().method() === "POST"),
    launchJob(page, ["rdap", "dns_doh"]),
  ]);
  const jobA = (await jobAResponse.json()) as { id: string };
  await waitForTerminal(page);

  await launchJob(page, ["rdap", "dns_doh"]);
  await waitForTerminal(page);

  await page.getByLabel(/compare against/i).selectOption(jobA.id);
  await page.getByRole("button", { name: /^compare$/i }).click();

  await expect(page.getByText(/0 added · 0 changed · 0 removed · 1 unchanged/i)).toBeVisible();
});
