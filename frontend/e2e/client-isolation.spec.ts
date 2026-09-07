import { expect, test } from "@playwright/test";

/**
 * UX-12: the dashboard must never cause the browser to contact the assessed
 * target. This runs a real job against the fixed verification target
 * (example.com - never substitute another domain here, per the project's
 * own rule) through the real production gateway, so it proves the claim
 * against genuine RDAP/DNS evidence, not a scripted stand-in.
 */
const TARGET = "example.com";

test("no browser request ever resolves to the assessed target", async ({ page }) => {
  const requestedHosts = new Set<string>();
  page.on("request", (request) => {
    try {
      requestedHosts.add(new URL(request.url()).hostname);
    } catch {
      // ignore unparseable URLs (e.g. data:/blob:), which cannot be a target request anyway
    }
  });

  await page.goto("/");

  await page.getByLabel(/target \(domain, ip, or cidr\)/i).fill(TARGET);
  await page.getByLabel(/i own this target/i).check();

  // Keep the run fast and deterministic: crt.sh/Wayback/Common Crawl can
  // each take up to a minute against the real internet, which this
  // single-purpose isolation check doesn't need to exercise.
  for (const name of [/crt\.sh/i, /wayback/i, /common crawl/i]) {
    const checkbox = page.getByRole("listitem").filter({ hasText: name }).getByRole("checkbox");
    if (await checkbox.isChecked()) await checkbox.uncheck();
  }

  await page.getByRole("button", { name: /^launch job$/i }).click();

  // Wait for the job to reach a terminal state (the evidence panel only
  // renders once it does).
  await expect(page.getByRole("link", { name: /download markdown/i })).toBeVisible({ timeout: 45_000 });

  // Expand every raw-evidence disclosure - interacting with archived/
  // registry evidence must not trigger any request either.
  const disclosures = page.getByText("Raw evidence", { exact: true });
  const count = await disclosures.count();
  for (let i = 0; i < count; i++) {
    await disclosures.nth(i).click();
  }

  // No rendered link may point AT the target itself - checked by the link's
  // actual destination host, not by whether the URL text contains the
  // domain name. A legitimate evidence link, e.g. an RDAP query URL like
  // https://rdap.verisign.com/com/v1/domain/example.com, necessarily
  // includes the queried domain as a path segment while still pointing at
  // the registry, not the target - exactly what UX-12 allows.
  const hrefs = await page.locator("a[href]").evaluateAll((links) => links.map((l) => l.getAttribute("href") || ""));
  for (const href of hrefs) {
    let host: string;
    try {
      host = new URL(href, "http://localhost:5173").hostname;
    } catch {
      continue; // not an absolute/parseable URL (e.g. a relative in-app link) - cannot be a target link
    }
    expect(
      host === TARGET || host.endsWith(`.${TARGET}`),
      `link host must not be the target: ${href}`,
    ).toBe(false);
  }

  const targetHosts = [...requestedHosts].filter((host) => host === TARGET || host.endsWith(`.${TARGET}`));
  expect(targetHosts, `requests must never resolve to the assessed target: ${targetHosts.join(", ")}`).toEqual([]);
});
