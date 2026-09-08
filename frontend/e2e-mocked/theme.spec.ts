import { expect, test } from "@playwright/test";

test("an explicit theme choice applies immediately and survives a reload", async ({ page }) => {
  await page.goto("/");
  const select = page.getByLabel(/theme/i);

  await select.selectOption("dark");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.getByLabel(/theme/i)).toHaveValue("dark");

  await page.getByLabel(/theme/i).selectOption("light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  await page.getByLabel(/theme/i).selectOption("system");
  await expect(page.locator("html")).not.toHaveAttribute("data-theme");
});
