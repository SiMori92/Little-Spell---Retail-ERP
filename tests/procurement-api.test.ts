import { afterEach,expect,test,vi } from 'vitest';
import { randomUUID } from 'node:crypto';
import { workspace } from './helpers';
import { initializeWorkspace } from '../src/server/initialize';
import { projectMasters } from '../src/domain/master-projection';
import { planMasters } from '../src/domain/masters';

const cleanups:(()=>Promise<unknown>)[]=[];
afterEach(async()=>{delete process.env.ERP_DATA_DIR;vi.resetModules();for(const cleanup of cleanups.splice(0))await cleanup();});
test('purchasing API preview writes zero, confirmation books once, retries duplicate, stale heads and cross-origin refuse',async()=>{
  const context=await workspace();cleanups.push(context.cleanup);await initializeWorkspace(context.store.directory);process.env.ERP_DATA_DIR=context.store.directory;vi.resetModules();
  const {POST:preview}=await import('../src/app/api/buy/record/preview/route'),{POST:confirm}=await import('../src/app/api/buy/record/route');
  const masters=projectMasters(await context.store.read());const input={action:'count',occurredOn:'2026-11-16',idempotencyKey:randomUUID(),founderConfirmed:true,record:{countedAt:'2026-11-16',evidenceRef:'synthetic-api-count',lines:masters.products.map(({record})=>({sku:record.sku,qtyPieces:'0',agreedUnitCostTwd:'0.0000',condition:'sellable'}))}};
  const request=(body:unknown,origin='http://127.0.0.1:3000')=>new Request('http://127.0.0.1:3000/api/buy/record',{method:'POST',headers:{'Content-Type':'application/json',origin},body:JSON.stringify(body)});
  const before=(await context.store.read()).length,proposed=await(await preview(request(input))).json();expect(proposed.ok).toBe(true);expect(proposed.effects.some((effect:{type:string})=>effect.type==='journal.posted')).toBe(true);expect((await context.store.read()).length).toBe(before);
  const payload={...input,expectedHeadHash:proposed.headHash};const first=await(await confirm(request(payload))).json(),duplicate=await(await confirm(request(payload))).json();expect(first.ok).toBe(true);expect(duplicate.runId).toBe(first.runId);expect(duplicate.duplicate).toBe(true);expect((await context.store.read()).length).toBe(before+1);
  const next={...input,idempotencyKey:randomUUID(),record:{...input.record,evidenceRef:'synthetic-next-count'}};const nextPreview=await(await preview(request(next))).json();await context.store.execute(runs=>planMasters({action:'business',occurredOn:'2026-11-16',idempotencyKey:randomUUID(),previousRunId:null,record:{tradingName:'Synthetic Studio',country:'TW',functionalCurrency:'TWD',taxRegime:'unregistered',taxId:'',evidenceRef:'synthetic-business'}},runs));const stale=await(await confirm(request({...next,expectedHeadHash:nextPreview.headHash}))).json();expect(stale.ok).toBe(false);expect(stale.errors[0]?.field).toBe('expectedHeadHash');
  expect((await confirm(request(input,'https://invalid.example'))).status).toBe(409);expect((await confirm(request({...input,unexpectedField:true}))).status).toBe(400);
  const {GET}=await import('../src/app/api/buy/records/route');const read=await(await GET(new Request('http://127.0.0.1:3000/api/buy/records'))).json();expect(read.inventory.openingRecorded).toBe(true);expect(read.procurement.counts).toHaveLength(1);
});
