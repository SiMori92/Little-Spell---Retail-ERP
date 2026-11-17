import { afterEach, expect, test, vi } from 'vitest';
import { randomUUID } from 'node:crypto';
import { workspace } from './helpers';
import { initializeWorkspace } from '../src/server/initialize';

const cleanups:(()=>Promise<unknown>)[]=[];
afterEach(async()=>{delete process.env.ERP_DATA_DIR;vi.resetModules();for(const cleanup of cleanups.splice(0))await cleanup();});
test('selling route validates shared payload, previews without writing, confirms once, and blocks cross-origin',async()=>{
  const context=await workspace();cleanups.push(context.cleanup);await initializeWorkspace(context.store.directory);process.env.ERP_DATA_DIR=context.store.directory;vi.resetModules();
  const {POST:preview}=await import('../src/app/api/sell/record/preview/route');const {POST:confirm}=await import('../src/app/api/sell/record/route');
  const input={action:'deal',occurredOn:'2026-11-16',idempotencyKey:randomUUID(),previousRunId:null,record:{dealId:'IG-202611-800',customerRef:'C-0800',status:'enquiry',enquiryAt:'2026-11-01',quotedAt:null,quoteTwd:null,followUpOn:'2026-11-20',lostReason:'',lines:[{sku:'',qtySaleUnits:null,unitPriceTwd:null}],shippingTwd:null,shipCountry:'',paidAt:null,walletTxnId:'',shipDate:null,consentMarketing:'',journeySent:'none',evidenceRef:'synthetic-api-deal'}};
  const request=(body:unknown,origin='http://127.0.0.1:3000')=>new Request('http://127.0.0.1:3000/api/sell/record',{method:'POST',headers:{'Content-Type':'application/json',origin},body:JSON.stringify(body)});
  const before=(await context.store.read()).length;const proposed=await(await preview(request(input))).json();expect(proposed.ok).toBe(true);expect(proposed.runId).toBeNull();expect((await context.store.read()).length).toBe(before);
  const payload={...input,expectedHeadHash:proposed.headHash};const first=await(await confirm(request(payload))).json();const second=await(await confirm(request(payload))).json();expect(first.ok).toBe(true);expect(second.runId).toBe(first.runId);expect(second.duplicate).toBe(true);expect((await context.store.read()).length).toBe(before+1);
  expect((await confirm(request(input,'https://invalid.example'))).status).toBe(409);expect((await confirm(request({...input,buyerEmail:'not-accepted'}))).status).toBe(400);
  const {GET}=await import('../src/app/api/sell/records/route');const records=await(await GET(new Request('http://127.0.0.1:3000/api/sell/records'))).json();expect(records.ok).toBe(true);expect(records.deals.length).toBe(13);
});
