import { afterEach,expect,test,vi } from 'vitest';
import { randomUUID } from 'node:crypto';
import { workspace } from './helpers';
import { initializeWorkspace } from '../src/server/initialize';
const cleanups:(()=>Promise<unknown>)[]=[];
afterEach(async()=>{delete process.env.ERP_DATA_DIR;vi.resetModules();for(const cleanup of cleanups.splice(0))await cleanup();});
const request=(body:unknown,origin='http://127.0.0.1:3000')=>new Request('http://127.0.0.1:3000/api/money/record',{method:'POST',headers:{'Content-Type':'application/json',origin},body:JSON.stringify(body)});
test('money API validates, previews without writing, posts separately, retries once and refuses stale confirmation',async()=>{
 const c=await workspace();cleanups.push(c.cleanup);await initializeWorkspace(c.store.directory);process.env.ERP_DATA_DIR=c.store.directory;vi.resetModules();const {POST:preview}=await import('../src/app/api/money/record/preview/route'),{POST:confirm}=await import('../src/app/api/money/record/route');
 const input={action:'manual',occurredOn:'2026-10-02',idempotencyKey:randomUUID(),record:{eventType:'owner.funds_moved',amount:'100.0000',fundsType:'capital'},evidenceRef:'synthetic-api-owner-funding'};
 const count=(await c.store.read()).length,p=await(await preview(request(input))).json();expect(p.ok).toBe(true);expect((await c.store.read()).length).toBe(count);
 const payload={...input,expectedHeadHash:p.headHash};const first=await(await confirm(request(payload))).json(),retry=await(await confirm(request(payload))).json();expect(first.ok).toBe(true);expect(retry.runId).toBe(first.runId);expect(retry.duplicate).toBe(true);
 expect((await confirm(request({...input,idempotencyKey:randomUUID(),evidenceRef:'synthetic-api-next',expectedHeadHash:p.headHash}))).status).toBe(409);expect((await confirm(request(input,'https://invalid.example'))).status).toBe(409);expect((await confirm(request({...input,record:{...input.record,amount:''}}))).status).toBe(400);
 const f=first.effects.find((e:{type:string})=>e.type==='accounting.fact').record,post={action:'post',occurredOn:f.date,eventId:f.id,idempotencyKey:randomUUID()};const pp=await(await preview(request(post))).json();expect(pp.effects.some((e:{type:string})=>e.type==='journal.posted')).toBe(true);expect((await c.store.read()).length).toBe(count+1);expect((await(await confirm(request({...post,expectedHeadHash:pp.headHash}))).json()).ok).toBe(true);
});
test('close API saves a blocked attempt and reports API validates period and returns sourced gate diagnostics',async()=>{
 const c=await workspace();cleanups.push(c.cleanup);await initializeWorkspace(c.store.directory);process.env.ERP_DATA_DIR=c.store.directory;vi.resetModules();const {POST:preview}=await import('../src/app/api/close/record/preview/route'),{POST:confirm}=await import('../src/app/api/close/record/route'),{GET:reports}=await import('../src/app/api/reports/records/route');
 const input={action:'close',period:'2026-10',occurredOn:'2026-11-17',actor:'Synthetic founder',evidenceRef:'synthetic-api-close-evidence',founderAuthorization:'synthetic-api-authorization',idempotencyKey:randomUUID()};const count=(await c.store.read()).length,p=await(await preview(request(input))).json();expect(p.effects[0].status).toBe('BLOCKED');expect((await c.store.read()).length).toBe(count);const final=await(await confirm(request({...input,expectedHeadHash:p.headHash}))).json();expect(final.ok).toBe(true);expect(final.effects.some((e:{type:string})=>e.type==='period.closed')).toBe(false);
 const valid=await(await reports(new Request('http://127.0.0.1:3000/api/reports/records?period=2026-10'))).json();expect(valid.reports.length).toBe(18);expect(valid.gates.find((g:{gate:string})=>g.gate==='G-2').status).toBe('NOT_RUNNABLE');expect((await reports(new Request('http://127.0.0.1:3000/api/reports/records?period=2026-99'))).status).toBe(400);
});
