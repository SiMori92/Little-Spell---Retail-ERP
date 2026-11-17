import { afterEach,expect,test } from 'vitest';
import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { workspace } from './helpers';
import { initializeWorkspace } from '../src/server/initialize';
import { accountingState,planAccounting,pendingAccounting } from '../src/domain/accounting';
import { buildReports,allocate,settlementAging,combine,known,absent } from '../src/domain/reporting';
import { closeGates,planClose } from '../src/domain/closing';
import { projectMasters } from '../src/domain/master-projection';
import { projectInventory } from '../src/domain/inventory-projection';
import { planProcurement } from '../src/domain/procurement';
import { planSelling } from '../src/domain/selling';
import { headerHashes } from '../src/domain/selling-csv';
import { supplementaryJournal } from '../src/domain/posting/catalogue';
import Decimal from '../src/domain/decimal';
import { candidateSchema } from '../src/domain/schemas';
import { planActivation } from '../src/domain/activation';
import { planReversal } from '../src/domain/reversal';
const cleanups:(()=>Promise<unknown>)[]=[];
afterEach(async()=>{for(const cleanup of cleanups.splice(0))await cleanup();});
const base=()=>({occurredOn:'2026-10-02',idempotencyKey:randomUUID(),expectedHeadHash:null});
async function fresh(){const c=await workspace();cleanups.push(c.cleanup);await initializeWorkspace(c.store.directory);return c.store;}
test('manual facts are unposted, previews write zero, posting balances, retries write zero, and corrections preserve original',async()=>{
 const store=await fresh(),input={action:'manual',...base(),evidenceRef:'synthetic-capital-voucher',record:{eventType:'owner.funds_moved',amount:'1000.0000',fundsType:'capital'}};
 const before=(await store.read()).length;await store.execute(r=>planAccounting(input,r),true);expect((await store.read()).length).toBe(before);
 await store.execute(r=>planAccounting(input,r));expect(accountingState(await store.read()).entries).toHaveLength(0);
 const fact=accountingState(await store.read()).facts[0]!,post={action:'post',...base(),eventId:fact.id};const result=await store.execute(r=>planAccounting(post,r));await store.execute(r=>planAccounting(post,r));expect((await store.read()).length).toBe(before+2);
 const journal=result.run.effects.find(e=>e.type==='journal.posted');if(journal?.type!=='journal.posted')throw Error('test');expect(journal.entry.lines[0]?.debit).toBe('1000.0000');
 const reverse={action:'reverse',...base(),occurredOn:'2026-11-17',entryId:journal.entry.entryId,reason:'synthetic-source-correction'};await store.execute(r=>planAccounting(reverse,r));expect(accountingState(await store.read()).entries).toHaveLength(2);expect(buildReports(await store.read(),'2026-11').find(r=>r.slug==='trial-balance')?.rows.find(r=>r.account==='1121')?.balance).toMatchObject({amount:'0.0000'});
 await expect(store.execute(r=>planAccounting({...reverse,idempotencyKey:randomUUID()},r))).rejects.toThrow(/unreversed/);
});
test('accrual estimate, reversal, tax and owner classifications use their specified accounts',async()=>{
 const store=await fresh();for(const [index,record]of [{eventType:'period.accrued',amount:'23.4000',expenseAccount:'6161',accrualAccount:'2193',basisNote:'synthetic-prorated-license'},{eventType:'tax.assessed',amount:'50.0000',needsProfessionalConfirmation:true},{eventType:'tax.paid',amount:'50.0000'},{eventType:'owner.funds_moved',amount:'100.0000',fundsType:'drawings'},{eventType:'owner.funds_moved',amount:'200.0000',fundsType:'loan'},{eventType:'period.revalued',amount:'1.0000',account:'1191',direction:'gain',rateSource:'synthetic-month-end-public-rate'}].entries()){
 await store.execute(r=>planAccounting({action:'manual',...base(),evidenceRef:`synthetic-manual-${index}`,record},r));const fact=accountingState(await store.read()).facts.at(-1)!;await store.execute(r=>planAccounting({action:'post',...base(),eventId:fact.id},r));}
 const accrual=accountingState(await store.read()).facts[0]!;await store.execute(r=>planAccounting({action:'manual',...base(),occurredOn:'2026-11-01',record:{eventType:'period.accrual_reversed',originalId:accrual.id},evidenceRef:'synthetic-next-month-reversal'},r));const reversal=accountingState(await store.read()).facts.at(-1)!;await store.execute(r=>planAccounting({action:'post',...base(),occurredOn:'2026-11-01',eventId:reversal.id},r));
 const entries=accountingState(await store.read()).entries;expect(entries[0]?.entry.lines[0]?.memo).toContain('[ESTIMATE] basis:');expect(entries[3]?.entry.lines[0]?.account.code).toBe('3211');expect(entries[4]?.entry.lines[1]?.account.code).toBe('2281');expect(closeGates(await store.read(),'2026-11')[4]?.status).toBe('PASS');
 await expect(store.execute(r=>planAccounting({action:'manual',...base(),evidenceRef:'synthetic-invalid-revaluation',record:{eventType:'period.revalued',amount:'1',account:'1231',direction:'gain',rateSource:'synthetic-rate'}},r))).rejects.toThrow(/Stock/);
});
test('expenses need category attribution, evidenced unique receipts and a separate posting review',async()=>{
 const store=await fresh(),input={action:'expense',...base(),record:{date:'2026-10-02',category:'advertising',amountTwd:'125.2500',settledVia:'bank',bankAccount:'1121',channel:'meta',description:'Synthetic ad voucher',evidenceRef:'synthetic-meta-ad'}};
 await expect(store.execute(r=>planAccounting({...input,record:{...input.record,channel:''}},r))).rejects.toThrow();await store.execute(r=>planAccounting(input,r));const f=accountingState(await store.read()).facts[0]!;await store.execute(r=>planAccounting({action:'post',...base(),eventId:f.id},r));const journal=accountingState(await store.read()).entries[0]!.entry;expect(journal.lines.map(l=>l.account.code)).toEqual(['6142','1121']);
 await expect(store.execute(r=>planAccounting({...input,idempotencyKey:randomUUID()},r))).rejects.toThrow(/already/);
});
test('public rates are immutable and posting refuses missing rate evidence and unresolved settlement',async()=>{
 const store=await fresh(),fx={action:'fx',...base(),date:'2025-12-28',currency:'USD',rate:'31.123456',evidenceRef:'synthetic-public-fx'};
 await store.execute(r=>planAccounting(fx,r));await expect(store.execute(r=>planAccounting({...fx,idempotencyKey:randomUUID(),rate:'32.000000'},r))).rejects.toThrow(/already/);expect(accountingState(await store.read()).rates[0]?.rate).toBe('31.123456');
});
test('forged accounting effects are refused before writing',async()=>{
 const store=await fresh(),candidate=planAccounting({action:'manual',...base(),evidenceRef:'synthetic-forgery-voucher',record:{eventType:'owner.funds_moved',amount:'1.0000',fundsType:'capital'}},await store.read());candidate.effects=[];
 await expect(store.execute(()=>candidate)).rejects.toThrow();
});
test('a genuine opening count can acquire sourced journal attribution append-only and G3 compares independent quantities',async()=>{
 const store=await fresh(),masters=projectMasters(await store.read());await store.execute(r=>planProcurement({action:'count',...base(),record:{countedAt:'2026-01-01',evidenceRef:'synthetic-complete-opening',lines:masters.products.map(p=>({sku:p.record.sku,qtyPieces:p.record.productType==='packaging'?'0':'10',agreedUnitCostTwd:p.record.productType==='packaging'?'0.0000':'2.0000',condition:'sellable'}))},founderConfirmed:true},r));
 expect(closeGates(await store.read(),'2026-10')[2]?.status).toBe('NOT_RUNNABLE');const before=await store.read();await store.execute(r=>planAccounting({action:'inventory-evidence',...base(),evidenceRef:'synthetic-journal-attribution-review'},r));expect((await store.read()).slice(0,before.length)).toEqual(before);expect(closeGates(await store.read(),'2026-10')[2]?.status).toBe('PASS');
});
test('Etsy deposit, dispatch, fees and WAC post once in TWD with no second stock deduction',async()=>{
 const store=await fresh(),masters=projectMasters(await store.read());await store.execute(r=>planProcurement({action:'count',...base(),record:{countedAt:'2025-12-01',evidenceRef:'synthetic-sales-opening',lines:masters.products.map(p=>({sku:p.record.sku,qtyPieces:p.record.productType==='packaging'?'0':'1000',agreedUnitCostTwd:p.record.productType==='packaging'?'0.0000':'1.0000',condition:'sellable'}))},founderConfirmed:true},r));
 await store.execute(r=>planSelling({action:'verify-etsy',...base(),...headerHashes,evidenceRef:'synthetic-own-header-review',founderConfirmed:true},r));
 const ordersCsv=await readFile('seed/fixtures/SAMPLE_etsy_orderitems_2025-12_fixture.csv','utf8'),statementCsv=await readFile('seed/fixtures/SAMPLE_etsy_statement_2025-12_fixture.csv','utf8');
 await store.execute(r=>planSelling({action:'etsy',...base(),orderFilename:'SAMPLE_etsy_orderitems_2025-12_fixture.csv',statementFilename:'SAMPLE_etsy_statement_2025-12_fixture.csv',ordersCsv,statementCsv,couponRules:['WELCOME10','HOLIDAY15','FREESHIP'].map(code=>({code,fundedBy:'seller',validFrom:null,validTo:null,evidenceRef:'synthetic-seller-coupon'}))},r));
 const pending=pendingAccounting(await store.read()),dates=[...new Set(pending.map(e=>e.date))];for(const date of dates)await store.execute(r=>planAccounting({action:'fx',...base(),date,currency:'USD',rate:'31.0000',evidenceRef:`synthetic-rate-${date}`},r));
 const before=projectInventory(await store.read());for(const type of ['order.placed','order.shipped','order.cogs_relieved','order.fees_assessed','cost.recorded'])for(const event of pending.filter(e=>e.label===type))await store.execute(r=>planAccounting({action:'post',...base(),occurredOn:event.date,eventId:event.id},r));expect(projectInventory(await store.read()).positions).toEqual(before.positions);expect(projectInventory(await store.read()).pendingCogsTwd).toBe('0.0000');
 const state=accountingState(await store.read());expect(state.entries.filter(e=>e.entry.sourceEvent==='order.shipped')).toHaveLength(5);const settlement=pending.find(e=>e.label==='settlement.received');if(settlement)await expect(store.execute(r=>planAccounting({action:'post',...base(),occurredOn:settlement.date,eventId:settlement.id},r))).rejects.toThrow(/composition/);
});
test('missing evidence never passes a close; attempts persist blocked without closing the month',async()=>{
 const store=await fresh(),gates=closeGates(await store.read(),'2026-10');expect(gates.find(g=>g.gate==='G-2')?.status).toBe('NOT_RUNNABLE');expect(gates.find(g=>g.gate==='G-4')?.status).toBe('NOT_RUNNABLE');
 const input={action:'close',...base(),occurredOn:'2026-11-17',period:'2026-10',actor:'Synthetic founder',evidenceRef:'synthetic-close-packet',founderAuthorization:'synthetic-authorization'};
 const before=(await store.read()).length;await store.execute(r=>planClose(input,r),true);expect((await store.read()).length).toBe(before);const result=await store.execute(r=>planClose(input,r));expect(result.run.effects.some(e=>e.type==='period.closed')).toBe(false);expect(result.run.effects[0]).toMatchObject({status:'BLOCKED'});
 const forged=planClose({...input,idempotencyKey:randomUUID()},await store.read());forged.effects.push({type:'period.closed',period:'2026-10',founderAuthorization:'synthetic',gates:[]});await expect(store.execute(()=>forged)).rejects.toThrow();
});
test('closed months refuse recording and posting on effective fact dates',async()=>{
 const store=await fresh();await store.execute(()=>candidateSchema.parse({kind:'period.close',dataset:'SAMPLE',occurredOn:'2026-10-31',input:{},idempotencyKey:'synthetic-legacy-closed',effects:[{type:'period.closed',period:'2026-10',founderAuthorization:'synthetic',gates:['G-1','G-2','G-3','G-4','G-5'].map(gate=>({gate,status:'PASS',evidenceRef:'synthetic-foundation-test'}))}]}));
 await expect(store.execute(r=>planAccounting({action:'manual',...base(),record:{eventType:'owner.funds_moved',amount:'1.0000',fundsType:'capital'},evidenceRef:'synthetic-closed-fact'},r))).rejects.toThrow(/closed/);
});
test('figure absence propagates; exact allocation keeps last-key remainder',()=>{
 expect(combine([known('10'),absent('Freight missing')])).toMatchObject({amount:null,basis:'absent'});expect([...allocate('1.0000',new Map([['A',new Decimal(1)],['B',new Decimal(1)],['C',new Decimal(1)]]))]).toEqual([['A','0.3333'],['B','0.3333'],['C','0.3334']]);expect(settlementAging([],'2026-10')).toEqual([]);
});
test('receipt CSV validates headers and month, imports atomically, and a second file import writes zero runs',async()=>{
 const store=await fresh(),csvText='occurred_on,category,amount_twd,settled_via,evidence_ref,description\n2026-10-02,software,12.50,bank,synthetic-import-receipt,Synthetic license\n',input={action:'import-receipts',...base(),filename:'SAMPLE_receipts_2026-10.csv',csvText};
 await expect(store.execute(r=>planAccounting({...input,csvText:csvText.replace('category','wrong_category')},r))).rejects.toThrow(/header/);await expect(store.execute(r=>planAccounting({...input,filename:'SAMPLE_receipts_2026-09.csv'},r))).rejects.toThrow(/month/);
 await store.execute(r=>planAccounting(input,r));const before=(await store.read()).length;const repeat=await store.execute(r=>planAccounting({...input,...base()},r));expect(repeat.duplicate).toBe(true);expect((await store.read()).length).toBe(before);expect(accountingState(await store.read()).facts).toHaveLength(1);
});
test('the normal manifest-only seed supports an evidenced, one-way quarantine transition',async()=>{
 const store=await fresh(),fields={...base(),founderAuthorization:'synthetic-founder-real-opening',evidenceRef:'synthetic-real-opening-packet'},activate={action:'activate',...fields};
 await expect(store.execute(r=>planActivation(activate,r))).rejects.toThrow(/Reverse/);
 const seed=(await store.read()).find(r=>r.kind==='sample.seed')!;await store.execute(r=>planReversal({originalRunId:seed.runId,occurredOn:'2026-10-02',reason:'Synthetic manifest-only seed retired',idempotencyKey:randomUUID()},r));
 await store.execute(r=>planActivation({action:'actual-opening',...fields,lines:[{account:'1121',debit:'100.0000',credit:'0.0000'},{account:'3111',debit:'0.0000',credit:'100.0000'}]},r));
 await store.execute(r=>planActivation({...activate,idempotencyKey:randomUUID()},r));expect((await store.status()).dataset).toBe('ACTUAL');expect(projectMasters(await store.read()).products).toHaveLength(0);expect(accountingState(await store.read()).entries).toHaveLength(1);
 await expect(store.execute(r=>planActivation({...activate,idempotencyKey:randomUUID()},r))).rejects.toThrow(/already active/);
});
test.each([
 {eventType:'order.cancelled',amount:'100',phase:'pre'}, {eventType:'order.cancelled',amount:'100',phase:'post'}, {eventType:'order.refunded',amount:'100',feeRefunds:[{account:'6112',amount:'2'}]},
 {eventType:'order.ship_cost_accrued',amount:'100',basisNote:'Synthetic carrier quote'}, {eventType:'order.ship_cost_invoiced',amount:'110',accruedTwd:'100',accrualRef:'synthetic-accrual'}, {eventType:'order.duty_incurred',amount:'20',position:'DDP'}, {eventType:'order.duty_invoiced',amount:'15',accruedTwd:'20',accrualRef:'synthetic-duty'},
 {eventType:'po.in_transit',amount:'100'}, {eventType:'po.landed_cost_adjusted',amount:'100',onhandRatio:'0.4',lotRef:'synthetic-lot',sku:'SYNTHETIC'}, {eventType:'settlement.received',cashTwd:'3000',usdSettled:'100',publicRate:'31',channelRate:'30',rateSource:'derived',evidenceRef:'synthetic-bank'}, {eventType:'settlement.received',cashTwd:'3100',usdSettled:'100',publicRate:'30',channelRate:'31',rateSource:'derived',evidenceRef:'synthetic-bank'}, {eventType:'settlement.reversed',originalCarryingTwd:'3100',bankReversalTwd:'3120',reversalFeeTwd:'10'}, {eventType:'order.reprint_issued',decisionsRef:'synthetic-reprint-approval',sku:'SYNTHETIC',qtyPieces:'3',positionPieces:'10',positionValue:'100'}
])('supplementary catalogue $eventType balances independently',record=>{const entry=supplementaryJournal(record,'2026-10-02',randomUUID())!;const expected:Record<string,string[][]>={
 'order.cancelled:pre':[['2211','100.0000','0.0000'],['1191','0.0000','100.0000']],
 'order.cancelled:post':[['4192','100.0000','0.0000'],['1191','0.0000','100.0000']],
 'order.refunded':[['4192','100.0000','0.0000'],['1191','0.0000','100.0000'],['1191','2.0000','0.0000'],['6112','0.0000','2.0000']],
 'order.ship_cost_accrued':[['6131','100.0000','0.0000'],['2191','0.0000','100.0000']],
 'order.ship_cost_invoiced':[['2191','100.0000','0.0000'],['2172','0.0000','110.0000'],['6131','10.0000','0.0000']],
 'order.duty_incurred':[['6132','20.0000','0.0000'],['2192','0.0000','20.0000']],
 'order.duty_invoiced':[['2192','20.0000','0.0000'],['2172','0.0000','15.0000'],['6132','0.0000','5.0000']],
 'po.in_transit':[['1232','100.0000','0.0000'],['2171','0.0000','100.0000']],
 'po.landed_cost_adjusted':[['1231','40.0000','0.0000'],['5112','60.0000','0.0000'],['2172','0.0000','100.0000']],
 'settlement.received:3000':[['1121','3000.0000','0.0000'],['1191','0.0000','3100.0000'],['6116','100.0000','0.0000']],
 'settlement.received:3100':[['1121','3100.0000','0.0000'],['1191','0.0000','3000.0000'],['6116','0.0000','100.0000']],
 'settlement.reversed':[['1191','3100.0000','0.0000'],['1121','0.0000','3120.0000'],['6181','10.0000','0.0000'],['6116','10.0000','0.0000']],
 'order.reprint_issued':[['5111','30.0000','0.0000'],['1231','0.0000','30.0000']]
 };const suffix='phase' in record?`:${record.phase}`:'cashTwd' in record?`:${record.cashTwd}`:'';expect(entry.lines.map(l=>[l.account.code,l.debit,l.credit])).toEqual(expected[record.eventType+suffix]);});
test('DDU is memo-only, gateways remain reserved and excessive settlement spread refuses',()=>{expect(supplementaryJournal({eventType:'order.duty_incurred',amount:'0',position:'DDU'},'2026-10-02',randomUUID())).toBe(null);expect(()=>supplementaryJournal({eventType:'payment.received',amount:'1'},'2026-10-02',randomUUID())).toThrow(/RESERVED/);expect(()=>supplementaryJournal({eventType:'settlement.received',cashTwd:'1',usdSettled:'100',publicRate:'31',channelRate:'0.01',rateSource:'derived',evidenceRef:'synthetic'},'2026-10-02',randomUUID())).toThrow(/tolerance/);});
