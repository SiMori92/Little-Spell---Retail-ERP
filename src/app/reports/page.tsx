import Link from 'next/link';
import { store } from '@/server/runtime';
import { operatingReports } from '@/domain/operating-reports';
import { buildReports } from '@/domain/reporting';
import { dashboard } from '@/domain/dashboard';
import { closeGates } from '@/domain/closing';
import { periodSchema } from '@/domain/schemas/accounting';
import { FinancialTable } from '@/components/financial-table';
import { KpiStrip,DashboardCharts } from '@/components/dashboard';
export const runtime='nodejs';
export const dynamic='force-dynamic';
export default async function Reports({searchParams}:{searchParams:Promise<{period?:string;report?:string}>}){
 const params=await searchParams,today=new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Taipei'}),period=periodSchema.parse(params.period??today.slice(0,7)),status=await store.status(),runs=status.readOnly?[]:await store.read(),reports=[...buildReports(runs,period),...operatingReports(runs,period)],data=dashboard(runs,period,today),gates=closeGates(runs,period),selected=reports.find(r=>r.slug===params.report);
 return <><div className="page-heading"><div><p className="eyebrow">Same records. Useful answers.</p><h1>Reports</h1><p className="muted">{period} · posted ledger and evidenced operational projections</p></div></div><KpiStrip data={data}/><nav className="setup-actions"><Link className="button secondary" href={`/reports?period=${period}`}>Dashboard</Link>{reports.map(r=><Link className="button secondary" key={r.slug} href={`/reports?period=${period}&report=${r.slug}`}>{r.title}</Link>)}</nav>{selected?<section className="card"><h2>{selected.title}</h2>{selected.notes.map(n=><p className="note" key={n}>{n}</p>)}{selected.rows.length?<FinancialTable label={selected.slug} rows={selected.rows.map(row=>({_dataset:selected.dataset,_period:selected.period,...Object.fromEntries(Object.entries(row).map(([key,value])=>[key,typeof value==='string'?value:value.amount===null?`ABSENT — ${value.reason}`:`${value.amount}${value.basis==='provisional'?` · PROVISIONAL: ${value.reason}`:''}`]))}))}/>:<p className="muted">No posted evidence for this report. <Link href="/money?action=expense">Record your first expense</Link> · <Link href="/money#money-guide">Three-step guide</Link></p>}</section>:<><div className="gate-lights">{gates.map(g=><Link className="gate" href={`/close?period=${period}`} key={g.gate}><span className="light" style={{background:g.status==='PASS'?'var(--primary)':g.status==='FAIL'?'var(--danger)':'var(--warn)'}}/>{g.gate} {g.status}</Link>)}</div><DashboardCharts data={data}/></>}<p className="note">ABSENT means required evidence is missing. It never means zero. Financial parity against the reference is tracked separately.</p></>;
}
