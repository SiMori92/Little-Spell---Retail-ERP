import { afterEach,expect,test } from 'vitest';
import { randomUUID } from 'node:crypto';
import { readFile,writeFile,chmod } from 'node:fs/promises';
import { basename,join } from 'node:path';
import { workspace,journalCandidate } from './helpers';
import type { RunStore } from '../src/server/store';
import { initializeWorkspace } from '../src/server/initialize';
import { planMasters } from '../src/domain/masters';
import { projectMasters } from '../src/domain/master-projection';
import { planProcurement } from '../src/domain/procurement';
import { projectProcurement } from '../src/domain/procurement-projection';
import { projectInventory } from '../src/domain/inventory-projection';
import { allocateCharge,proRataDeposit,valueReceipt } from '../src/domain/landed-cost';
import { purchaseOrderSchema,receiptSchema,supplierPaymentSchema,landedInputSchema,procurementPayloadSchema } from '../src/domain/schemas/procurement';
import { candidateSchema } from '../src/domain/schemas';
import { canonical,digest } from '../src/domain/canonical';
import { headerHashes } from '../src/domain/selling-csv';
import { planSelling } from '../src/domain/selling';

const cleanups:(()=>Promise<unknown>)[]=[];
afterEach(async()=>{for(const cleanup of cleanups.splice(0))await cleanup();});
const fields=()=>({occurredOn:'2026-11-16',idempotencyKey:randomUUID(),expectedHeadHash:null});
async function fresh(g3=true){const context=await workspace();cleanups.push(context.cleanup);if(!g3)await initializeWorkspace(context.store.directory);else for(const area of ['suppliers','products']){const csvText=await readFile(`seed/samples/g3/SAMPLE_${area}_2026-09-27.csv`,'utf8');await context.store.execute(runs=>planMasters({action:'import',...fields(),area,filename:`SAMPLE_${area}_2026-09-27.csv`,csvText},runs));}return context.store;}
async function importFile(store:RunStore,path:string,area:'po'|'grn'|'inv'|'pay'|'counts'){
  const input={action:'import',...fields(),area,filename:basename(path),csvText:await readFile(path,'utf8'),founderConfirmed:true};return store.execute(runs=>planProcurement(input,runs));
}
const g3=(name:string)=>`seed/samples/g3/SAMPLE_${name}.csv`;
async function count(store:RunStore,date='2026-01-01',qty='0',cost='0.0000',evidence:string=randomUUID()){
  const masters=projectMasters(await store.read());return store.execute(runs=>planProcurement({action:'count',...fields(),founderConfirmed:true,record:{countedAt:date,evidenceRef:evidence,lines:masters.products.map(({record})=>({sku:record.sku,qtyPieces:record.productType==='packaging'?'0':qty,agreedUnitCostTwd:record.productType==='packaging'?'0.0000':cost,condition:'sellable'}))}},runs));
}

test('landed cost allocates by value, splits damage from full landed cost, and ties the packaging fixture',()=>{
  const lines=[landedInputSchema.parse({lineNo:1,sku:'PKG-MAIL-LS',inventoryAccount:'1233',qtyGood:'15000',qtyDamaged:'0',lineAmount:'100000.0000',setup:'2500.0000',statedTax:null}),landedInputSchema.parse({lineNo:2,sku:'PKG-CARD-LS',inventoryAccount:'1233',qtyGood:'19800',qtyDamaged:'200',lineAmount:'37000.0000',setup:'1000.0000',statedTax:null})];
  const result=valueReceipt(lines,'0.0000','6850.0000','0.0000');expect(result[0]?.goodValue).toBe('105000.0000');expect(result[1]?.landed).toBe('38850.0000');expect(result[1]?.damagedValue).toBe('388.5000');expect(result[1]?.goodValue).toBe('38461.5000');
});
test('allocation remainder goes to highest line and stated tax takes precedence',()=>{
  const shares=allocateCharge('0.0001',[{lineNo:7,value:'1.0000'},{lineNo:2,value:'1.0000'},{lineNo:4,value:'1.0000'}]);expect(shares.get(7)).toBe('0.0001');expect(shares.get(2)).toBe('0.0000');
  const rows=[1,2].map(lineNo=>landedInputSchema.parse({lineNo,sku:`SKU-${lineNo}`,inventoryAccount:'1231',qtyGood:'1',qtyDamaged:'0',lineAmount:'10.0000',setup:'0.0000',statedTax:lineNo===1?'0.0000':'2.0000'}));expect(valueReceipt(rows,'0.0000','2.0000','0.0000')[1]?.taxShare).toBe('2.0000');expect(()=>valueReceipt([{...rows[0]!,statedTax:null},rows[1]!],'0','2','0')).toThrow(/every line/);
});
test('deposit pro-rata uses exact completion remainder without plugging',()=>{expect(proRataDeposit('1.0000','1.0000','3.0000','0.0000',false)).toBe('0.3333');expect(proRataDeposit('1.0000','1.0000','3.0000','0.6666',true)).toBe('0.3334');});
test('the complete two-receipt deposit/invoice/payment fixture closes with zero deposits and payable',async()=>{
  const store=await fresh();for(const [file,area] of [['po_PO-2026-002','po'],['pay_DEP-002','pay'],['grn_PO-2026-002_R1','grn'],['inv_INV-A','inv'],['grn_PO-2026-002_R2','grn'],['inv_INV-B','inv'],['pay_BAL-A','pay'],['pay_BAL-B','pay']] as const)await importFile(store,g3(file),area);
  const projection=projectProcurement(await store.read());expect(projection.orders[0]?.status).toBe('closed');expect(projection.orders[0]?.openDepositTwd).toBe('0.0000');expect(projection.totalPayablesTwd).toBe('0.0000');expect(projection.matches.map(match=>match.depositAppliedTwd)).toEqual(['17400.0000','21300.0000']);
  const inventory=projectInventory(await store.read());expect(inventory.positions.find(item=>item.sku==='TS-MT-005-S')?.valueTwd).toBe('60900.0000');expect(inventory.positions.find(item=>item.sku==='TS-FS-004-P')?.valueTwd).toBe('74550.0000');expect((await store.read()).flatMap(run=>run.effects).filter(effect=>effect.type==='journal.posted')).toHaveLength(5);
});
test('every G3 fixture re-import writes zero runs after the lifecycle has advanced',async()=>{
  const store=await fresh();const inputs=[['po_PO-2026-002','po'],['pay_DEP-002','pay'],['grn_PO-2026-002_R1','grn'],['inv_INV-A','inv'],['grn_PO-2026-002_R2','grn'],['inv_INV-B','inv'],['pay_BAL-A','pay'],['pay_BAL-B','pay']] as const;for(const [file,area]of inputs)await importFile(store,g3(file),area);const before=(await store.read()).length;for(const [file,area]of inputs)expect((await importFile(store,g3(file),area)).duplicate).toBe(true);expect((await store.read()).length).toBe(before);
});
test('invoice-first and receipt-first both match once; unmatched facts create neither stock nor journals',async()=>{
  const store=await fresh();await importFile(store,g3('po_PO-2026-002'),'po');const invoice=await importFile(store,g3('inv_INV-A'),'inv');expect(invoice.run.effects.some(effect=>effect.type==='journal.posted')).toBe(false);expect(projectProcurement(await store.read()).exceptions).toHaveLength(1);
  const result=await importFile(store,g3('grn_PO-2026-002_R1'),'grn');expect(result.run.effects.filter(effect=>effect.type==='journal.posted')).toHaveLength(1);expect(projectProcurement(await store.read()).invoices[0]?.matched).toBe(true);expect(projectInventory(await store.read()).positions.find(item=>item.sku==='TS-MT-005-S')?.qtyPieces).toBe('3000');
});
test('mismatched accepted/invoiced pieces remain visible and unposted',async()=>{
  const store=await fresh();await importFile(store,g3('po_PO-2026-002'),'po');await importFile(store,g3('grn_PO-2026-002_R1'),'grn');const csvText=(await readFile(g3('inv_INV-A'),'utf8')).replace(',3000,18.0000,4000.0000,58000.0000,',',2999,18.0000,4000.0000,57982.0000,').replace(',60900.0000,',',60882.0000,');
  await store.execute(runs=>planProcurement({action:'import',...fields(),area:'inv',filename:'SAMPLE_inv_INV-A.csv',csvText},runs));const state=projectProcurement(await store.read());expect(state.invoices[0]?.matched).toBe(false);expect(state.exceptions.length).toBeGreaterThan(0);expect(state.totalPayablesTwd).toBe('0.0000');expect(projectInventory(await store.read()).totalValueTwd).toBe('0.0000');
});
test('sent POs freeze commercial lines, omitted lines are not deletions, and compliance blocks unknown evidence',async()=>{
  const store=await fresh();const result=await importFile(store,g3('po_PO-2026-002'),'po');const prior=projectProcurement(await store.read()).orders[0]!;
  await expect(store.execute(runs=>planProcurement({action:'po',...fields(),previousRunId:result.run.runId,record:{...prior.record,lines:prior.record.lines.slice(0,1)}},runs))).rejects.toThrow(/Omitting/);
  await expect(store.execute(runs=>planProcurement({action:'po',...fields(),previousRunId:result.run.runId,record:{...prior.record,quoteRef:'changed-quote'}},runs))).rejects.toThrow(/freeze/);
  const defaultStore=await fresh(false);const record=purchaseOrderSchema.parse({...prior.record,poNumber:'PO-2026-900',supplierRef:'SUP-001',lines:[{...prior.record.lines[0],lineNo:1,sku:'TS-FL-001-S'}]});await expect(defaultStore.execute(runs=>planProcurement({action:'po',...fields(),previousRunId:null,record},runs))).rejects.toThrow(/evidence/);
});
test('a partial line must short-close with evidence and cannot be delivered twice',async()=>{
  const store=await fresh();await importFile(store,g3('po_PO-2026-002'),'po');const record=receiptSchema.parse({poNumber:'PO-2026-002',receiptNo:'SHORT',receivedOn:'2026-01-20',lines:[{lineNo:1,sku:'TS-MT-005-S',qtyGood:'2000',qtyDamaged:'0',damagedCredited:false,shortClose:false,shortCloseReason:'',evidenceRef:'synthetic-short'}]});
  await expect(store.execute(runs=>planProcurement({action:'receipt',...fields(),record},runs))).rejects.toThrow(/short delivery/);await store.execute(runs=>planProcurement({action:'receipt',...fields(),record:{...record,lines:[{...record.lines[0]!,shortClose:true,shortCloseReason:'Supplier cannot deliver remainder'}]}},runs));await expect(importFile(store,g3('grn_PO-2026-002_R1'),'grn')).rejects.toThrow(/one delivery/);
});
test('deposits after receipt, cumulative excess, premature balances, and overpayment are refused',async()=>{
  const store=await fresh();await importFile(store,g3('po_PO-2026-002'),'po');const pay=supplierPaymentSchema.parse({paymentRef:'TEST-DEP',paidOn:'2026-01-13',supplierRef:'SUP-002',poNumber:'PO-2026-002',invoiceNo:'',paymentKind:'deposit',amountTwd:'129001.0000',bankAccount:'1121',bankRef:'synthetic-bank',evidenceRef:'synthetic-payment'});
  await expect(store.execute(runs=>planProcurement({action:'payment',...fields(),record:pay},runs))).rejects.toThrow(/Cumulative/);await expect(importFile(store,g3('pay_BAL-A'),'pay')).rejects.toThrow(/matched and posted/);
  await importFile(store,g3('grn_PO-2026-002_R1'),'grn');await expect(importFile(store,g3('pay_DEP-002'),'pay')).rejects.toThrow(/before any goods receipt/);await importFile(store,g3('inv_INV-A'),'inv');await expect(store.execute(runs=>planProcurement({action:'payment',...fields(),record:{...pay,paymentRef:'EXCESS-BAL',paymentKind:'balance',invoiceNo:'INV-A',paidOn:'2026-01-26',amountTwd:'60900.0001'}},runs))).rejects.toThrow(/overpay/);
});
test('cancelled supplier deposits refund or forfeit through the specified accounts without deleting history',async()=>{
  const store=await fresh();await importFile(store,g3('po_PO-2026-002'),'po');await importFile(store,g3('pay_DEP-002'),'pay');const prior=projectProcurement(await store.read()).orders[0]!;await store.execute(runs=>planProcurement({action:'po',...fields(),previousRunId:prior.runId,record:{...prior.record,status:'cancelled'}},runs));
  const record=supplierPaymentSchema.parse({paymentRef:'FORFEIT-TEST',paidOn:'2026-11-16',supplierRef:'SUP-002',poNumber:'PO-2026-002',invoiceNo:'',paymentKind:'deposit_forfeit',amountTwd:'38700.0000',bankAccount:'1121',bankRef:'',evidenceRef:'synthetic-forfeiture'});const result=await store.execute(runs=>planProcurement({action:'payment',...fields(),record},runs));const journal=result.run.effects.find(effect=>effect.type==='journal.posted');if(journal?.type!=='journal.posted')throw Error('fixture');expect(journal.entry.lines.map(line=>line.account.code)).toEqual(['6199','1266']);expect(projectProcurement(await store.read()).orders[0]?.openDepositTwd).toBe('0.0000');
});
test('GUI/tax regime, non-TWD sources, carrier columns, filename and header gates refuse atomically',async()=>{
  const store=await fresh();await importFile(store,g3('po_PO-2026-002'),'po');const csv=await readFile(g3('inv_INV-A'),'utf8');const before=(await store.read()).length;
  await expect(store.execute(runs=>planProcurement({action:'import',...fields(),area:'inv',filename:'SAMPLE_inv_INV-A.csv',csvText:csv.replace('INV-A,,','INV-A,AB12345678,').replace(',2900.0000,0.0000,',',2900.0000,290.0000,')},runs))).rejects.toThrow(/tax regime/);
  for(const patch of [{filename:'inv_INV-A.csv'},{csvText:csv.replace('freight_twd','carrier_freight_twd')},{csvText:csv.replace('invoice_no,','wrong_header,')}])await expect(store.execute(runs=>planProcurement({action:'import',...fields(),area:'inv',filename:'SAMPLE_inv_INV-A.csv',csvText:csv,...patch},runs))).rejects.toThrow();expect((await store.read()).length).toBe(before);
});
test('complete explicit opening count books balanced capital/inventory once; damage is a memo',async()=>{
  const store=await fresh();const first=await count(store,'2026-01-01','3','2.0000','synthetic-opening');expect(first.run.effects.filter(effect=>effect.type==='journal.posted')).toHaveLength(1);expect(projectInventory(await store.read()).totalValueTwd).toBe('12.0000');
  const changed=procurementPayloadSchema.parse(first.run.input);if(changed.action!=='count')throw Error('fixture');await expect(store.execute(runs=>planProcurement({...changed,idempotencyKey:randomUUID(),record:{...changed.record,lines:changed.record.lines.slice(0,1)}},runs))).rejects.toThrow(/already booked/);
  await expect(store.execute(runs=>planProcurement({...changed,idempotencyKey:randomUUID(),record:{...changed.record,evidenceRef:'new-adjustment',lines:changed.record.lines.map(line=>({...line,qtyPieces:'4'}))}},runs))).rejects.toThrow(/cannot add/);
});
test('count decreases use exact WAC rather than entered unit cost and finish at exact zero',async()=>{
  const store=await fresh();await count(store,'2026-01-01','3','0.3333');await count(store,'2026-01-02','2','900.0000');const state=projectInventory(await store.read());expect(state.positions.every(item=>item.valueTwd==='0.6666')).toBe(true);await count(store,'2026-01-03','0','0.0000');expect(projectInventory(await store.read()).totalValueTwd).toBe('0.0000');
});
test('opening and damaged count validation requires all active SKUs and explicit founder confirmation',async()=>{
  const store=await fresh();const input={action:'count',...fields(),founderConfirmed:false,record:{countedAt:'2026-01-01',evidenceRef:'synthetic-count',lines:[{sku:'TS-MT-005-S',qtyPieces:'1',agreedUnitCostTwd:'2.0000',condition:'sellable'}]}};await expect(store.execute(runs=>planProcurement(input,runs))).rejects.toThrow();await expect(store.execute(runs=>planProcurement({...input,founderConfirmed:true},runs))).rejects.toThrow(/every active product/);
});
test('M2 dispatch is consumed once in WAC and retains pending COGS without a journal',async()=>{
  const store=await fresh(false);await count(store,'2025-12-01','100','2.0000');await store.execute(runs=>planSelling({action:'verify-etsy',...fields(),...headerHashes,evidenceRef:'synthetic-review',founderConfirmed:true},runs));
  const input={action:'etsy',...fields(),orderFilename:'SAMPLE_etsy_orderitems_2025-12_fixture.csv',statementFilename:'SAMPLE_etsy_statement_2025-12_fixture.csv',ordersCsv:await readFile('seed/fixtures/SAMPLE_etsy_orderitems_2025-12_fixture.csv','utf8'),statementCsv:await readFile('seed/fixtures/SAMPLE_etsy_statement_2025-12_fixture.csv','utf8'),couponRules:['WELCOME10','HOLIDAY15','FREESHIP'].map(code=>({code,fundedBy:'seller',validFrom:null,validTo:null,evidenceRef:'synthetic-coupon'}))};await store.execute(runs=>planSelling(input,runs));const inventory=projectInventory(await store.read());expect(inventory.positions.find(item=>item.sku==='TS-FL-001-S')?.qtyPieces).toBe('95');expect(inventory.positions.find(item=>item.sku==='TS-FL-001-S')?.valueTwd).toBe('190.0000');expect(inventory.consumptions.length).toBe(5);expect(inventory.pendingCogsTwd).toBe('26.0000');
});
test('forged effects and rehashed tampering are refused',async()=>{
  const store=await fresh();const original=await importFile(store,g3('po_PO-2026-002'),'po');const candidate=planProcurement({...fields(),action:'po',previousRunId:original.run.runId,record:{...projectProcurement(await store.read()).orders[0]!.record,status:'acknowledged'}},await store.read());const effect=candidate.effects.find(item=>item.type==='procurement.po');if(effect?.type!=='procurement.po')throw Error('fixture');effect.record.paymentTerms='forged-terms';await expect(store.execute(()=>candidate)).rejects.toThrow(/effects/);
  const pay=await importFile(store,g3('pay_DEP-002'),'pay');const changed=pay.run.effects.find(item=>item.type==='procurement.payment');if(changed?.type!=='procurement.payment')throw Error('fixture');changed.record.evidenceRef='forged-evidence';const {hash,...body}=pay.run;void hash;const filename=join(store.directory,'runs',pay.run.createdAt.slice(0,4),pay.run.createdAt.slice(5,7),`${pay.run.runId}.json`);await chmod(filename,0o600);await writeFile(filename,canonical({...body,hash:digest(body)}));expect((await store.status()).readOnly).toBe(true);
});
test('closed receipt dates block a match even when the invoice date and submission month are open',async()=>{
  const store=await fresh();await importFile(store,g3('po_PO-2026-002'),'po');await importFile(store,g3('grn_PO-2026-002_R1'),'grn');
  await store.execute(()=>candidateSchema.parse({kind:'period.close',dataset:'SAMPLE',occurredOn:'2026-01-31',input:{},idempotencyKey:randomUUID(),effects:[{type:'period.closed',period:'2026-01',founderAuthorization:'synthetic-approval',gates:['G-1','G-2','G-3','G-4','G-5'].map(gate=>({gate,status:'PASS',evidenceRef:'synthetic-gate'}))}]}));
  const csvText=(await readFile(g3('inv_INV-A'),'utf8')).replace('2026-01-20','2026-02-01'),before=(await store.read()).length;
  await expect(store.execute(runs=>planProcurement({action:'import',...fields(),area:'inv',filename:'SAMPLE_inv_INV-A.csv',csvText},runs))).rejects.toThrow(/closed month/);expect((await store.read()).length).toBe(before);
});
test('blank or malformed numeric form inputs return validation issues rather than throwing Decimal errors',async()=>{
  const store=await fresh();await importFile(store,g3('po_PO-2026-002'),'po');const record=projectProcurement(await store.read()).orders[0]!.record;
  for(const patch of [{qtyPieces:''},{unitPriceTwd:'not-a-price'},{setupChargeTwd:''}]){const input={...record,lines:[{...record.lines[0],...patch}]};expect(()=>purchaseOrderSchema.safeParse(input)).not.toThrow();expect(purchaseOrderSchema.safeParse(input).success).toBe(false);}
});
test('damaged opening pieces stay zero-value memos and never increase sellable stock',async()=>{
  const store=await fresh();const masters=projectMasters(await store.read());const lines=masters.products.map(({record})=>({sku:record.sku,qtyPieces:'3',agreedUnitCostTwd:'2.0000',condition:'sellable'}));
  const result=await store.execute(runs=>planProcurement({action:'count',...fields(),founderConfirmed:true,record:{countedAt:'2026-01-01',evidenceRef:'synthetic-damaged-opening',lines:[...lines,{sku:lines[0]!.sku,qtyPieces:'5',agreedUnitCostTwd:'0.0000',condition:'damaged_unsellable'}]}},runs));
  expect(result.run.effects.filter(effect=>effect.type==='procurement.movement')).toHaveLength(2);expect(projectInventory(await store.read()).positions.every(item=>item.qtyPieces==='3')).toBe(true);expect(projectInventory(await store.read()).totalValueTwd).toBe('12.0000');
});
test('uncredited receipt damage gets full landed loss and no WAC quantity',async()=>{
  const store=await fresh();await importFile(store,g3('po_PO-2026-002'),'po');const csvText=(await readFile(g3('grn_PO-2026-002_R1'),'utf8')).replace(',3000,0,no,',',2900,100,no,');await store.execute(runs=>planProcurement({action:'import',...fields(),area:'grn',filename:'SAMPLE_grn_PO-2026-002_R1.csv',csvText},runs));await importFile(store,g3('inv_INV-A'),'inv');
  const state=projectProcurement(await store.read());expect(state.matches[0]?.lines[0]?.damagedValue).toBe('2030.0000');expect(projectInventory(await store.read()).positions.find(item=>item.sku==='TS-MT-005-S')?.qtyPieces).toBe('2900');expect(projectInventory(await store.read()).positions.find(item=>item.sku==='TS-MT-005-S')?.valueTwd).toBe('58870.0000');
});
test('count CSV re-import is idempotent and reference account adoption never rewrites the old bootstrap',async()=>{
  const store=await fresh(false);const before=await store.read(),bootstrap=before.find(run=>run.kind==='masters.bootstrap')!;const filename=join(store.directory,'runs',bootstrap.createdAt.slice(0,4),bootstrap.createdAt.slice(5,7),`${bootstrap.runId}.json`),bytes=await readFile(filename,'utf8');
  await importFile(store,'seed/samples/uat/SAMPLE_count_2026-10-04.csv','counts');expect(projectMasters(await store.read()).accounts).toHaveLength(75);expect(await readFile(filename,'utf8')).toBe(bytes);const length=(await store.read()).length;expect((await importFile(store,'seed/samples/uat/SAMPLE_count_2026-10-04.csv','counts')).duplicate).toBe(true);expect((await store.read()).length).toBe(length);
});
test('a supplier-stated deposit discrepancy is listed while the computed amount alone is posted',async()=>{
  const store=await fresh();for(const[file,area]of [['po_PO-2026-002','po'],['pay_DEP-002','pay'],['grn_PO-2026-002_R1','grn']] as const)await importFile(store,g3(file),area);
  const csvText=(await readFile(g3('inv_INV-A'),'utf8')).replace(',17400.0000,',',17000.0000,');await store.execute(runs=>planProcurement({action:'import',...fields(),area:'inv',filename:'SAMPLE_inv_INV-A.csv',csvText},runs));const state=projectProcurement(await store.read());expect(state.matches[0]?.depositAppliedTwd).toBe('17400.0000');expect(state.invoices[0]?.openAmountTwd).toBe('43500.0000');expect(state.exceptions.some(item=>item.message.includes('supplier-stated deposit'))).toBe(true);
});
test('goods-in-transit records block the unsupported receipt route',async()=>{
  const store=await fresh();await importFile(store,g3('po_PO-2026-002'),'po');const base=journalCandidate();const journal=base.effects.find(effect=>effect.type==='journal.posted');if(journal?.type!=='journal.posted')throw Error('fixture');
  await store.execute(()=>candidateSchema.parse({...base,occurredOn:'2026-01-15',input:{poNumber:'PO-2026-002',evidenceRef:'synthetic-transit'},effects:[{...journal,entry:{...journal.entry,occurredOn:'2026-01-15',sourceEvent:'po.in_transit'}}]}));
  await expect(importFile(store,g3('grn_PO-2026-002_R1'),'grn')).rejects.toThrow(/goods-in-transit/);
});
test('an immutable physical-count checkpoint refuses later backdated sales that would change its quantity',async()=>{
  const store=await fresh(false);await count(store,'2025-12-01','100','2.0000');await store.execute(runs=>planSelling({action:'verify-etsy',...fields(),...headerHashes,evidenceRef:'synthetic-review',founderConfirmed:true},runs));
  const input={action:'etsy',...fields(),orderFilename:'SAMPLE_etsy_orderitems_2025-12_fixture.csv',statementFilename:'SAMPLE_etsy_statement_2025-12_fixture.csv',ordersCsv:await readFile('seed/fixtures/SAMPLE_etsy_orderitems_2025-12_fixture.csv','utf8'),statementCsv:await readFile('seed/fixtures/SAMPLE_etsy_statement_2025-12_fixture.csv','utf8'),couponRules:['WELCOME10','HOLIDAY15','FREESHIP'].map(code=>({code,fundedBy:'seller',validFrom:null,validTo:null,evidenceRef:'synthetic-coupon'}))};
  await store.execute(runs=>planSelling(input,runs));const inventory=projectInventory(await store.read()),masters=projectMasters(await store.read());await store.execute(runs=>planProcurement({action:'count',...fields(),founderConfirmed:true,record:{countedAt:'2026-01-01',evidenceRef:'synthetic-checkpoint',lines:masters.products.map(({record})=>({sku:record.sku,qtyPieces:inventory.positions.find(position=>position.sku===record.sku)?.qtyPieces??'0',agreedUnitCostTwd:'0.0000',condition:'sellable'}))}},runs));
  await expect(store.execute(runs=>planSelling({...input,idempotencyKey:randomUUID(),ordersCsv:input.ordersCsv.replaceAll('291847','391847').replaceAll('384910','484910')},runs))).rejects.toThrow(/booked physical count/);
});
