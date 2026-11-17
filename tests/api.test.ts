import { afterEach, expect, test, vi } from 'vitest';
import { join } from 'node:path';
import { chmod, writeFile } from 'node:fs/promises';
import { workspace, journalCandidate } from './helpers';
import { canonical } from '../src/domain/canonical';
const cleanups:(()=>Promise<unknown>)[]=[];
afterEach(async()=>{delete process.env.ERP_DATA_DIR;vi.resetModules();for(const cleanup of cleanups.splice(0))await cleanup();});
async function context(){const context=await workspace();cleanups.push(context.cleanup);process.env.ERP_DATA_DIR=context.store.directory;vi.resetModules();return context.store;}
function request(path:string,input:unknown,origin='http://127.0.0.1:3000'){return new Request(`http://127.0.0.1:3000/api/history/reverse${path}`,{method:'POST',headers:{'content-type':'application/json',origin},body:JSON.stringify(input)});}
test('API validates form, previews zero writes, books reversal once, rejects cross-origin',async()=>{
  const store=await context();const original=await store.execute(()=>journalCandidate());
  const {POST:preview}=await import('../src/app/api/history/reverse/preview/route');const {POST:confirm}=await import('../src/app/api/history/reverse/route');
  const input={originalRunId:original.run.runId,occurredOn:'2026-11-16',reason:'Correct synthetic evidence',idempotencyKey:'api-correction'};
  expect((await preview(request('/preview',input))).status).toBe(200);expect((await store.read()).length).toBe(1);
  const first=await(await confirm(request('',input))).json();const second=await(await confirm(request('',input))).json();
  expect(first.ok).toBe(true);expect(first.runId).toBe(second.runId);expect(second.duplicate).toBe(true);expect((await store.read()).length).toBe(2);
  expect((await confirm(request('',{},'https://invalid.example'))).status).toBe(409);
  expect((await confirm(request('',{}))).status).toBe(400);
});
test('API integrity errors reveal only the bad identifier, never input data',async()=>{
  const store=await context();const {run}=await store.execute(()=>journalCandidate());const filename=join(store.directory,'runs',run.createdAt.slice(0,4),run.createdAt.slice(5,7),`${run.runId}.json`);
  const privateMarker=['PRIVATE','DO','NOT','ECHO'].join('_');await chmod(filename,0o600);await writeFile(filename,canonical({...run,input:{buyerName:privateMarker}}));
  const {POST}=await import('../src/app/api/history/reverse/route');const response=await POST(request('',{originalRunId:run.runId,occurredOn:'2026-11-16',reason:'Synthetic correction',idempotencyKey:'integrity-check'}));
  const text=await response.text();expect(response.status).toBe(409);expect(text.includes(run.runId)).toBe(true);expect(text.includes(privateMarker)).toBe(false);
});
