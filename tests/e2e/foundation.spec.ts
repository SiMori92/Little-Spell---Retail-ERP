import { expect, test } from '@playwright/test';
test('first visit shows quarantine, honest empty metrics, navigation, and setup guide',async({page})=>{
  await page.goto('/');await expect(page.getByText('SAMPLE DATA — NOT ACTUALS',{exact:false})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Your day, at a glance'})).toBeVisible();
  await page.getByRole('link',{name:'Open setup'}).click();await expect(page.getByRole('heading',{name:'Your setup checklist'})).toBeVisible();
  await expect(page.getByText('pnpm backup',{exact:false})).toBeVisible();
  await page.getByRole('link',{name:'Close',exact:true}).click();await expect(page.getByText('NOT RUNNABLE',{exact:false})).toBeVisible();
});
test('guided correction previews before confirmation and preserves original history',async({page,request})=>{
  await page.goto('/money');const before=await(await request.get('/api/system/status')).json();
  await page.getByRole('row').filter({hasText:'journal.post'}).first().click();await page.getByLabel('Why are you correcting this?').fill('Correct synthetic test entry');
  await page.getByRole('button',{name:'Check correction'}).click();await page.getByRole('button',{name:'Preview effects'}).click();
  await expect(page.getByText('This will undo the original recorded stock and money effects exactly.',{exact:false})).toBeVisible();
  const afterPreview=await(await request.get('/api/system/status')).json();expect(afterPreview.runCount).toBe(before.runCount);
  await page.getByRole('button',{name:'Continue',exact:true}).click();await page.getByRole('button',{name:'Confirm reversal'}).click();await expect(page.getByRole('status').filter({hasText:'Reversal recorded.'})).toBeVisible();
  const after=await(await request.get('/api/system/status')).json();expect(after.runCount).toBe(before.runCount+1);
});
