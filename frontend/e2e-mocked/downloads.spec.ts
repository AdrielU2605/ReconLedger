import { expect, test } from "@playwright/test";
import { launchJob, waitForTerminal } from "./helpers";

test("all three evidence exports download successfully", async ({ page }) => {
  await launchJob(page, ["rdap", "dns_doh"]);
  await waitForTerminal(page);

  const [mdDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: /download markdown/i }).click(),
  ]);
  expect(mdDownload.suggestedFilename()).toMatch(/\.md$/);

  const [jsonDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: /download json/i }).click(),
  ]);
  expect(jsonDownload.suggestedFilename()).toMatch(/\.json$/);

  const [csvDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: /download csv/i }).click(),
  ]);
  expect(csvDownload.suggestedFilename()).toMatch(/\.csv$/);
});
