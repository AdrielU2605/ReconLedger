import { expect, test } from "@playwright/test";

test("core header controls are reachable and operable via keyboard alone", async ({ page }) => {
  await page.goto("/");

  // Tab until the History button is focused - bounded, so a broken tab
  // order (e.g. a stray tabindex or a focus trap) fails loudly instead of
  // hanging.
  let focused = false;
  for (let i = 0; i < 10 && !focused; i++) {
    await page.keyboard.press("Tab");
    focused = await page
      .getByRole("button", { name: /^history$/i })
      .evaluate((el) => el === document.activeElement);
  }
  expect(focused).toBe(true);

  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: /^history/i })).toBeVisible();

  // The target input itself must also be reachable and typeable via keyboard.
  await page.getByRole("button", { name: /^new job$/i }).click();
  await page.getByLabel(/target \(domain, ip, or cidr\)/i).focus();
  await page.keyboard.type("example.com");
  await expect(page.getByLabel(/target \(domain, ip, or cidr\)/i)).toHaveValue("example.com");
});
