import { expect, test, type Page } from '@playwright/test';
import type { z } from 'zod';
import type { masterResultSchema } from '../../src/domain/schemas/masters';

async function preview(page: Page) {
  await page.getByRole('button', { name:'Check details', exact:true }).click();
  await page.getByRole('button', { name:'Preview what gets recorded', exact:true }).click();
  await expect(page.getByRole('heading', { name:'What will happen' })).toBeVisible();
}

async function confirm(page: Page) {
  await page.getByRole('button', { name:'Continue to confirm', exact:true }).click();
  const response = page.waitForResponse((result) => /\/api\/setup\/(record|import)$/.test(result.url()));
  await page.getByRole('button', { name:'Confirm record', exact:true }).click();
  await expect(page.getByRole('heading', { name:'Recorded', exact:true })).toBeVisible();
  const result = await (await response).json() as z.infer<typeof masterResultSchema>;
  expect(result.ok).toBe(true);
  return result;
}

test.describe.serial('guided master setup', () => {
  test('business details validate inline and preview without writing', async ({ page, request }) => {
    await page.goto('/setup?action=business');
    await page.getByRole('button', { name:'Check details' }).click();
    await expect(page.getByRole('alert').first()).toBeVisible();
    await page.getByLabel('Business name', { exact:true }).fill('Synthetic Studio');
    await page.getByLabel('Evidence reference', { exact:true }).fill('synthetic-founder-declaration');
    const before = await (await request.get('/api/system/status')).json();
    await preview(page);
    expect((await (await request.get('/api/system/status')).json()).runCount).toBe(before.runCount);
    await confirm(page);
    expect((await (await request.get('/api/system/status')).json()).runCount).toBe(before.runCount + 1);
    await page.goto('/');
    await expect(page.getByText('Opening stock recorded', { exact:true })).toBeVisible();
  });

  test('supplier and product additions retain evidenced compliance history', async ({ page }) => {
    await page.goto('/setup?action=supplier');
    await page.getByLabel('Supplier reference', { exact:true }).fill('SUP-850');
    await page.getByLabel('Supplier legal name', { exact:true }).fill('Synthetic Workshop');
    await page.getByLabel('When to pay', { exact:true }).fill('Before production');
    await page.getByLabel('Evidence reference', { exact:true }).fill('synthetic-supplier-quote');
    await preview(page);
    await confirm(page);
    await page.goto('/setup?tab=suppliers');
    await page.getByRole('row').filter({ hasText:'SUP-850' }).click();
    await page.getByRole('button', { name:'Record compliance change' }).click();
    await expect(page.getByLabel('Supplier legal name · fixed', { exact:true })).toHaveAttribute('readonly', '');
    await page.getByLabel('When to pay', { exact:true }).fill('On receipt');
    await page.getByLabel('Supplier declaration reference', { exact:true }).fill('compliance/suppliers/synthetic-declaration');
    await page.getByLabel('Evidence reference', { exact:true }).fill('synthetic-revised-terms');
    await preview(page);
    await confirm(page);
    await page.getByRole('button', { name:'Close record' }).click();
    await page.getByRole('row').filter({ hasText:'SUP-850' }).click();
    await expect(page.getByRole('table', { name:'changes', exact:true }).getByText('Before production', { exact:true })).toBeVisible();
    await page.getByRole('button', { name:'Close record' }).click();
    await page.goto('/setup?action=product');
    await page.getByLabel('SKU', { exact:true }).fill('TS-QA-850-S');
    await page.getByLabel('Product name', { exact:true }).fill('Synthetic Fern');
    await page.getByLabel('Supplier', { exact:true }).selectOption('SUP-850');
    await page.getByLabel('Evidence reference', { exact:true }).fill('synthetic-product-specification');
    await preview(page);
    await confirm(page);
    await page.goto('/setup?tab=products');
    await page.getByRole('row').filter({ hasText:'TS-QA-850-S' }).click();
    await page.getByRole('button', { name:'Record compliance change' }).click();
    await page.getByLabel('Ingredient evidence', { exact:true }).fill('compliance/suppliers/synthetic-ingredients');
    await page.getByLabel('Evidence reference', { exact:true }).fill('synthetic-ingredient-review');
    await preview(page);
    await confirm(page);
    await page.getByRole('button', { name:'Close record' }).click();
    await page.getByRole('row').filter({ hasText:'TS-QA-850-S' }).click();
    await expect(page.getByRole('table', { name:'changes', exact:true }).getByText('UNKNOWN', { exact:true })).toBeVisible();
  });

  test('all four master CSV imports are idempotent and tables export the filtered view', async ({ page, request }) => {
    const before = await (await request.get('/api/system/status')).json();
    let imports = 0;
    for (const area of ['suppliers', 'products', 'channels', 'accounts']) {
    const csv = await (await request.get(`/api/setup/template?area=${area}`)).text();
    for (const attempt of [0, 1]) {
      await page.goto(`/setup?action=import&tab=${area}`);
      await page.getByLabel('CSV file', { exact:true }).setInputFiles({ name:`SAMPLE_${area}_2026-11-16.csv`, mimeType:'text/csv', buffer:Buffer.from(csv) });
      await preview(page);
      await confirm(page);
      if (attempt === 1) await expect(page.getByRole('status').filter({ hasText:'Already imported or recorded.' })).toBeVisible();
      expect((await (await request.get('/api/system/status')).json()).runCount).toBe(before.runCount + imports + 1);
    }
    imports++;
    }
    await page.goto('/setup?tab=suppliers');
    await page.getByLabel('Search suppliers', { exact:true }).fill('SUP-850');
    await expect(page.getByRole('table', { name:'suppliers', exact:true }).getByRole('row')).toHaveCount(2);
    await page.getByLabel('Filter suppliers', { exact:true }).selectOption('Evidence recorded');
    const pending = page.waitForEvent('download');
    await page.getByRole('button', { name:'Export current view', exact:true }).click();
    expect((await pending).suggestedFilename()).toMatch(/^SAMPLE_suppliers_/);
    await page.goto('/setup?tab=accounts');
    await expect(page.getByRole('heading', { name:'Chart of accounts / 會計科目' })).toBeVisible();
    await expect(page.getByRole('table', { name:'accounts', exact:true }).getByRole('row')).toHaveCount(76);
    await page.goto('/setup?tab=channels');
    await expect(page.getByRole('table', { name:'channels', exact:true }).getByRole('row')).toHaveCount(3);
  });

  test('opening preparation remains unposted and no-stock declaration requires confirmation', async ({ page }) => {
    await page.goto('/setup?action=opening');
    await page.getByLabel('Pieces counted', { exact:true }).fill('12');
    await page.getByLabel('Agreed cost per piece (TWD)', { exact:true }).fill('2.5000');
    await page.getByLabel('Line evidence reference', { exact:true }).fill('synthetic-count-line');
    await page.getByLabel('Evidence reference', { exact:true }).fill('synthetic-count');
    await page.getByRole('checkbox').check();
    await preview(page);
    await expect(page.getByText('Opening stock preparation: NT$30.0000.', { exact:false })).toBeVisible();
    const prepared = await confirm(page);
    expect(prepared.effects.map((effect) => effect.type)).toEqual(['opening.prepared']);
    await page.goto('/setup');
    await expect(page.getByText('Opening stock is recorded. New setup preparation remains unposted and does not change it.', { exact:true })).toBeVisible();
    await page.goto('/setup?action=opening');
    await page.getByLabel('Do you have stock already?', { exact:true }).selectOption('no_stock');
    await page.getByLabel('Evidence reference', { exact:true }).fill('synthetic-no-stock-correction');
    await page.getByRole('button', { name:'Check details' }).click();
    await expect(page.getByText('Confirm the declaration before continuing.', { exact:true })).toBeVisible();
    await page.getByRole('checkbox').check();
    await preview(page);
    const declared = await confirm(page);
    expect(declared.effects.map((effect) => effect.type)).toEqual(['opening.prepared']);
    await page.goto('/setup');
    await expect(page.getByText('4 of 4 complete', { exact:true })).toBeVisible();
    await expect(page.getByText('This does not certify opening balances', { exact:false })).toBeVisible();
  });
});

test('setup remains usable on a narrow screen', async ({ page }) => {
  await page.setViewportSize({ width:390, height:844 });
  await page.goto('/setup?tab=products');
  await expect(page.getByRole('heading', { name:'Setup', exact:true })).toBeVisible();
  await expect(page.getByRole('link', { name:'Add product', exact:true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
