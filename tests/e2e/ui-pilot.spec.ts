import { expect, test } from '@playwright/test';

const artKey = 'little-spell-artwork-shuffle-v1';

test('workspace artwork stays stable across filters and flow steps; reload advances the bag', async ({ page }) => {
  await page.goto('/buy');
  const art = page.locator('.page-heading-art');
  await expect(art.locator('a')).toBeVisible();
  const before = await art.getAttribute('style');
  const bag = await page.evaluate(key => sessionStorage.getItem(key), artKey);
  await page.getByRole('link', { name: 'Deliveries', exact: true }).click();
  await expect(art).toHaveAttribute('style', before!);
  expect(await page.evaluate(key => sessionStorage.getItem(key), artKey)).toBe(bag);
  await page.getByRole('link', { name: 'New purchase order', exact: true }).click();
  await expect(page.locator('.page-heading')).toHaveClass(/compact-heading/);
  await expect(art).toBeHidden();
  expect(await page.evaluate(key => sessionStorage.getItem(key), artKey)).toBe(bag);
  await page.reload();
  await page.getByRole('link', { name: 'Back to purchasing', exact: true }).click();
  await expect(art.locator('a')).toBeVisible();
  await expect(art).not.toHaveAttribute('style', before!);
});

test('artwork failure and blocked storage preserve a usable workspace', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, 'sessionStorage', { get() { throw new Error('Storage blocked'); } });
  });
  await page.route('**/art/*.jpg', route => route.abort());
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Your day, at a glance' })).toBeVisible();
  await expect(page.locator('.page-heading-art a')).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Open setup', exact: true })).toBeVisible();
});

test('pilot layouts keep page overflow contained at handbook breakpoints', async ({ page }) => {
  for (const width of [1440, 1151, 1150, 901, 900, 651, 650, 390, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const path of ['/', '/buy', '/buy?action=po']) {
      await page.goto(path);
      await expect(page.locator('main h1')).toHaveCount(1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${path} at ${width}px`).toBe(true);
    }
  }
});

test('skip link reaches main content and nested setup keeps navigation selected', async ({ page }) => {
  await page.goto('/');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Skip to main content' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('main')).toBeFocused();
  await page.goto('/setup/dataset');
  await expect(page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Setup', exact: true })).toHaveAttribute('aria-current', 'page');
});
