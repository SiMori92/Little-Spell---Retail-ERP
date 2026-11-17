import { accountingPayloadSchema, accountingFactSchema, fxSchema, type AccountingFact } from './schemas/accounting';
import { candidateSchema, journalSchema, type Candidate, type Effect, type Journal, type Run, type Dataset } from './schemas';
import { approvedChartRows } from './chart';
import Decimal from './decimal';
import { exactMoney as money } from './landed-cost';
import { canonical,digest } from './canonical';
import { DomainError } from './errors';
import { projectSelling } from './selling-projection';
import { projectInventory } from './inventory-projection';
import { placeOrder,dispatchOrder } from './posting/selling';
import { parseExpenses } from './expense-csv';
import { projectMasters } from './master-projection';
export const datasetOf=(runs:readonly Run[]):Dataset=>runs.some(r=>r.effects.some(e=>e.type==='dataset.activated'))?'ACTUAL':'SAMPLE';
export const stableId=(value:unknown)=>{const h=digest(value);return `${h.slice(0,8)}-${h.slice(8,12)}-4${h.slice(13,16)}-a${h.slice(17,20)}-${h.slice(20,32)}`;};
export function accountLeg(code:string,debit:string,credit:string,extra:Partial<Journal['lines'][number]>={}){
 const a=approvedChartRows.find(a=>a.account_code===code);if(!a||a.is_reserved==='true'||a.is_closing_only==='true')throw new DomainError('account','Choose an active approved account.');
 return {account:{code,name:a.account_name_en},debit:money(debit),credit:money(credit),txnAmount:null,txnCurrency:null,fxRateId:null,...extra};
}
export function accountingState(runs:readonly Run[],dataset:Dataset=datasetOf(runs)){
 const scoped=runs.filter(r=>r.dataset===dataset),effects=scoped.flatMap(r=>r.effects);
 return {dataset,rates:effects.flatMap(e=>e.type==='accounting.fx'?[e.record]:[]),facts:effects.flatMap(e=>e.type==='accounting.fact'?[e.record]:[]),posted:effects.flatMap(e=>e.type==='accounting.posted'?[e]:[]),reversed:effects.flatMap(e=>e.type==='accounting.reversed'?[e]:[]),causes:effects.flatMap(e=>e.type==='accounting.cause'?[e]:[]),entries:scoped.flatMap(r=>r.effects.flatMap(e=>e.type==='journal.posted'?[{runId:r.runId,entry:e.entry}]:[]))};
}
export function inventoryTags(runs:readonly Run[]){
 const tags:{entryId:string;lineIndex:number;sku:string;qtyPieces:string|null}[]=[];
 for(const run of runs.filter(r=>r.dataset===datasetOf(runs)))for(const effect of run.effects){
  if(effect.type==='procurement.matched'){
   const entry=run.effects.find(e=>e.type==='journal.posted'&&e.entry.entryId===effect.record.journalId);if(entry?.type!=='journal.posted')continue;let index=0;
   for(const row of effect.record.lines){if(!new Decimal(row.goodValue).isZero()){tags.push({entryId:entry.entry.entryId,lineIndex:index++,sku:row.sku,qtyPieces:row.qtyGood});}if(!new Decimal(row.damagedValue).isZero())tags.push({entryId:entry.entry.entryId,lineIndex:index++,sku:row.sku,qtyPieces:null});}
  }
  if(effect.type==='procurement.count'){
   const entry=run.effects.find(e=>e.type==='journal.posted'&&['inventory.opening_counted','inventory.adjusted'].includes(e.entry.sourceEvent));if(entry?.type!=='journal.posted')continue;
   const rows=run.effects.flatMap(e=>e.type==='procurement.movement'?[e.record]:[]);for(const [index,row]of rows.entries()){const opening=effect.kind==='opening';tags.push({entryId:entry.entry.entryId,lineIndex:index*2+(opening?0:1),sku:row.sku,qtyPieces:row.qtyPieces});tags.push({entryId:entry.entry.entryId,lineIndex:index*2+(opening?1:0),sku:row.sku,qtyPieces:null});}
  }
 }
 const adopted=accountingState(runs).entries.flatMap(e=>runs.flatMap(r=>r.effects.flatMap(x=>x.type==='accounting.inventory-tags'?x.tags.filter(t=>t.entryId===e.entry.entryId):[])));
 return tags.filter(t=>!adopted.some(a=>a.entryId===t.entryId&&a.lineIndex===t.lineIndex));
}
export function pendingAccounting(runs:readonly Run[],dataset:Dataset=datasetOf(runs)){
 const state=accountingState(runs,dataset),sell=projectSelling(runs,dataset);
 return [...sell.events.map(e=>({id:e.eventId,date:e.occurredOn,label:e.eventType,reference:e.eventType==='order.fees_assessed'?e.payload.order_id:e.eventType==='cost.recorded'?`Listing fees ${e.occurredOn}`:e.entityRef,stream:'ops' as const})),...state.facts.map(f=>({id:f.id,date:f.date,label:f.detail.kind==='manual'?f.detail.record.eventType:f.detail.kind,reference:f.evidenceRef,stream:'manual' as const}))].map(e=>({...e,status:state.posted.some(p=>p.eventId===e.id)?'POSTED':'UNPOSTED'}));
}
export function planFactJournal(fact:AccountingFact,runs:readonly Run[]):Journal|null{
 const state=accountingState(runs),d=fact.detail;
 let lines:Journal['lines']=[],eventType:string=d.kind;
 const pair=(debit:string,credit:string,amount:string)=>[accountLeg(debit,amount,'0'),accountLeg(credit,'0',amount)];
 const invoice=(id:string,kind:'freight-accrual'|'duty',amount:string)=>{
   const old=state.facts.find(f=>f.id===id);if(!old||old.detail.kind!==kind||!state.posted.some(e=>e.eventId===id))throw new DomainError('originalId','Choose the posted original accrual.');
   if(state.facts.some(f=>f.id!==fact.id&&((f.detail.kind==='freight-invoice'||f.detail.kind==='duty-invoice')&&f.detail.originalId===id)))throw new DomainError('originalId','This accrual already has an invoice.');
   const base=old.detail.amount,expense=kind==='duty'?'6132':'6131',liability=kind==='duty'?'2192':'2191',delta=new Decimal(amount).minus(base);
   const result=[accountLeg(liability,base,'0'),accountLeg('2172','0',amount)];if(!delta.isZero())result.push(accountLeg(expense,delta.gt(0)?delta.toFixed(4):'0',delta.lt(0)?delta.negated().toFixed(4):'0'));return result;
 };
 if(d.kind==='manual'){
  const r=d.record;eventType=r.eventType;
  switch(r.eventType){
   case 'owner.funds_moved':{const codes={capital:['1121','3111'],drawings:['3211','1121'],loan:['1121','2281']} as const;const [debit,credit]=codes[r.fundsType];lines=pair(debit,credit,r.amount);break;}
   case 'tax.assessed':lines=pair('6182','2194',r.amount);break;
   case 'tax.paid':lines=pair('2194','1121',r.amount);break;
   case 'period.accrued':if(!approvedChartRows.some(a=>a.account_code===r.expenseAccount&&a.statement==='PL'&&a.normal_balance==='debit'))throw new DomainError('expenseAccount','Choose an expense account.');lines=pair(r.expenseAccount,r.accrualAccount,r.amount).map(l=>({...l,memo:`[ESTIMATE] basis: ${r.basisNote}`}));break;
   case 'period.revalued':if(['1231','1232','1233'].includes(r.account))throw new DomainError('account','Stock cannot be revalued.');lines=r.direction==='loss'?pair('7112',r.account,r.amount):pair(r.account,'7112',r.amount);break;
   case 'period.accrual_reversed':{const old=state.facts.find(f=>f.id===r.originalId);if(!old||old.detail.kind!=='manual'||old.detail.record.eventType!=='period.accrued'||!state.posted.some(p=>p.eventId===old.id))throw new DomainError('originalId','Choose a posted accrual to reverse.');if(state.facts.some(f=>f.id!==fact.id&&f.detail.kind==='manual'&&f.detail.record.eventType==='period.accrual_reversed'&&f.detail.record.originalId===old.id))throw new DomainError('originalId','This accrual already has a reversal.');lines=pair(old.detail.record.accrualAccount,old.detail.record.expenseAccount,old.detail.record.amount);break;}
  }
 }else if(d.kind==='expense'){
  const r=d.record,codes={rent:'6151',software:'6161',professional:'6162',utilities:'6163',wages:'6171',bank_fee:'6181',other:'6199',advertising:({etsy:'6141',meta:'6142',other:'6143','':''})[r.channel]};
  eventType='cost.recorded';lines=pair(codes[r.category],r.settledVia==='payable'?'2173':r.bankAccount,r.amountTwd);
 }else if(d.kind==='freight-accrual'){eventType='order.ship_cost_accrued';lines=pair('6131','2191',d.amount).map(l=>({...l,memo:`[ESTIMATE] basis: ${d.basisNote}`}));}
 else if(d.kind==='freight-invoice'){eventType='order.ship_cost_invoiced';lines=invoice(d.originalId,'freight-accrual',d.amount);}
 else if(d.kind==='duty'){eventType='order.duty_incurred';if(d.position!=='DDP')return null;if(new Decimal(d.amount).lte(0))throw new DomainError('amount','Enter the evidenced duty amount.');lines=pair('6132','2192',d.amount);}
 else {eventType='order.duty_invoiced';lines=invoice(d.originalId,'duty',d.amount);}
 return journalSchema.parse({entryId:stableId(['fact',fact.id]),occurredOn:fact.date,sourceEvent:eventType,lines:lines.map(l=>({...l,sourceRef:fact.evidenceRef}))});
}
export function planExistingJournal(eventId:string,runs:readonly Run[]):Journal|null{
 const state=accountingState(runs),fact=state.facts.find(f=>f.id===eventId);if(fact)return planFactJournal(fact,runs);
 const sell=projectSelling(runs),event=sell.events.find(e=>e.eventId===eventId);if(!event)throw new DomainError('eventId','Choose an existing accounting fact.');
 const order=sell.orders.find(o=>o.record.orderId===event.entityRef)?.record,entryId=stableId(['selling-post',eventId]);
 const rateDate=event.eventType==='order.shipped'?order?.orderDate:event.occurredOn;
 const rate=state.rates.find(r=>r.date===rateDate&&r.currency==='USD');
 if(event.eventType==='settlement.received')throw new DomainError('eventId','The Etsy deposit has no proven bank credit and cleared-item composition. Record source evidence before settlement can be posted.');
 if(event.eventType==='order.cogs_relieved'){
  const shipped=sell.events.find(e=>e.entityRef===event.entityRef&&e.eventType==='order.shipped');if(!shipped||!state.posted.some(p=>p.eventId===shipped.eventId))throw new DomainError('eventId','Post dispatch revenue before its stock cost.');
  const rows=projectInventory(runs).consumptions.filter(c=>c.orderId===event.entityRef);if(!rows.length)throw new DomainError('stock','Counted and valued dispatch stock is missing.');
  return journalSchema.parse({entryId,occurredOn:event.occurredOn,sourceEvent:event.eventType,lines:rows.flatMap(c=>[accountLeg('5111',c.costTwd,'0',{sku:c.sku}),accountLeg('1231','0',c.costTwd,{sku:c.sku,qtyPieces:new Decimal(c.qtyPieces).negated().toFixed(0)})])});
 }
 if(!rate)throw new DomainError('fx','Record the Bank of Taiwan public rate for this transaction date first.');
 const fx={...rate,source:'public' as const},saleFx={id:fx.id,date:fx.date,currency:'USD' as const,rate:fx.rate,source:fx.source,evidenceRef:fx.evidenceRef};
 if(event.eventType==='order.placed'){if(!order)throw new DomainError('order','Order facts are missing.');return placeOrder(order,saleFx,entryId);}
 if(event.eventType==='order.shipped'){
  const placed=sell.events.find(e=>e.entityRef===event.entityRef&&e.eventType==='order.placed');if(!order||!placed||!state.posted.some(p=>p.eventId===placed.eventId))throw new DomainError('eventId','Post the customer deposit before dispatch revenue.');
  return dispatchOrder(order,saleFx,event.occurredOn,entryId);
 }
 const translated=(amount:string)=>money(new Decimal(amount).times(rate.rate));
 const leg=(code:string,amount:string,debit:boolean)=>accountLeg(code,debit?translated(amount):'0',debit?'0':translated(amount),{txnAmount:money(amount),txnCurrency:'USD',fxRateId:rate.id});
 let lines:Journal['lines'];
 if(event.eventType==='order.fees_assessed'){
  const map={transaction_fee:'6111',payment_processing_fee:'6112',offsite_ads_fee:'6113',regulatory_operating_fee:'6114'};
  lines=event.payload.fee_components.flatMap(c=>[leg(map[c.code],c.amount,true),leg('1191',c.amount,false)]);
 }else if(event.eventType==='cost.recorded'&&event.amount){lines=[leg('6115',event.amount,true),leg('1191',event.amount,false)];}
 else throw new DomainError('eventId','This fact has no complete posting rule or source.');
 return journalSchema.parse({entryId,occurredOn:event.occurredOn,sourceEvent:event.eventType,lines});
}
export function planAccounting(raw:unknown,runs:readonly Run[]):Candidate{
 const input=accountingPayloadSchema.parse(raw),dataset=datasetOf(runs),state=accountingState(runs);
 if(input.action==='import-receipts'){const prior=runs.find(r=>r.dataset===dataset&&r.effects.some(e=>e.type==='accounting.receipt-import'&&e.sourceHash===digest(input.csvText)));if(prior)return {kind:prior.kind,occurredOn:prior.occurredOn,dataset:prior.dataset,input:prior.input,effects:prior.effects,idempotencyKey:prior.idempotencyKey};}
 const previous=runs.find(r=>r.kind==='accounting.record'&&r.idempotencyKey===input.idempotencyKey);if(previous){if(canonical(previous.input)!==canonical(input))throw new DomainError('idempotencyKey','This request key was already used.');return {kind:previous.kind,occurredOn:previous.occurredOn,dataset:previous.dataset,input:previous.input,effects:previous.effects,idempotencyKey:previous.idempotencyKey};}
 if(input.expectedHeadHash&&input.expectedHeadHash!==(runs.at(-1)?.hash??'0'.repeat(64)))throw new DomainError('expectedHeadHash','Records changed. Preview this action again.');
 let effects:Effect[]=[];
 if(input.action==='reorder'){
  if(!projectMasters(runs).products.some(p=>p.record.sku===input.record.sku&&p.record.productType==='sellable'))throw new DomainError('sku','Choose a recorded sellable product.');effects=[{type:'accounting.stock-policy',record:input.record}];
 }else if(input.action==='import-receipts'){
  const receipts=parseExpenses(input.csvText,input.filename,dataset),fresh=receipts.filter(record=>{const prior=state.facts.find(f=>f.evidenceRef===record.evidenceRef);if(prior&&(prior.detail.kind!=='expense'||canonical(prior.detail.record)!==canonical(record)))throw new DomainError('evidenceRef','Previously recorded receipt evidence has changed.');return !prior;});
  if(!fresh.length)throw new DomainError('csvText','Every receipt is already recorded. No new fact is needed.');
  effects=[{type:'accounting.receipt-import',sourceHash:digest(input.csvText),records:fresh.length},...fresh.map(record=>({type:'accounting.fact' as const,record:accountingFactSchema.parse({id:digest(['fact',dataset,record.evidenceRef]),date:record.date,evidenceRef:record.evidenceRef,detail:{kind:'expense',record}})}))];
 }else if(input.action==='fx'){
  const record=fxSchema.parse({id:digest(['fx',dataset,input.date,input.currency]),date:input.date,currency:input.currency,rate:input.rate,evidenceRef:input.evidenceRef,source:'Bank of Taiwan'});
  if(state.rates.some(r=>r.date===record.date&&r.currency===record.currency))throw new DomainError('rate','This public rate is already recorded. Investigate conflicting evidence; do not overwrite it.');effects=[{type:'accounting.fx',record}];
 }else if(input.action==='manual'||input.action==='expense'||input.action==='fact'){
  const detail=input.action==='manual'?{kind:'manual' as const,record:input.record}:input.action==='expense'?{kind:'expense' as const,record:input.record}:input.detail;
  const evidenceRef=input.action==='expense'?input.record.evidenceRef:input.evidenceRef;
  if(state.facts.some(f=>f.evidenceRef===evidenceRef))throw new DomainError('evidenceRef','This evidence already has a recorded fact.');
  const record=accountingFactSchema.parse({id:digest(['fact',dataset,evidenceRef]),date:input.occurredOn,evidenceRef,detail});
  if(detail.kind==='expense'&&detail.record.date!==input.occurredOn)throw new DomainError('date','Use the receipt date for this action.');
  if((detail.kind==='freight-accrual'||detail.kind==='duty')&&!projectSelling(runs).orders.some(o=>o.record.orderId===detail.orderId))throw new DomainError('orderId','Choose a recorded order.');
  planFactJournal(record,runs);effects=[{type:'accounting.fact',record}];
 }else if(input.action==='inventory-evidence'){
  const tags=inventoryTags(runs);if(!tags.length)throw new DomainError('evidenceRef','No untagged sourced purchasing journals remain.');effects=[{type:'accounting.inventory-tags',tags,evidenceRef:input.evidenceRef}];
 }else if(input.action==='post'){
  if(state.posted.some(e=>e.eventId===input.eventId))throw new DomainError('eventId','This fact has already been posted.');
  const journal=planExistingJournal(input.eventId,runs),eventDate=state.facts.find(f=>f.id===input.eventId)?.date??projectSelling(runs).events.find(e=>e.eventId===input.eventId)?.occurredOn;
  if(input.occurredOn!==eventDate)throw new DomainError('occurredOn','Post using the original fact date. Closed months cannot accept a backdated posting.');
  effects=[{type:'accounting.posted',eventId:input.eventId,entryId:journal?.entryId??null,memo:journal?'Reviewed and posted':'No financial entry: duty position DDU or unknown'},...(journal?[{type:'journal.posted' as const,entry:journal,opening:null,founderAuthorization:null}]:[])];
 }else if(input.action==='cause'){
  const line=state.entries.flatMap(e=>e.entry.lines.map((l,i)=>({line:l,id:`${e.entry.entryId}:${i}`}))).find(l=>l.id===input.lineId);if(!line||!['1191','1192','1193'].includes(line.line.account.code)||state.causes.some(c=>c.lineId===input.lineId))throw new DomainError('lineId','Choose a clearing line without an existing cause.');effects=[{type:'accounting.cause',lineId:input.lineId,cause:input.cause,evidenceRef:input.evidenceRef,actor:input.actor}];
 }else{
  const original=state.entries.find(e=>e.entry.entryId===input.entryId);
  if(!original||state.reversed.some(e=>e.entryId===input.entryId))throw new DomainError('entryId','Choose an unreversed posted entry.');
  const originalRun=runs.find(r=>r.runId===original.runId);
  if(originalRun?.kind!=='accounting.record'||original.entry.lines.some(l=>l.account.code.startsWith('123')))throw new DomainError('entryId','This operational record needs its own stock and document reversal workflow.');
  if(input.occurredOn<original.entry.occurredOn)throw new DomainError('occurredOn','Date a correction on or after the original.');
  const reversalId=stableId(['reverse',input.entryId]);
  const entry=journalSchema.parse({...original.entry,entryId:reversalId,occurredOn:input.occurredOn,sourceEvent:'entry.reversed',lines:original.entry.lines.map(l=>({...l,debit:l.credit,credit:l.debit,txnAmount:l.txnAmount===null?null:money(new Decimal(l.txnAmount).negated()),memo:input.reason}))});
  effects=[{type:'accounting.reversed',entryId:input.entryId,reversalId,reason:input.reason},{type:'journal.posted',entry,opening:null,founderAuthorization:null}];
 }
 return candidateSchema.parse({kind:'accounting.record',occurredOn:input.occurredOn,dataset,input:structuredClone(input),idempotencyKey:input.idempotencyKey,effects:structuredClone(effects)});
}
export function validateAccounting(candidate:Candidate,runs:readonly Run[]){const planned=planAccounting(candidate.input,runs);if(canonical(planned)!==canonical(candidate))throw new DomainError('record','Accounting effects do not match their source facts.');}
