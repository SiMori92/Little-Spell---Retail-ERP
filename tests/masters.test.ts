import { afterEach, expect, test } from 'vitest';
import { randomUUID } from 'node:crypto';
import { chmod, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { workspace } from './helpers';
import { planMasters, officialAccounts } from '../src/domain/masters';
import { projectMasters } from '../src/domain/master-projection';
import { canonical, digest } from '../src/domain/canonical';
import { parseCsv, serializeCsv } from '../src/domain/csv';
import { readMasterCsv, masterHeaders } from '../src/domain/master-csv';
import { exportMasters } from '../src/domain/master-export';
import { supplierSchema, productSchema } from '../src/domain/schemas/masters';
import { candidateSchema } from '../src/domain/schemas';
import { initializeWorkspace } from '../src/server/initialize';

const cleanups:(()=>Promise<unknown>)[]=[];
afterEach(async()=>{for(const cleanup of cleanups.splice(0))await cleanup();});
async function fresh(seed=false) {const context=await workspace();cleanups.push(context.cleanup);if(seed)await initializeWorkspace(context.store.directory);return context.store;}
const fields=()=>({occurredOn:'2026-11-16',idempotencyKey:randomUUID()});
const supplier=()=>supplierSchema.parse({supplierRef:'SUP-900',legalName:'Synthetic Test Supplier',country:'TW',currency:'TWD',defaultIncoterm:'EXW',paymentTerms:'Before production',canInvoiceToTaxId:'unknown',declarationRef:'',evidenceRef:'synthetic-supplier-evidence'});
const product=()=>productSchema.parse({sku:'TS-QA-900-S',name:'Synthetic Test Product',uom:'PC',piecesPerSaleUnit:5,supplierRef:'SUP-900',ingredientRef:'UNKNOWN',productType:'sellable',evidenceRef:'synthetic-product-evidence'});

test('supplier changes append a linked version with exact audit values; identity cannot change',async()=>{
  const store=await fresh();const original=await store.execute(runs=>planMasters({action:'supplier',...fields(),previousRunId:null,record:supplier()},runs));
  const filename=join(store.directory,'runs',original.run.createdAt.slice(0,4),original.run.createdAt.slice(5,7),`${original.run.runId}.json`);const before=await readFile(filename,'utf8');
  await store.execute(runs=>planMasters({action:'supplier',...fields(),previousRunId:original.run.runId,record:{...supplier(),paymentTerms:'Net 30',canInvoiceToTaxId:'yes',evidenceRef:'synthetic-new-evidence'}},runs));
  const projected=projectMasters(await store.read());expect(projected.suppliers.length).toBe(1);expect(projected.history.length).toBe(2);expect(projected.history[1]?.changes.length).toBe(2);expect(await readFile(filename,'utf8')===before).toBe(true);
  await expect(store.execute(runs=>planMasters({action:'supplier',...fields(),previousRunId:projected.suppliers[0]!.runId,record:{...projected.suppliers[0]!.record,legalName:'Different identity'}},runs))).rejects.toThrow(/identity/);
  await expect(store.execute(runs=>planMasters({action:'supplier',...fields(),previousRunId:original.run.runId,record:{...supplier(),paymentTerms:'Stale correction'}},runs))).rejects.toThrow(/changed/);
});
test('products keep PC, strict SKU/type/ingredient semantics, and immutable sale conversion',async()=>{
  const store=await fresh();await store.execute(runs=>planMasters({action:'supplier',...fields(),previousRunId:null,record:supplier()},runs));
  const original=await store.execute(runs=>planMasters({action:'product',...fields(),previousRunId:null,record:product()},runs));
  expect(productSchema.safeParse({...product(),uom:'PK'}).success).toBe(false);expect(productSchema.safeParse({...product(),piecesPerSaleUnit:1.5}).success).toBe(false);
  expect(productSchema.safeParse({...product(),ingredientRef:'NOT_APPLICABLE'}).success).toBe(false);
  expect(productSchema.safeParse({...product(),sku:'PKG-BOX-TW',productType:'packaging',ingredientRef:'NOT_APPLICABLE'}).success).toBe(true);
  await expect(store.execute(runs=>planMasters({action:'product',...fields(),previousRunId:original.run.runId,record:{...product(),piecesPerSaleUnit:10}},runs))).rejects.toThrow(/conversion/);
  await expect(store.execute(runs=>planMasters({action:'product',...fields(),previousRunId:original.run.runId,record:{...product(),ingredientRef:'compliance/suppliers/qa-ink'}},runs))).rejects.toThrow(/declaration/);
});
test('a product compliance revision needs supplier evidence and keeps the original version',async()=>{
  const store=await fresh();const first=await store.execute(runs=>planMasters({action:'supplier',...fields(),previousRunId:null,record:supplier()},runs));
  await store.execute(runs=>planMasters({action:'supplier',...fields(),previousRunId:first.run.runId,record:{...supplier(),declarationRef:'compliance/suppliers/qa-declaration'}},runs));
  const original=await store.execute(runs=>planMasters({action:'product',...fields(),previousRunId:null,record:product()},runs));
  await store.execute(runs=>planMasters({action:'product',...fields(),previousRunId:original.run.runId,record:{...product(),ingredientRef:'compliance/suppliers/qa-ink',evidenceRef:'synthetic-ink-evidence'}},runs));
  const projection=projectMasters(await store.read());const change=projection.history.at(-1)?.changes[0];expect(change?.field).toBe('ingredientRef');expect(change?.old).toBe('UNKNOWN');expect(change?.new).toBe('compliance/suppliers/qa-ink');
});
test('CSV parser handles BOM, quoted commas, embedded newlines, escaped quotes, and rejects broken quotes',()=>{
  const rows=parseCsv('\uFEFFfirst,second\r\n"quoted, value","line one\nline ""two"""\r\n');expect(rows.length).toBe(2);expect(rows[1]?.length).toBe(2);expect(rows[1]?.[1]).toBe('line one\nline "two"');
  expect(()=>parseCsv('first,second\n"never closed')).toThrow(/quotation/);expect(()=>parseCsv('first,second\n"closed"bad,cell')).toThrow(/unexpected/);
  expect(serializeCsv([['=synthetic-formula','plain']]).startsWith("'=synthetic-formula")).toBe(true);
});
test('supplier/product header versions and filename provenance are enforced before any write',async()=>{
  const store=await fresh();const text=await readFile('seed/samples/SAMPLE_products_2026-09-27.csv','utf8');
  await expect(store.execute(runs=>planMasters({action:'import',...fields(),area:'products',filename:'products_2026-09-27.csv',csvText:text},runs))).rejects.toThrow(/SAMPLE/);
  expect(()=>readMasterCsv('products','SAMPLE_products_2026-09-27.csv',text.replace('pieces_per_sale_unit','pack_qty'),'SAMPLE')).toThrow(/v3/);
  expect(()=>readMasterCsv('products','SAMPLE_products_2026-09-27.csv',text.replace(',product_type',''),'SAMPLE')).toThrow(/v3/);
  expect(()=>readMasterCsv('products','SAMPLE_products_2026-02-30.csv',text,'SAMPLE')).toThrow(/YYYY/);expect((await store.read()).length).toBe(0);
});
test('SAMPLE bootstrap is atomic and idempotent; every master CSV re-import creates zero new runs',async()=>{
  const store=await fresh(true);const initial=await store.read();expect(initial.length).toBe(3);const projected=projectMasters(initial);
  expect(projected.suppliers.length).toBe(3);expect(projected.products.length>0).toBe(true);expect(projected.accounts.length).toBe(74);expect(projected.channels.length).toBe(2);
  await initializeWorkspace(store.directory);expect((await store.read()).length).toBe(3);
  for(const area of ['suppliers','products','channels','accounts'] as const){
    const input={action:'import',...fields(),area,filename:`SAMPLE_${area}_2026-11-16.csv`,csvText:exportMasters(area,projected)};
    await store.execute(runs=>planMasters(input,runs));const count=(await store.read()).length;
    const repeated=await store.execute(runs=>planMasters({...input,occurredOn:'2026-11-17',idempotencyKey:randomUUID()},runs));expect(repeated.duplicate).toBe(true);expect((await store.read()).length).toBe(count);
  }
});
test('supplier snapshots cannot delete missing records; duplicate and unknown FK rows roll back the entire run',async()=>{
  const store=await fresh(true);const projection=projectMasters(await store.read());const one=exportMasters('suppliers',projection,new Set(['SUP-001']));const before=(await store.read()).length;
  await expect(store.execute(runs=>planMasters({action:'import',...fields(),area:'suppliers',filename:'SAMPLE_suppliers_2026-11-16.csv',csvText:one},runs))).rejects.toThrow(/every existing/);
  const rows=parseCsv(exportMasters('products',projection));const duplicate=serializeCsv([rows[0]!,rows[1]!,rows[1]!]);
  await expect(store.execute(runs=>planMasters({action:'import',...fields(),area:'products',filename:'SAMPLE_products_2026-11-16.csv',csvText:duplicate},runs))).rejects.toThrow(/repeats/);
  await expect(store.execute(runs=>planMasters({action:'product',...fields(),previousRunId:null,record:product()},runs))).rejects.toThrow(/supplier/);expect((await store.read()).length).toBe(before);
});
test('the bilingual chart is frozen and channel names match their identifiers',async()=>{
  const store=await fresh();await store.execute(runs=>planMasters({action:'reference',...fields()},runs));const projection=projectMasters(await store.read());
  expect(projection.accounts[0]?.record.nameZh).toBeTruthy();expect(officialAccounts.length).toBe(74);
  const csv=exportMasters('accounts',projection).replace('Petty cash','Rounding');
  await expect(store.execute(runs=>planMasters({action:'import',...fields(),area:'accounts',filename:'SAMPLE_accounts_2026-11-16.csv',csvText:csv},runs))).rejects.toThrow(/frozen/);
  await expect(store.execute(runs=>planMasters({action:'channel',...fields(),record:{code:'etsy',name:'Instagram'}},runs))).rejects.toThrow();
});
test('CSV PII refusal does not echo values, including in no-op evidence columns',async()=>{
  const store=await fresh(true);const projection=projectMasters(await store.read());const privateValue=['synthetic-buyer','invalid.example'].join('@');const csv=exportMasters('suppliers',projection).replace('sample supplier master 2026-09-27',privateValue);let safe=false;
  try{await store.execute(runs=>planMasters({action:'import',...fields(),area:'suppliers',filename:'SAMPLE_suppliers_2026-11-16.csv',csvText:csv},runs));}catch(error){safe=error instanceof Error&&!error.message.includes(privateValue);}expect(safe).toBe(true);expect((await store.read()).length).toBe(3);
});
test('expected-head preview protection and exact-effect replay reject stale or forged effects',async()=>{
  const store=await fresh();const input={action:'supplier',...fields(),previousRunId:null,record:supplier()};const preview=await store.execute(runs=>planMasters(input,runs),true);
  await store.execute(runs=>planMasters({action:'reference',...fields()},runs));
  await expect(store.execute(runs=>planMasters({...input,expectedHeadHash:preview.run.prevHash},runs))).rejects.toThrow(/Preview again/);
  const good=planMasters(input,await store.read());const effect=good.effects[0];if(effect?.type!=='supplier.recorded')throw new Error('fixture');effect.record.paymentTerms='Forged effect';await expect(store.execute(()=>good)).rejects.toThrow(/effects/);
});
test('recomputed hash alone cannot legitimise a forged master record',async()=>{
  const store=await fresh();const {run}=await store.execute(runs=>planMasters({action:'supplier',...fields(),previousRunId:null,record:supplier()},runs));
  const effect=run.effects[0];if(effect?.type!=='supplier.recorded')throw new Error('fixture');effect.record.paymentTerms='Forged effect';const {hash,...body}=run;void hash;
  const filename=join(store.directory,'runs',run.createdAt.slice(0,4),run.createdAt.slice(5,7),`${run.runId}.json`);await chmod(filename,0o600);await writeFile(filename,canonical({...body,hash:digest(body)}));expect((await store.status()).readOnly).toBe(true);
});
test('opening preparation is exact, evidenced, confirmed, and never a posted stock/journal event',async()=>{
  const store=await fresh(true);await store.execute(runs=>planMasters({action:'business',...fields(),previousRunId:null,record:{tradingName:'Synthetic Business',country:'TW',functionalCurrency:'TWD',taxRegime:'unregistered',taxId:'',evidenceRef:'synthetic-business'}},runs));
  const input={action:'opening',...fields(),previousRunId:null,record:{mode:'prepare',countedOn:'2026-11-16',lines:[{sku:'TS-FL-001-S',condition:'sellable',qtyPieces:'7',agreedUnitCostTwd:'0.1234',evidenceRef:'synthetic-line'}],evidenceRef:'synthetic-count',founderConfirmed:true}};
  await expect(store.execute(runs=>planMasters({...input,record:{...input.record,founderConfirmed:false}},runs))).rejects.toThrow();
  const result=await store.execute(runs=>planMasters(input,runs));const effect=result.run.effects[0];expect(effect?.type).toBe('opening.prepared');if(effect?.type==='opening.prepared')expect(effect.totalPreparedValueTwd).toBe('0.8638');expect(result.run.effects.some(item=>item.type==='journal.posted'||item.type==='stock.moved')).toBe(false);
  const projection=projectMasters(await store.read(),'ACTUAL');expect(projection.products.length).toBe(0);expect(projection.opening).toBeNull();
});
test('closed months reject master changes and unverified contracts never import',async()=>{
  const store=await fresh();await store.execute(()=>candidateSchema.parse({kind:'period.close',dataset:'SAMPLE',occurredOn:'2026-11-30',input:{},idempotencyKey:'close-master-month',effects:[{type:'period.closed',period:'2026-11',founderAuthorization:'synthetic-founder',gates:['G-1','G-2','G-3','G-4','G-5'].map(gate=>({gate,status:'PASS',evidenceRef:'synthetic-check'}))}]}));
  await expect(store.execute(runs=>planMasters({action:'supplier',...fields(),previousRunId:null,record:supplier()},runs))).rejects.toThrow(/closed/);
  const before=masterHeaders.suppliers.verified;masterHeaders.suppliers.verified=false;
  try{expect(()=>readMasterCsv('suppliers','SAMPLE_suppliers_2026-11-16.csv','supplier_ref\nSUP-001','SAMPLE')).toThrow(/verified/);}finally{masterHeaders.suppliers.verified=before;}
});
