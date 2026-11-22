import { expect, test } from '@playwright/test';

// Read-only checks for the handbook rollout. Runs before the zz-* specs, which write records.
const pages = ['/', '/sell', '/buy', '/stock', '/money', '/close', '/reports', '/setup', '/setup/dataset'];

test('every workspace uses the shared heading and no milestone badges remain', async ({ page }) => {
  for (const path of pages) {
    await page.goto(path);
    await expect(page.locator('.page-heading'), path).toHaveCount(1);
    await expect(page.locator('h1'), path).toHaveCount(1);
    await expect(page.getByText(/M[0-9] · [A-Z]+/), path).toHaveCount(0);
  }
});

test('report library searches, groups and keeps the reporting month', async ({ page }) => {
  await page.goto('/reports?period=2026-10');
  const library = page.getByRole('region', { name: 'Report library' });
  await expect(library.getByRole('status')).toHaveText(/^18 of 18 reports$/);
  await library.getByLabel('Find a report').fill('deposit');
  await expect(library.getByRole('status')).toHaveText('2 of 18 reports');
  await library.getByRole('link', { name: 'Supplier deposits' }).click();
  await expect(page).toHaveURL(/period=2026-10&report=supplier-deposits/);
  await expect(page.getByRole('heading', { level: 1, name: 'Supplier deposits' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Supplier deposits' })).toHaveAttribute('aria-current', 'page');
  await library.getByLabel('Find a report').fill('zzzz');
  await expect(page.getByText('No reports match “zzzz”.', { exact: false })).toBeVisible();
});

test('close shows each check, the first blocker and where to go next', async ({ page }) => {
  await page.goto('/close?period=2026-10');
  await expect(page.getByText('2026-10 · OPEN', { exact: true })).toBeVisible();
  const checks = page.getByRole('list', { name: 'Month-end checks in order' }).getByRole('listitem');
  await expect(checks).toHaveCount(5);
  await expect(page.getByText(/^Month stays open — first unresolved check: G-[1-5]$/)).toBeVisible();
  await expect(page.getByText('Next step:', { exact: false })).toBeVisible();
  await checks.first().getByText('Evidence details').click();
  await expect(checks.first().locator('pre')).toBeVisible();
});

test('money keeps one primary action and groups the rest by task', async ({ page }) => {
  await page.goto('/money');
  await expect(page.locator('.page-heading').getByRole('link', { name: 'Record expense' })).toBeVisible();
  const groups = page.getByRole('region', { name: 'Other money actions' });
  for (const name of ['Owner and exchange rates', 'Month-end estimates', 'Freight and duty', 'Tax and clearing']) await expect(groups.getByText(name, { exact: true })).toBeVisible();
  await expect(groups.getByRole('link')).toHaveCount(13);
});

test('flows use compact headings without artwork', async ({ page }) => {
  for (const path of ['/money?action=expense', '/stock?action=count', '/sell?action=deal', '/setup?action=product', '/close?period=2026-10&action=review']) {
    await page.goto(path);
    await expect(page.locator('.page-heading.compact'), path).toHaveCount(1);
    await expect(page.locator('.page-heading-art'), path).toHaveCount(0);
  }
});

for (const width of [1440, 1150, 900, 650, 390, 375]) {
  test(`no page-level horizontal overflow at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    for (const path of pages) {
      await page.goto(path);
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth), `${path} at ${width}px`).toBeLessThanOrEqual(0);
    }
  });
}


test('report charts render at a readable width on desktop and mobile', async ({ page }) => {
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/reports?period=2026-10');
    const plots = page.locator('.recharts-surface');
    await expect(plots.first()).toBeVisible();
    for (const plot of await plots.all()) {
      await expect(plot).toBeVisible();
      const bounds = await plot.boundingBox();
      expect(bounds?.width).toBeGreaterThan(100);
      expect(bounds?.height).toBeGreaterThan(100);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);
  }
});
