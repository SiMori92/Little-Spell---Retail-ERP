import Link from 'next/link';
import { randomUUID } from 'node:crypto';
import { store } from '@/server/runtime';
import { closeGates } from '@/domain/closing';
import { periodSchema } from '@/domain/schemas/accounting';
import { FinancialFlow } from '@/components/financial-flow';
import { FinancialTable } from '@/components/financial-table';
import { PageHeading } from '@/components/page-heading';
import { CloseChecklist } from '@/components/close-checklist';
export const runtime='nodejs';
export const dynamic='force-dynamic';
export default async function Close({searchParams}:{searchParams:Promise<{period?:string;action?:string}>}){
 const params=await searchParams,today=new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Taipei'}),period=periodSchema.parse(params.period??today.slice(0,7)),status=await store.status(),runs=status.readOnly?[]:await store.read(),gates=closeGates(runs,period),closed=runs.some(r=>r.dataset===status.dataset&&r.effects.some(e=>e.type==='period.closed'&&e.period===period));
 return <><PageHeading eyebrow="Evidence, then a quiet month end" title="Close" compact={params.action==='review'||params.action==='close'}
  description={`${period} · ${closed?'CLOSED':'OPEN'}`}
  action={params.action==='review'||params.action==='close'?<Link href={`/close?period=${period}`}>Back to month-end checks</Link>:<><Link className="button" href={`/close?period=${period}&action=close`}>Review close attempt</Link><Link className="button secondary" href={`/close?period=${period}&action=review`}>Record pre-posting review</Link></>}/>
 {params.action!=='review'&&params.action!=='close'&&<CloseChecklist gates={gates} period={period} closed={closed}/>}
 {params.action==='review'||params.action==='close'?<FinancialFlow initial={{action:params.action,occurredOn:today,period,actor:'',evidenceRef:'',founderAuthorization:'',idempotencyKey:randomUUID(),expectedHeadHash:null}} readOnly={status.readOnly||closed}/>:null}<section className="card" style={{marginTop:24}}><h2>Close history</h2><FinancialTable label="close attempts" rows={runs.filter(r=>r.dataset===status.dataset).flatMap(r=>r.effects.flatMap(e=>e.type==='close.attempted'?[{date:r.occurredOn,period:e.period,status:e.status,actor:e.actor,remaining:e.remaining.join('; ')}]:[]))}/><p className="note">Input review is due WD+1 before posting. Close is due WD+3. Weekdays exclude weekends; no holiday calendar is supplied. Founder authorization is recorded with every attempt.</p></section></>;
}
