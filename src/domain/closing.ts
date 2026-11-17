import type { Candidate,Run } from './schemas';
import { candidateSchema } from './schemas';
import { closePayloadSchema } from './schemas/closing';
import { gateSchema,type Gate } from './schemas/reporting';
import { accountingState,datasetOf,pendingAccounting } from './accounting';
import { buildReports,contributionOrders,contributionAccounts,ledger,net,periodEnd,settlementAging } from './reporting';
import { projectProcurement } from './procurement-projection';
import { projectSelling } from './selling-projection';
import { approvedChartRows } from './chart';
import { canonical } from './canonical';
import Decimal from './decimal';
import { DomainError } from './errors';
const result=(gate:Gate['gate'],status:Gate['status'],reason:string,details:unknown={}):Gate=>gateSchema.parse({gate,status,reason,details});
export function closeGates(runs:readonly Run[],period:string):Gate[]{
 const end=periodEnd(period),pending=[...pendingAccounting(runs,'SAMPLE'),...pendingAccounting(runs,'ACTUAL')].filter(e=>e.date<=end&&e.status==='UNPOSTED'),state=accountingState(runs),sell=projectSelling(runs),all=ledger(runs,period).flatMap(e=>e.entry.lines);
 const aging=settlementAging(runs,period),old=aging.filter(i=>i.account!=='2205'&&i.businessDays>15&&!i.cause),tax=net(all,['2205']),deposit=projectProcurement(runs,undefined,new Date(new Date(`${end}T00:00:00Z`).getTime()-86400000).toISOString().slice(0,10)).orders.filter(o=>['received','short_closed','cancelled'].includes(o.status)&&!new Decimal(o.openDepositTwd).isZero());
 const settlement=sell.events.some(e=>e.eventType==='settlement.received'&&e.occurredOn<end&&state.posted.some(p=>p.eventId===e.eventId));
 const inventory=buildReports(runs,period).find(r=>r.slug==='inventory')!,gaps=inventory.rows.filter(r=>r.identity==='UNPROVABLE'),mismatch=inventory.rows.filter(r=>r.identity==='MISMATCH'),untagged=all.some(l=>['1231','1232','1233'].includes(l.account.code)&&!l.sku);
 const orders=contributionOrders(runs,period),contributionMissing=orders.some(o=>o.contribution.amount===null),orderSum=orders.reduce((s,o)=>s.plus(o.contribution.amount??'0'),new Decimal(0)),ledgerSum=net(ledger(runs,period,undefined,true).flatMap(e=>e.entry.lines),contributionAccounts,true);
 const expectedSku=new Map<string,InstanceType<typeof Decimal>>();
 for(const order of orders){const weighted=[...order.weights].sort(([a],[b])=>a.localeCompare(b)),total=weighted.reduce((s,[,w])=>s.plus(w),new Decimal(0));if(total.lte(0))continue;
  for(const [name,figure]of Object.entries(order.parts)){if(figure.amount===null)continue;if(name==='cogs'){const event=sell.events.find(e=>e.eventType==='order.cogs_relieved'&&e.entityRef===order.orderId),entryId=state.posted.find(p=>p.eventId===event?.eventId)?.entryId;for(const line of state.entries.find(e=>e.entry.entryId===entryId)?.entry.lines??[])if(line.account.code==='5111'&&line.sku)expectedSku.set(line.sku,(expectedSku.get(line.sku)??new Decimal(0)).minus(line.debit).plus(line.credit));continue;}
   let left=new Decimal(figure.amount);for(const [index,[sku,weight]]of weighted.entries()){const share=index===weighted.length-1?left:new Decimal(new Decimal(figure.amount).times(weight).div(total).toFixed(4));left=left.minus(share);expectedSku.set(sku,(expectedSku.get(sku)??new Decimal(0)).plus(share.times(['product','shipping'].includes(name)?1:-1)));}
  }
 }
 const actualSku=buildReports(runs,period).find(r=>r.slug==='contribution-skus')!.rows,skuMismatch=[...expectedSku].filter(([sku,value])=>{const row=actualSku.find(r=>r.sku===sku);return !row||typeof row.contribution==='string'||row.contribution?.amount===null||!value.eq(row.contribution!.amount!);}).map(([sku])=>sku);
 const contributionMismatch=!orderSum.eq(ledgerSum)||skuMismatch.length>0||expectedSku.size!==actualSku.length;
 const badAccounts=approvedChartRows.filter(a=>/suspense|rounding|difference/i.test(a.account_name_en)),badLines=all.filter(l=>/to balance|difference|adjust/i.test(l.memo??'')&&!l.sourceRef),estimates=all.filter(l=>l.memo?.includes('[ESTIMATE]')&&!/\bbasis:\s*\S/i.test(l.memo));
 return [result('G-1',pending.length?'FAIL':'PASS',pending.length?'Unposted facts remain in the ops or manual stream.':'Both event streams are posted.',{ops:pending.filter(e=>e.stream==='ops').length,manual:pending.filter(e=>e.stream==='manual').length}),
 result('G-2',deposit.length?'FAIL':!settlement?'NOT_RUNNABLE':old.length||!new Decimal(tax).isZero()?'FAIL':'PASS',deposit.length?'Supplier deposits remain on received or cancelled orders.':!settlement?'Q-1 OPEN: no posted TWD settlement source; aging cannot be certified.':old.length||!new Decimal(tax).isZero()?'Unexplained aging over 15 business days or uncleared platform tax.':'Rail aging explained and platform tax exactly zero.',{aging,depositBalances:deposit.map(o=>({po:o.record.poNumber,amount:o.openDepositTwd})),platformTaxTwd:tax}),
 result('G-3',!inventory.rows.length||gaps.length||untagged?'NOT_RUNNABLE':mismatch.length?'FAIL':'PASS',!inventory.rows.length||gaps.length||untagged?'Posted opening, valued moves, independent journal quantity or SKU attribution missing.':mismatch.length?'Stock quantity or value differs from the ledger.':'SKU quantity and value tie exactly.',{rows:inventory.rows}),
 result('G-4',!orders.length||contributionMissing?'NOT_RUNNABLE':contributionMismatch?'FAIL':'PASS',!orders.length||contributionMissing?'Dispatched orders or contribution inputs are ABSENT.':contributionMismatch?'Order contribution or independent gross-share SKU allocation differs.':'Orders, SKU allocations and period contribution tie.',{ordersTwd:orderSum.toFixed(4),ledgerTwd:ledgerSum,skuMismatches:skuMismatch}),
 result('G-5',badAccounts.length||badLines.length||estimates.length?'FAIL':'PASS',badAccounts.length||badLines.length||estimates.length?'Prohibited account, unreferenced correction or unsupported estimate.':'No plug account or unsupported estimate.',{prohibitedAccounts:badAccounts.map(a=>a.account_code),unreferencedLines:badLines.length,unsupportedEstimates:estimates.length})];
}
export function workdayAfter(date:string,count:number){const d=new Date(`${date}T00:00:00Z`);let passed=0;while(passed<count){d.setUTCDate(d.getUTCDate()+1);if(d.getUTCDay()%6!==0)passed++;}return d.toISOString().slice(0,10);}
export function planClose(raw:unknown,runs:readonly Run[]):Candidate{
 const input=closePayloadSchema.parse(raw),dataset=datasetOf(runs),existing=runs.find(r=>r.kind==='close.record'&&r.idempotencyKey===input.idempotencyKey);
 if(existing){if(canonical(existing.input)!==canonical(input))throw new DomainError('idempotencyKey','This request key was used for different close evidence.');return {kind:existing.kind,occurredOn:existing.occurredOn,dataset:existing.dataset,input:existing.input,effects:existing.effects,idempotencyKey:existing.idempotencyKey};}
 if(input.expectedHeadHash&&input.expectedHeadHash!==(runs.at(-1)?.hash??'0'.repeat(64)))throw new DomainError('expectedHeadHash','Records changed. Recompute the checks before confirmation.');
 if(input.occurredOn>new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Taipei'}))throw new DomainError('occurredOn','Record a close review or attempt on a date that has already arrived.');
 if(runs.some(r=>r.dataset===dataset&&r.effects.some(e=>e.type==='period.closed'&&e.period===input.period)))throw new DomainError('period','This month is already closed.');
 const end=periodEnd(input.period),last=new Date(new Date(`${end}T00:00:00Z`).getTime()-86400000).toISOString().slice(0,10),reviews=runs.filter(r=>r.dataset===dataset).flatMap(r=>r.effects.filter(e=>e.type==='close.reviewed'&&e.period===input.period));
 if(input.occurredOn<workdayAfter(last,input.action==='review'?1:3))throw new DomainError('period','Wait until the scheduled workday after month end.');
 let effects:Candidate['effects'];
 if(input.action==='review'){
  if(reviews.length||ledger(runs,input.period).some(e=>e.entry.occurredOn.startsWith(input.period)))throw new DomainError('period','Input review must be recorded once, before any journal in this month.');
  effects=[{type:'close.reviewed',period:input.period,actor:input.actor,evidenceRef:input.evidenceRef}];
 }else{
  let stopped=reviews.length?'':'WD+1 input-review signoff';const gates=closeGates(runs,input.period).map(g=>{if(stopped)return result(g.gate,'NOT_RUNNABLE',`Not run after ${stopped}.`);if(g.status!=='PASS')stopped=g.gate;return g;}),remaining=gates.filter(g=>g.status!=='PASS').map(g=>`${g.gate}: ${g.reason}`);if(!reviews.length)remaining.unshift('WD+1 input-review signoff is missing.');
  const passed=remaining.length===0;effects=[{type:'close.attempted',period:input.period,actor:input.actor,founderAuthorization:input.founderAuthorization,gates,status:passed?'CLOSED':'BLOCKED',remaining}];
  if(passed)effects.push({type:'period.closed',period:input.period,founderAuthorization:input.founderAuthorization,gates:gates.map(g=>({gate:g.gate,status:g.status,evidenceRef:input.evidenceRef}))});
 }
 return candidateSchema.parse({kind:'close.record',occurredOn:input.occurredOn,dataset,input,effects,idempotencyKey:input.idempotencyKey});
}
export function validateClose(candidate:Candidate,runs:readonly Run[]){if(canonical(planClose(candidate.input,runs))!==canonical(candidate))throw new DomainError('record','Close results must be recomputed from the recorded evidence.');}
