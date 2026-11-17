import { afterEach, expect, test } from 'vitest';
import { randomUUID } from 'node:crypto';
import { readFile, chmod, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { workspace } from './helpers';
import { initializeWorkspace } from '../src/server/initialize';
import { projectMasters } from '../src/domain/master-projection';
import { projectSelling } from '../src/domain/selling-projection';
import { planSelling, sellingBlockers } from '../src/domain/selling';
import { headerHashes, normalizeSelling, parseOrders, parseStatement } from '../src/domain/selling-csv';
import { sellingPayloadSchema, dealSchema } from '../src/domain/schemas/selling';
import { candidateSchema, runSchema } from '../src/domain/schemas';
import { canonical, digest } from '../src/domain/canonical';
import { placeOrder, dispatchOrder } from '../src/domain/posting/selling';

const cleanups:(()=>Promise<unknown>)[]=[];
afterEach(async()=>{for(const cleanup of cleanups.splice(0))await cleanup();});
const fields=()=>({occurredOn:'2026-11-16',idempotencyKey:randomUUID(),expectedHeadHash:null});
async function fresh(stock=true,verified=true){const context=await workspace();cleanups.push(context.cleanup);await initializeWorkspace(context.store.directory);if(stock){const masters=projectMasters(await context.store.read());await context.store.execute(()=>candidateSchema.parse({kind:'stock.count',dataset:'SAMPLE',occurredOn:'2025-12-01',input:{evidenceRef:'synthetic-test-stock-only'},idempotencyKey:randomUUID(),effects:masters.products.map(({record})=>({type:'stock.moved',move:{moveId:randomUUID(),sku:record.sku,qtyPieces:'10000',condition:'sellable',valueTwd:'10000.0000'}}))}));}if(verified)await context.store.execute(runs=>planSelling({action:'verify-etsy',...fields(),...headerHashes,evidenceRef:'synthetic-header-review',founderConfirmed:true},runs));return context.store;}
async function etsy(){return sellingPayloadSchema.parse({action:'etsy',...fields(),orderFilename:'SAMPLE_etsy_orderitems_2025-12_fixture.csv',statementFilename:'SAMPLE_etsy_statement_2025-12_fixture.csv',ordersCsv:await readFile('seed/fixtures/SAMPLE_etsy_orderitems_2025-12_fixture.csv','utf8'),statementCsv:await readFile('seed/fixtures/SAMPLE_etsy_statement_2025-12_fixture.csv','utf8'),couponRules:['WELCOME10','HOLIDAY15','FREESHIP'].map(code=>({code,fundedBy:'seller',validFrom:null,validTo:null,evidenceRef:'synthetic-coupon-decision'}))});}
function enquiry(){return dealSchema.parse({dealId:'IG-202611-901',customerRef:'C-0901',status:'enquiry',enquiryAt:'2026-11-01',quotedAt:null,quoteTwd:null,followUpOn:'2026-11-04',lostReason:'',lines:[{sku:'',qtySaleUnits:null,unitPriceTwd:null}],shippingTwd:null,shipCountry:'',paidAt:null,walletTxnId:'',shipDate:null,consentMarketing:'',journeySent:'none',evidenceRef:'synthetic-deal'});}

test('Etsy previews compute effects but unverified headers cannot be committed',async()=>{const store=await fresh(true,false),input=await etsy();const runs=await store.read();expect(planSelling(input,runs,true).effects.length).toBeGreaterThan(0);expect(sellingBlockers(input,runs)).toHaveLength(1);await expect(store.execute(history=>planSelling(input,history))).rejects.toThrow(/unverified/);expect((await store.read()).length).toBe(runs.length);});
test('header verification requires exact fingerprints and founder confirmation',async()=>{const store=await fresh(false,false);await expect(store.execute(runs=>planSelling({action:'verify-etsy',...fields(),...headerHashes,evidenceRef:'synthetic-review',founderConfirmed:false},runs))).rejects.toThrow();await expect(store.execute(runs=>planSelling({action:'verify-etsy',...fields(),...headerHashes,orderHeaderHash:'a'.repeat(64),evidenceRef:'synthetic-review',founderConfirmed:true},runs))).rejects.toThrow(/fingerprints/);});
test('paired Etsy fixture import is atomic, has exact gross controls, queued events and no journal',async()=>{
  const store=await fresh(),input=await etsy(),before=(await store.read()).length;
  const result=await store.execute(runs=>planSelling(input,runs)),projection=projectSelling(await store.read());
  expect((await store.read()).length).toBe(before+1);expect(projection.orders).toHaveLength(5);expect(projection.statements).toHaveLength(1);expect(projection.shipments).toHaveLength(5);
  expect(projection.statements[0]?.residual).toBe('0.0000');expect(projection.statements[0]?.compositionResolved).toBe(true);
  expect(projection.events.every(event=>event.status==='UNPOSTED')).toBe(true);expect(result.run.effects.some(effect=>effect.type==='journal.posted')).toBe(false);
  const order=projection.orders.find(item=>item.record.orderId==='2918473019')!;expect(order.record.gross).toBe('30.9700');expect(order.record.buyerPaid).toBe('28.3700');
  expect(projection.events.find(item=>item.eventType==='order.placed'&&item.entityRef===order.record.orderId)?.amount).toBe('28.3700');
  const product=projectMasters(await store.read()).products.find(item=>item.record.sku==='TS-FL-001-S')!;
  expect(projection.shipments.find(item=>item.orderId===order.record.orderId)?.lines[0]?.qtyPieces).toBe(String(2*product.record.piecesPerSaleUnit));
});
test('identical files, reordered statement rows, and later duplicate requests create zero runs',async()=>{
  const store=await fresh(),input=await etsy();await store.execute(runs=>planSelling(input,runs));const before=(await store.read()).length;
  const repeated=await store.execute(runs=>planSelling({...input,occurredOn:'2026-11-17',idempotencyKey:randomUUID()},runs));expect(repeated.duplicate).toBe(true);
  if(input.action!=='etsy')throw Error('fixture');const [header,...rows]=input.statementCsv.trimEnd().split('\n');
  const reordered=await store.execute(runs=>planSelling({...input,idempotencyKey:randomUUID(),statementCsv:[header,...rows.reverse()].join('\n')+'\n'},runs));expect(reordered.duplicate).toBe(true);expect((await store.read()).length).toBe(before);
});
test('changed statement duplicate multiplicity refuses without any partial write',async()=>{
  const store=await fresh(),input=await etsy();await store.execute(runs=>planSelling(input,runs));const before=(await store.read()).length;
  if(input.action!=='etsy')throw Error('fixture');const row=input.statementCsv.split('\n').find(line=>line.includes('Listing Fee'))!;
  await expect(store.execute(runs=>planSelling({...input,statementCsv:input.statementCsv+row+'\n'},runs))).rejects.toThrow(/multiset/);expect((await store.read()).length).toBe(before);
});
test('missing coupon funding, malformed headers, sale controls, and provenance refuse',async()=>{
  const store=await fresh(),input=await etsy();if(input.action!=='etsy')throw Error('fixture');
  for(const patch of [{couponRules:[]},{ordersCsv:input.ordersCsv.replace('Sale Date,','Wrong Date,')},{statementCsv:input.statementCsv.replace('30.97','30.98')},{orderFilename:'etsy_orderitems_2025-12.csv'}])await expect(store.execute(runs=>planSelling({...input,...patch},runs))).rejects.toThrow();
});
test('buyer columns are discarded before persistence or effects; statement narratives are not retained',async()=>{
  const store=await fresh(),input=await etsy();if(input.action!=='etsy')throw Error('fixture');const secret=['synthetic-buyer','invalid.example'].join('@');
  const raw=input.ordersCsv.replace('12/28/25,,,2,',`12/28/25,Private synthetic label,${secret},2,`);
  const result=await store.execute(runs=>planSelling({...input,ordersCsv:raw},runs));const content=canonical(result.run);
  expect(content.includes(secret)).toBe(false);expect(content.includes('Private synthetic label')).toBe(false);expect(content.includes('Bank account ending')).toBe(false);
});
test('dispatch cannot use M1 preparation, damaged pieces, or future dated stock',async()=>{
  const store=await fresh(false),input=await etsy();await expect(store.execute(runs=>planSelling(input,runs))).rejects.toThrow(/counted sellable/);
  const masters=projectMasters(await store.read());await store.execute(()=>candidateSchema.parse({kind:'stock.count',dataset:'SAMPLE',occurredOn:'2026-01-01',input:{evidenceRef:'synthetic-future-stock'},idempotencyKey:randomUUID(),effects:masters.products.map(({record})=>({type:'stock.moved',move:{moveId:randomUUID(),sku:record.sku,qtyPieces:'10000',condition:'sellable',valueTwd:'10000.0000'}}))}));
  await expect(store.execute(runs=>planSelling(input,runs))).rejects.toThrow(/dispatch date/);
});
test('unshipped orders emit no revenue or cost event; guided dispatch is append-only and once only',async()=>{
  const store=await fresh(),input=await etsy();if(input.action!=='etsy')throw Error('fixture');
  const sanitized=normalizeSelling(input);if(sanitized.action!=='etsy')throw Error('fixture');
  const lines=sanitized.ordersCsv.trimEnd().split('\n');const columns=lines[0]!.split(',');const ship=columns.indexOf('Date Shipped');
  const unshipped=[lines[0],...lines.slice(1).map(line=>{const cells=line.split(',');cells[ship]='';return cells.join(',');})].join('\n')+'\n';
  await store.execute(runs=>planSelling({...input,ordersCsv:unshipped},runs));let projection=projectSelling(await store.read());expect(projection.events.some(event=>event.eventType==='order.shipped'||event.eventType==='order.cogs_relieved')).toBe(false);
  const order=projection.orders[0]!;const payload={action:'dispatch',...fields(),occurredOn:'2026-11-16',shipDate:'2026-11-16',orderId:order.record.orderId,previousRunId:order.runId,trackingRef:'synthetic-tracking',evidenceRef:'synthetic-dispatch'};
  await store.execute(runs=>planSelling(payload,runs));projection=projectSelling(await store.read());expect(projection.shipments).toHaveLength(1);expect(projection.events.filter(event=>event.eventType==='order.shipped')).toHaveLength(1);
  await expect(store.execute(runs=>planSelling({...payload,idempotencyKey:randomUUID()},runs))).rejects.toThrow(/already dispatched/);
});
test('Instagram forward snapshots preserve originals, freeze paid lines, and refuse stale versions',async()=>{
  const store=await fresh(false);const record=enquiry();const first=await store.execute(runs=>planSelling({action:'deal',...fields(),previousRunId:null,record},runs));
  const quoted={...record,status:'quoted',quotedAt:'2026-11-02',quoteTwd:'600.0000'};const second=await store.execute(runs=>planSelling({action:'deal',...fields(),previousRunId:first.run.runId,record:quoted},runs));
  await expect(store.execute(runs=>planSelling({action:'deal',...fields(),previousRunId:first.run.runId,record:quoted},runs))).rejects.toThrow(/changed/);
  const paid={...quoted,status:'paid',paidAt:'2026-11-03',walletTxnId:'synthetic-wallet-901',shippingTwd:'0.0000',shipCountry:'TW',lines:[{sku:'TS-FL-001-S',qtySaleUnits:'2',unitPriceTwd:'300.0000'}]};const third=await store.execute(runs=>planSelling({action:'deal',...fields(),previousRunId:second.run.runId,record:paid},runs));
  await expect(store.execute(runs=>planSelling({action:'deal',...fields(),previousRunId:third.run.runId,record:{...paid,status:'shipped',shipDate:'2026-11-04',lines:[{...paid.lines[0],qtySaleUnits:'3'}]}},runs))).rejects.toThrow(/fixed/);
  expect(projectSelling(await store.read()).history.filter(item=>item.record.dealId===record.dealId)).toHaveLength(3);
});
test('Instagram exact v2 sample import is idempotent and creates no wallet or journal entry',async()=>{
  const store=await fresh(false);const csvText=await readFile('seed/samples/SAMPLE_ig_deals_2026-10.csv','utf8');const input={action:'ig-import',...fields(),filename:'SAMPLE_ig_deals_2026-10.csv',csvText};
  const result=await store.execute(runs=>planSelling(input,runs)),before=(await store.read()).length;expect(result.run.effects.some(effect=>effect.type==='journal.posted')).toBe(false);expect(projectSelling(await store.read()).deals).toHaveLength(12);
  const duplicate=await store.execute(runs=>planSelling({...input,idempotencyKey:randomUUID()},runs));expect(duplicate.duplicate).toBe(true);expect((await store.read()).length).toBe(before);
  await expect(store.execute(runs=>planSelling({...input,csvText:csvText.replace('qty_sale_units','qty_packs')},runs))).rejects.toThrow(/v2/);
});
test('deal schema refuses chronology, missing next action, invalid quantities and missing lost reason',()=>{
  for(const patch of [{followUpOn:null},{quotedAt:'2026-10-01'},{status:'lost'},{lines:[{sku:'',qtySaleUnits:'1.5',unitPriceTwd:null}]}])expect(dealSchema.safeParse({...enquiry(),...patch}).success).toBe(false);
});
test('ACTUAL paid Instagram is blocked before any claim of wallet cash',()=>{
  const activation=runSchema.parse({runId:randomUUID(),kind:'dataset.activate',dataset:'ACTUAL',createdAt:'2026-11-16T00:00:00.000Z',occurredOn:'2026-11-16',schemaVersion:1,input:{},effects:[{type:'dataset.activated'}],idempotencyKey:'synthetic-actual-context',prevHash:'0'.repeat(64),hash:'a'.repeat(64)});
  const record={...enquiry(),status:'paid',quotedAt:'2026-11-02',quoteTwd:'600.0000',paidAt:'2026-11-03',walletTxnId:'synthetic-wallet',shippingTwd:'0.0000',shipCountry:'TW',lines:[{sku:'TS-FL-001-S',qtySaleUnits:'2',unitPriceTwd:'300.0000'}]};
  expect(()=>planSelling({action:'deal',...fields(),previousRunId:null,record},[activation])).toThrow(/wallet-statement/);
});
test('wallet references cannot cross deals and final lost states cannot reopen',async()=>{
  const store=await fresh(false);const record={...enquiry(),status:'paid',quotedAt:'2026-11-02',quoteTwd:'600',paidAt:'2026-11-03',walletTxnId:'synthetic-unique-wallet',shippingTwd:'0',shipCountry:'TW',lines:[{sku:'TS-FL-001-S',qtySaleUnits:'2',unitPriceTwd:'300'}]};
  await store.execute(runs=>planSelling({action:'deal',...fields(),previousRunId:null,record},runs));
  await expect(store.execute(runs=>planSelling({action:'deal',...fields(),previousRunId:null,record:{...record,dealId:'IG-202611-902'}},runs))).rejects.toThrow(/already belongs/);
  const lost=await store.execute(runs=>planSelling({action:'deal',...fields(),previousRunId:null,record:{...enquiry(),dealId:'IG-202611-903',status:'lost',lostReason:'no_reply'}},runs));
  await expect(store.execute(runs=>planSelling({action:'deal',...fields(),previousRunId:lost.run.runId,record:{...enquiry(),dealId:'IG-202611-903'}},runs))).rejects.toThrow(/final state/);
});
test('platform-funded discounts and domestic dispatch use the approved revenue accounts',async()=>{
  const input=await etsy();if(input.action!=='etsy')throw Error('fixture');const order={...parseOrders(input)[0]!,discountFundedBy:'platform',country:'TW'};
  const fx={id:'synthetic-public-fx',date:order.orderDate,currency:'USD',rate:'32.0000',source:'public',evidenceRef:'synthetic-public-rate'};
  expect(placeOrder(order,fx,randomUUID()).lines[0]?.debit).toBe('991.0400');expect(dispatchOrder(order,fx,'2025-12-29',randomUUID()).lines.map(line=>line.account.code)).toEqual(['2211','4112','4182']);
});
test('closed effective dates reject imports even when the submission date is open',async()=>{
  const store=await fresh(),input=await etsy();await store.execute(()=>candidateSchema.parse({kind:'period.close',dataset:'SAMPLE',occurredOn:'2025-12-31',input:{},idempotencyKey:randomUUID(),effects:[{type:'period.closed',period:'2025-12',founderAuthorization:'synthetic-approval',gates:['G-1','G-2','G-3','G-4','G-5'].map(gate=>({gate,status:'PASS',evidenceRef:'synthetic-gate'}))}]}));
  await expect(store.execute(runs=>planSelling(input,runs))).rejects.toThrow(/closed/);
});
test('preview-head conflicts and mutated/rehashed selling effects are refused',async()=>{
  const store=await fresh(false);const input={action:'deal',...fields(),previousRunId:null,record:enquiry()};const before=await store.read();
  await store.execute(runs=>planSelling(input,runs));await expect(store.execute(runs=>planSelling({...input,idempotencyKey:randomUUID(),expectedHeadHash:before.at(-1)!.hash},runs))).rejects.toThrow(/Preview again/);
  const other={...enquiry(),dealId:'IG-202611-902',customerRef:'C-0902'};const candidate=planSelling({...input,idempotencyKey:randomUUID(),record:other},await store.read());const effect=candidate.effects[0];if(effect?.type!=='selling.deal')throw Error('fixture');effect.record.evidenceRef='forged-evidence';await expect(store.execute(()=>candidate)).rejects.toThrow(/effects/);
  const result=await store.execute(runs=>planSelling({...input,idempotencyKey:randomUUID(),record:other},runs));const record=result.run.effects[0];if(record?.type!=='selling.deal')throw Error('fixture');record.record.evidenceRef='forged-evidence';const {hash,...body}=result.run;void hash;const filename=join(store.directory,'runs',result.run.createdAt.slice(0,4),result.run.createdAt.slice(5,7),`${result.run.runId}.json`);await chmod(filename,0o600);await writeFile(filename,canonical({...body,hash:digest(body)}));expect((await store.status()).readOnly).toBe(true);
});
test('pure selling posting recognises revenue only at dispatch, using historical deposit FX',async()=>{
  const input=await etsy();if(input.action!=='etsy')throw Error('fixture');const order=parseOrders(input)[0]!;const fx={id:'synthetic-public-fx',date:order.orderDate,currency:'USD',rate:'32.0000',source:'public',evidenceRef:'synthetic-public-rate'};
  const placed=placeOrder(order,fx,randomUUID());expect(placed.lines.map(line=>line.account.code)).toEqual(['1191','2211']);expect(placed.lines[0]?.debit).toBe('907.8400');
  const shipped=dispatchOrder(order,fx,'2025-12-29',randomUUID());expect(shipped.lines.map(line=>line.account.code)).toEqual(['2211','4111','4181','4191']);expect(shipped.lines[0]?.debit).toBe('907.8400');expect(shipped.lines[1]?.credit).toBe('831.3600');expect(shipped.lines[2]?.credit).toBe('159.6800');expect(shipped.lines[3]?.debit).toBe('83.2000');
  expect(()=>dispatchOrder(order,{...fx,date:'2025-12-29'},'2025-12-29',randomUUID())).toThrow(/original deposit/);
});
test('statement canonical identity preserves identical-row occurrences',async()=>{const input=await etsy();if(input.action!=='etsy')throw Error('fixture');const sanitized=normalizeSelling(input);if(sanitized.action!=='etsy')throw Error('fixture');const parsed=parseStatement(sanitized,'2025-12');const row=sanitized.statementCsv.split('\n').find(line=>line.includes('Listing Fee'))!;const duplicate=parseStatement({...sanitized,statementCsv:sanitized.statementCsv+row+'\n'},'2025-12');expect(duplicate.multisetDigest).not.toBe(parsed.multisetDigest);expect(duplicate.rows.some(item=>item.key.endsWith('#2'))).toBe(true);});
