import { expect, test, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';

async function preview(page:Page){await page.getByRole('button',{name:'Check selling details',exact:true}).click();await page.getByRole('button',{name:'Preview selling effects',exact:true}).click();await expect(page.getByRole('heading',{name:'What will be recorded',exact:true})).toBeVisible();}
async function confirm(page:Page){await page.getByRole('button',{name:'Continue to selling confirmation',exact:true}).click();await page.getByRole('button',{name:'Confirm selling action',exact:true}).click();await expect(page.getByRole('heading',{name:'Selling action recorded',exact:true})).toBeVisible();}
async function etsyFiles(page:Page,ordersCsv?:string){await page.getByLabel('Order-items CSV',{exact:true}).setInputFiles({name:'SAMPLE_etsy_orderitems_2025-12_fixture.csv',mimeType:'text/csv',buffer:Buffer.from(ordersCsv??await readFile('seed/fixtures/SAMPLE_etsy_orderitems_2025-12_fixture.csv','utf8'))});await page.getByLabel('Monthly statement CSV',{exact:true}).setInputFiles('seed/fixtures/SAMPLE_etsy_statement_2025-12_fixture.csv');for(const [index,code] of ['WELCOME10','HOLIDAY15','FREESHIP'].entries()){await page.getByRole('button',{name:'Add coupon rule',exact:true}).click();await page.getByLabel('Coupon code',{exact:true}).nth(index).fill(code);await page.getByLabel('Coupon evidence',{exact:true}).nth(index).fill('synthetic-founder-coupon-rule');}}

test.describe.serial('selling guided flows',()=>{
  test('Etsy preview respects header gate, then an evidenced review unlocks confirmation',async({page,request})=>{
    await page.goto('/sell?action=etsy');await etsyFiles(page);const before=await(await request.get('/api/system/status')).json();await preview(page);
    await expect(page.getByRole('alert').filter({hasText:'Etsy headers are unverified'})).toBeVisible();await expect(page.getByRole('button',{name:'Continue to selling confirmation'})).toBeDisabled();expect((await(await request.get('/api/system/status')).json()).runCount).toBe(before.runCount);
    await page.goto('/sell?action=verify-etsy');await page.getByLabel('Header review evidence',{exact:true}).fill('synthetic-header-comparison');await page.getByRole('checkbox').check();await preview(page);await confirm(page);
    await page.goto('/sell?action=etsy');await etsyFiles(page);await preview(page);await expect(page.getByText('UNPOSTED accounting event(s).',{exact:false})).toBeVisible();await confirm(page);
    await page.goto('/sell');await expect(page.getByRole('table',{name:'orders',exact:true}).getByRole('row')).toHaveCount(6);
  });
  test('repeat Etsy import adds no run; statement and accounting drawers expose honest controls',async({page,request})=>{
    const before=await(await request.get('/api/system/status')).json();await page.goto('/sell?action=etsy');await etsyFiles(page);await preview(page);await confirm(page);await expect(page.getByRole('status').filter({hasText:'Already recorded. No new run'})).toBeVisible();expect((await(await request.get('/api/system/status')).json()).runCount).toBe(before.runCount);
    await page.goto('/sell?tab=statements');await page.getByRole('row').filter({hasText:'2025-12'}).click();await expect(page.getByRole('table',{name:'statement rows',exact:true}).getByRole('row')).toHaveCount(11);await page.getByRole('button',{name:'Close selling record'}).click();
    await page.goto('/sell?tab=events');await expect(page.getByRole('table',{name:'events',exact:true}).getByText('UNPOSTED').first()).toBeVisible();
  });
  test('Instagram flow validates inline, appends forward statuses, and shows history in table and kanban',async({page,request})=>{
    await page.goto('/sell?action=deal');await page.getByRole('button',{name:'Check selling details'}).click();await expect(page.getByRole('alert').first()).toBeVisible();
    await page.getByLabel('Deal identifier',{exact:true}).fill('IG-202611-850');await page.getByLabel('Anonymous customer reference',{exact:true}).fill('C-0850');await page.getByLabel('Enquiry date',{exact:true}).fill('2026-11-01');await page.getByLabel('Next follow-up date',{exact:true}).fill('2026-11-10');await page.getByLabel('Deal evidence',{exact:true}).fill('synthetic-enquiry');
    const before=await(await request.get('/api/system/status')).json();await preview(page);expect((await(await request.get('/api/system/status')).json()).runCount).toBe(before.runCount);await confirm(page);
    await page.goto('/sell?tab=deals');await page.getByLabel('Search deals',{exact:true}).fill('IG-202611-850');await page.getByRole('row').filter({hasText:'IG-202611-850'}).click();await page.getByRole('button',{name:'Move deal forward'}).click();await page.getByLabel('New status',{exact:true}).selectOption('quoted');await page.getByLabel('Quote date',{exact:true}).fill('2026-11-02');await page.getByLabel('Quote total (TWD)',{exact:true}).fill('600.0000');await page.getByLabel('Deal evidence',{exact:true}).fill('synthetic-quote');await preview(page);await confirm(page);await page.getByRole('button',{name:'Close selling record'}).click();
    await page.getByRole('row').filter({hasText:'IG-202611-850'}).click();await expect(page.getByRole('table',{name:'deal history',exact:true}).getByRole('row')).toHaveCount(3);await page.getByRole('button',{name:'Close selling record'}).click();
    await page.goto('/sell?tab=deals&view=board');await page.getByRole('button').filter({hasText:'IG-202611-850'}).click();await expect(page.getByText('synthetic-quote',{exact:true}).first()).toBeVisible();
    await page.goto('/');await expect(page.getByText('Instagram follow-up',{exact:false}).first()).toBeVisible();
  });
  test('a previously unshipped order dispatches once through a zero-write preview',async({page,request})=>{
    const source=await readFile('seed/fixtures/SAMPLE_etsy_orderitems_2025-12_fixture.csv','utf8');
    const [header,...lines]=source.trimEnd().split('\n');const shipColumn=header!.split(',').indexOf('Date Shipped');
    const orders=[header,...lines.map(line=>{const cells=line.replaceAll('291847','391847').replaceAll('384910','484910').split(',');cells[shipColumn]='';return cells.join(',');})].join('\n')+'\n';
    await page.goto('/sell?action=etsy');await etsyFiles(page,orders);await preview(page);await confirm(page);
    await page.goto('/sell?action=dispatch&order=3918473019');await page.getByLabel('Action date',{exact:true}).fill('2025-12-31');await page.getByLabel('Dispatch date',{exact:true}).fill('2025-12-31');await page.getByLabel('Dispatch evidence',{exact:true}).fill('synthetic-shipping-receipt');
    const before=await(await request.get('/api/system/status')).json();await preview(page);expect((await(await request.get('/api/system/status')).json()).runCount).toBe(before.runCount);await confirm(page);expect((await(await request.get('/api/system/status')).json()).runCount).toBe(before.runCount+1);
    await page.goto('/sell');await page.getByLabel('Search orders',{exact:true}).fill('3918473019');await expect(page.getByRole('row').filter({hasText:'3918473019'}).getByText('shipped',{exact:true})).toBeVisible();
  });
  test('Instagram sample re-import adds no run and never sends a notification',async({page,request})=>{
    const before=await(await request.get('/api/system/status')).json();await page.goto('/sell?action=ig-import');await page.getByLabel('Instagram v2 CSV',{exact:true}).setInputFiles('seed/samples/SAMPLE_ig_deals_2026-10.csv');await preview(page);await confirm(page);expect((await(await request.get('/api/system/status')).json()).runCount).toBe(before.runCount);await expect(page.getByText('No notification is sent.',{exact:false}).first()).toBeVisible();
  });
});

test('selling tables and board stay within a narrow viewport',async({page})=>{await page.setViewportSize({width:390,height:844});for(const target of ['/sell?tab=deals','/sell?tab=deals&view=board']){await page.goto(target);await expect(page.getByRole('heading',{name:'Sell',exact:true})).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);}});
