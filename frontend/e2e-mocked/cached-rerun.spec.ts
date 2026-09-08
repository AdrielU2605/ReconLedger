import { expect, test } from "@playwright/test";
import { launchJob, waitForTerminal } from "./helpers";

test("running the same target again within the cache TTL shows a cached collector state", async ({ page }) => {
  await launchJob(page, ["rdap", "dns_doh"]);
  await waitForTerminal(page);
  await expect(page.getByRole("row", { name: /rdap/i })).not.toContainText(/cached/i);

  // Same target, same sources, run again - the response cache (FR-05)
  // should make this a cache hit rather than a fresh provider call.
  await launchJob(page, ["rdap", "dns_doh"]);
  await waitForTerminal(page);
  await expect(page.getByRole("row", { name: /rdap/i })).toContainText(/done \(cached\)/i);
});
