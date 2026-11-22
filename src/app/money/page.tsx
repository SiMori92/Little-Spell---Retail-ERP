import Link from 'next/link';
import { randomUUID } from 'node:crypto';
import { notFound } from 'next/navigation';
import { z } from 'zod';
import { store } from '@/server/runtime';
import { accountingState,pendingAccounting } from '@/domain/accounting';
import { accountingPayloadSchema } from '@/domain/schemas/accounting';
import { approvedChartRows } from '@/domain/chart';
import { FinancialFlow } from '@/components/financial-flow';
import { FinancialTable } from '@/components/financial-table';
import { ActivityTable } from '@/components/activity-table';
import { PageHeading } from '@/components/page-heading';
import { StatusBadge } from '@/components/ui/workspace';

const actionGroups:[string,[string,string][]][]=[
 ['Owner and exchange rates',[['owner','Move owner funds'],['fx','Record public FX']]],
 ['Month-end estimates',[['accrue','Estimate cost owed'],['reverse-accrual','Reverse accrual'],['revalue','Revalue balance'],['inventory-evidence','Review inventory attribution']]],
 ['Freight and duty',[['freight-accrual','Estimate freight'],['freight-invoice','Record freight invoice'],['duty','Record duty position'],['duty-invoice','Record duty invoice']]],
 ['Tax and clearing',[['tax-assessed','Record tax assessed'],['tax-paid','Record tax paid'],['cause','Explain clearing item']]],
];
export const runtime='nodejs';
export const dynamic='force-dynamic';
export default async function Money({searchParams}:{searchParams:Promise<{action?:string;event?:string;entry?:string;date?:string}>}){
 const params=await searchParams,status=await store.status(),runs=status.readOnly?[]:await store.read(),state=accountingState(runs),queue=pendingAccounting(runs),today=new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Taipei'});
 const fields={occurredOn:params.date??today,idempotencyKey:randomUUID(),expectedHeadHash:null};let initial:z.input<typeof accountingPayloadSchema>|null=null;
 if(params.action){switch(params.action){
 case 'fx':initial={action:'fx',...fields,date:fields.occurredOn,currency:'USD',rate:'',evidenceRef:''};break;
 case 'expense':initial={action:'expense',...fields,record:{date:fields.occurredOn,category:'software',amountTwd:'',settledVia:'bank',bankAccount:'1121',channel:'',description:'',evidenceRef:''}};break;
 case 'post':initial={action:'post',...fields,occurredOn:queue.find(e=>e.id===params.event)?.date??fields.occurredOn,eventId:params.event??''};break;
 case 'reverse':initial={action:'reverse',...fields,entryId:params.entry??'',reason:''};break;
 case 'cause':initial={action:'cause',...fields,lineId:'',cause:'',evidenceRef:'',actor:''};break;
 case 'inventory-evidence':initial={action:'inventory-evidence',...fields,evidenceRef:''};break;
 case 'import-receipts':initial={action:'import-receipts',...fields,filename:'',csvText:''};break;
 case 'reorder':initial={action:'reorder',...fields,record:{sku:'',reorderPoint:'',evidenceRef:''}};break;
 case 'freight-accrual':initial={action:'fact',...fields,evidenceRef:'',detail:{kind:'freight-accrual',orderId:'',amount:'',basisNote:''}};break;
 case 'freight-invoice':initial={action:'fact',...fields,evidenceRef:'',detail:{kind:'freight-invoice',originalId:'',amount:''}};break;
 case 'duty':initial={action:'fact',...fields,evidenceRef:'',detail:{kind:'duty',orderId:'',position:'unknown',amount:'0.0000'}};break;
 case 'duty-invoice':initial={action:'fact',...fields,evidenceRef:'',detail:{kind:'duty-invoice',originalId:'',amount:''}};break;
 case 'owner':initial={action:'manual',...fields,evidenceRef:'',record:{eventType:'owner.funds_moved',amount:'',fundsType:'capital'}};break;
 case 'accrue':initial={action:'manual',...fields,evidenceRef:'',record:{eventType:'period.accrued',amount:'',expenseAccount:'6161',accrualAccount:'2193',basisNote:''}};break;
 case 'reverse-accrual':initial={action:'manual',...fields,evidenceRef:'',record:{eventType:'period.accrual_reversed',originalId:params.event??''}};break;
 case 'revalue':initial={action:'manual',...fields,evidenceRef:'',record:{eventType:'period.revalued',amount:'',account:'1191',direction:'gain',rateSource:''}};break;
 case 'tax-assessed':initial={action:'manual',...fields,evidenceRef:'',record:{eventType:'tax.assessed',amount:'',needsProfessionalConfirmation:true}};break;
 case 'tax-paid':initial={action:'manual',...fields,evidenceRef:'',record:{eventType:'tax.paid',amount:''}};break;
 default:notFound();}}
 return <><PageHeading eyebrow="Evidence before balances" title="Money" compact={Boolean(initial)}
  description={initial?'Enter the evidence, review the accounting effects, then confirm. Posting is a separate step.':'Save a fact, review its effects, then post. Corrections preserve the original.'}
  action={initial?<Link href="/money">Back to money</Link>:<><Link className="button" href="/money?action=expense">Record expense</Link><Link className="button secondary" href="/money?action=import-receipts">Import receipts</Link></>}/>{initial?<FinancialFlow key={fields.idempotencyKey} initial={initial} readOnly={status.readOnly} accounts={approvedChartRows.filter(a=>a.is_reserved!=='true').map(a=>({code:a.account_code,label:`${a.account_name_en} / ${a.account_name_zh}`}))}/>:<><div className="summary-strip">
  <section className="card summary-item"><span className="muted">Facts waiting for review</span><strong>{queue.filter(e=>e.status==='UNPOSTED').length}</strong><a href="#review">{queue.filter(e=>e.status==='UNPOSTED').length?'Review before posting':'Nothing waiting'}</a></section>
  <section className="card summary-item"><span className="muted">Posted journals</span><strong>{state.entries.length}</strong><a href="#journals">View journals</a></section>
  <section className="card summary-item"><span className="muted">Working dataset</span><StatusBadge tone={status.dataset==='SAMPLE'?'warning':'neutral'}>{status.dataset}</StatusBadge><Link href="/reports">Open your reports</Link></section>
 </div><section className="card" id="review"><h2>Review before posting</h2>{queue.filter(e=>e.status==='UNPOSTED').map(e=><p key={e.id}><Link className="button secondary" href={`/money?action=post&event=${e.id}`}>Review {e.label} · {e.reference}</Link></p>)}{!queue.length&&<p className="muted">Record your first expense, then review it here.</p>}<FinancialTable label="accounting facts" rows={queue.map(e=>({date:e.date,event:e.label,reference:e.reference,id:e.id,status:e.status}))}/></section><section className="card money-actions" style={{marginTop:24}} aria-labelledby="more-actions"><h2 id="more-actions">Other money actions</h2><div className="action-groups">{actionGroups.map(([title,items])=><div key={title}><p className="eyebrow">{title}</p><ul>{items.map(([action,label])=><li key={action}><Link href={`/money?action=${action}`}>{label}</Link></li>)}</ul></div>)}</div></section><section className="card" id="journals" style={{marginTop:24}}><h2>Posted journals</h2><FinancialTable label="journals" rows={state.entries.map(e=>({date:e.entry.occurredOn,event:e.entry.sourceEvent,reference:e.entry.entryId,status:state.reversed.some(r=>r.entryId===e.entry.entryId)?'REVERSED':'POSTED'}))}/>{state.entries.filter(e=>runs.find(r=>r.runId===e.runId)?.kind==='accounting.record'&&!e.entry.lines.some(l=>l.account.code.startsWith('123'))&&!state.reversed.some(r=>r.entryId===e.entry.entryId||r.reversalId===e.entry.entryId)).map(e=><p key={e.entry.entryId}><Link href={`/money?action=reverse&entry=${e.entry.entryId}`}>Correct {e.entry.sourceEvent} · {e.entry.occurredOn}</Link></p>)}</section><section className="card" style={{marginTop:24}}><h2>Public FX evidence</h2><FinancialTable label="exchange rates" rows={state.rates.map(r=>({date:r.date,currency:r.currency,rate:r.rate,evidence:r.evidenceRef}))}/></section><section className="card" style={{marginTop:24}}><h2>Workspace activity</h2><ActivityTable readOnly={status.readOnly} rows={runs.filter(r=>r.dataset===status.dataset&&!r.kind.startsWith('customer.')).map(r=>({runId:r.runId,kind:r.kind,occurredOn:r.occurredOn,dataset:r.dataset,reversible:r.effects.every(e=>['journal.posted','stock.moved','seed.registered'].includes(e.type))&&r.effects.some(e=>e.type==='journal.posted'||e.type==='stock.moved')&&!runs.some(other=>other.effects.some(e=>e.type==='run.reversed'&&e.originalRunId===r.runId))}))}/></section><details className="card guide-disclosure" id="money-guide"><summary>Three-step mini-guide</summary><p>1. Record the dated voucher or public rate. 2. Review the unposted fact and accounting preview. 3. Post separately; correct an eligible journal with an opposite entry.</p><p className="note">Unresolved settlement composition stays blocked. Operational stock/document reversals require their own flow.</p><Link href="/reports">Open your reports</Link></details></>}</>;
}
