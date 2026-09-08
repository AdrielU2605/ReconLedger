import { expect, type Page } from "@playwright/test";

// The fixed verification target, per the project's own rule - never
// substitute another domain. The mocked backend (run_e2e_server_mocked.py)
// only has scripted responses for this exact target's providers.
export const TARGET = "example.com";

const SOURCE_LABELS: Record<string, RegExp> = {
  rdap: /rdap/i,
  dns_doh: /dns \(dns-over-https\)/i,
  crtsh: /crt\.sh/i,
  ripestat: /ripestat/i,
  wayback: /wayback/i,
  commoncrawl: /common crawl/i,
  technology: /technology inference/i,
};

/** Fills the target/attestation, leaves only the named sources checked
 * (every MVP source starts checked), and clicks Launch job. Does not wait
 * for completion - call waitForTerminal afterward. */
export async function launchJob(page: Page, keep: (keyof typeof SOURCE_LABELS)[]): Promise<void> {
  await page.goto("/");
  await page.getByLabel(/target \(domain, ip, or cidr\)/i).fill(TARGET);
  await page.getByLabel(/i own this target/i).check();

  for (const [name, pattern] of Object.entries(SOURCE_LABELS)) {
    const checkbox = page.getByRole("listitem").filter({ hasText: pattern }).getByRole("checkbox");
    const shouldKeep = (keep as string[]).includes(name);
    if ((await checkbox.isChecked()) && !shouldKeep) await checkbox.uncheck();
  }

  await page.getByRole("button", { name: /^launch job$/i }).click();
}

/** The evidence panel (and its download links) render only once the job
 * reaches a terminal state, so waiting for this link is the same "job is
 * done" signal the existing UX-12 spec uses. */
export async function waitForTerminal(page: Page, timeout = 15_000): Promise<void> {
  await expect(page.getByRole("link", { name: /download markdown/i })).toBeVisible({ timeout });
}
