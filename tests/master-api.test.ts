import { afterEach, expect, test, vi } from 'vitest';
import { randomUUID } from 'node:crypto';
import { workspace } from './helpers';
import { allowLocalRequest } from '../src/server/http';
const cleanups:(()=>Promise<unknown>)[]=[];
afterEach(async()=>{delete process.env.ERP_DATA_DIR;vi.resetModules();for(const cleanup of cleanups.splice(0))await cleanup();});
test('rewritten loopback requests use a validated incoming Host for origin checks',()=>{
  const request=(host:string,origin:string)=>new Request('http://localhost:3217/api/setup/record',{headers:{host,origin}});
  expect(()=>allowLocalRequest(request('127.0.0.1:3217','http://127.0.0.1:3217'))).not.toThrow();
  expect(()=>allowLocalRequest(request('invalid.example:3217','http://invalid.example:3217'))).toThrow();
  expect(()=>allowLocalRequest(request('127.0.0.1:3218','http://127.0.0.1:3218'))).toThrow();
  expect(()=>allowLocalRequest(request('127.0.0.1:3217','https://invalid.example'))).toThrow();
});
test('setup APIs preview zero writes, confirm once, reject cross-origin/bootstrap/unknown fields',async()=>{
  const {store,cleanup}=await workspace();cleanups.push(cleanup);process.env.ERP_DATA_DIR=store.directory;vi.resetModules();
  const {POST:preview}=await import('../src/app/api/setup/record/preview/route');const {POST:confirm}=await import('../src/app/api/setup/record/route');
  const input={action:'supplier',occurredOn:'2026-11-16',idempotencyKey:randomUUID(),previousRunId:null,record:{supplierRef:'SUP-800',legalName:'Synthetic API Supplier',country:'TW',currency:'TWD',defaultIncoterm:'EXW',paymentTerms:'Before production',canInvoiceToTaxId:'unknown',declarationRef:'',evidenceRef:'synthetic-api-evidence'}};
  const request=(body:unknown,origin='http://127.0.0.1:3000')=>new Request('http://127.0.0.1:3000/api/setup/record',{method:'POST',headers:{'content-type':'application/json',origin},body:JSON.stringify(body)});
  const proposed=await(await preview(request(input))).json();expect(proposed.ok).toBe(true);expect(proposed.runId).toBeNull();expect((await store.read()).length).toBe(0);
  const first=await(await confirm(request({...input,expectedHeadHash:proposed.headHash}))).json();const second=await(await confirm(request({...input,expectedHeadHash:proposed.headHash}))).json();expect(first.ok).toBe(true);expect(first.runId).toBe(second.runId);expect(second.duplicate).toBe(true);expect((await store.read()).length).toBe(1);
  expect((await confirm(request(input,'https://invalid.example'))).status).toBe(409);expect((await confirm(request({...input,buyerName:'synthetic-forbidden'}))).status).toBe(400);expect((await confirm(request({...input,action:'bootstrap'}))).status).toBe(400);
});
