import Link from 'next/link';
import { randomUUID } from 'node:crypto';
import { store } from '@/server/runtime';
import { approvedChartRows } from '@/domain/chart';
import { FinancialFlow } from '@/components/financial-flow';
import { ReversalFlow } from '@/components/reversal-flow';
import { PageHeading } from '@/components/page-heading';
export const runtime='nodejs';
export const dynamic='force-dynamic';
export default async function Dataset({searchParams}:{searchParams:Promise<{action?:string}>}){
 const params=await searchParams,status=await store.status(),runs=status.readOnly?[]:await store.read(),fields={occurredOn:new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Taipei'}),idempotencyKey:randomUUID(),expectedHeadHash:null,founderAuthorization:'',evidenceRef:''};
 const seeds=runs.filter(r=>r.kind==='sample.seed'&&!runs.some(other=>other.effects.some(e=>e.type==='run.reversed'&&e.originalRunId===r.runId)));
 return <><PageHeading compact eyebrow="Setup · dataset" title="Dataset transition" description={`Current workspace: ${status.dataset}. Actual data starts with its own opening and empty masters.`} action={<Link href="/setup">Back to setup</Link>}/><p className="note">This transition does not certify financial parity or resolve missing source contracts. Keep the reference until a real month has closed with all gates green.</p>{status.dataset==='ACTUAL'?<p>ACTUAL is active. Return to Setup to record your real business and product masters.</p>:<>{params.action==='opening'?<FinancialFlow initial={{action:'actual-opening',...fields,lines:[{account:'1121',debit:'',credit:'0.0000'},{account:'3111',debit:'0.0000',credit:''}]}} readOnly={status.readOnly} accounts={approvedChartRows.filter(a=>a.is_reserved!=='true'&&!a.account_code.startsWith('123')).map(a=>({code:a.account_code,label:`${a.account_name_en} / ${a.account_name_zh}`}))}/>:params.action==='activate'?<FinancialFlow initial={{action:'activate',...fields}} readOnly={status.readOnly}/>:<><section className="card"><h2>1. Reverse the SAMPLE seed</h2>{seeds.map(seed=><ReversalFlow key={seed.runId} originalRunId={seed.runId}/>)}{!seeds.length&&<p>Seed reversal is already recorded.</p>}</section><nav className="setup-actions"><Link className="button secondary" href="/setup/dataset?action=opening">2. Record real opening</Link><Link className="button" href="/setup/dataset?action=activate">3. Review activation</Link></nav></>}</>}<Link href="/setup">Back to Setup</Link></>;
}
