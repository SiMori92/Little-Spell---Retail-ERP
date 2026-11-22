import Link from 'next/link';
import { store } from '@/server/runtime';
import { operatingReports } from '@/domain/operating-reports';
import { buildReports } from '@/domain/reporting';
import { dashboard } from '@/domain/dashboard';
import { closeGates } from '@/domain/closing';
import { periodSchema } from '@/domain/schemas/accounting';
import { FinancialTable } from '@/components/financial-table';
import { KpiStrip,DashboardCharts } from '@/components/dashboard';
import { PageHeading } from '@/components/page-heading';
import { ReportLibrary } from '@/components/report-library';
export const runtime='nodejs';
export const dynamic='force-dynamic';
export default async function Reports({searchParams}:{searchParams:Promise<{period?:string;report?:string}>}){
 const params=await searchParams,today=new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Taipei'}),period=periodSchema.parse(params.period??today.slice(0,7)),status=await store.status(),runs=status.readOnly?[]:await store.read(),reports=[...buildReports(runs,period),...operatingReports(runs,period)],data=dashboard(runs,period,today),gates=closeGates(runs,period),selected=reports.find(r=>r.slug===params.report);
 return <><PageHeading eyebrow="Same records. Useful answers." title={selected?selected.title:'Reports'} compact={Boolean(selected)} description={`${period} · posted ledger and evidenced operational projections`}
  action={selected?<Link href={`/reports?period=${period}`}>All reports</Link>:undefined}/>{!selected&&<KpiStrip data={data}/>}{!selected&&<ReportLibrary reports={reports.map(r=>({slug:r.slug,title:r.title}))} period={period}/>}{selected?<section className="card report-view" aria-label={selected.title}>{selected.notes.map(n=><p className="note" key={n}>{n}</p>)}{selected.rows.length?<FinancialTable label={selected.slug} rows={selected.rows.map(row=>({_dataset:selected.dataset,_period:selected.period,...Object.fromEntries(Object.entries(row).map(([key,value])=>[key,typeof value==='string'?value:value.amount===null?`ABSENT — ${value.reason}`:`${value.amount}${value.basis==='provisional'?` · PROVISIONAL: ${value.reason}`:''}`]))}))}/>:<p className="muted">No posted evidence for this report. <Link href="/money?action=expense">Record your first expense</Link> · <Link href="/money#money-guide">Three-step guide</Link></p>}</section>:<><p className="feedback info report-close-link" role="note">{gates.filter(g=>g.status==='PASS').length} of {gates.length} month-end checks pass for {period}. <Link href={`/close?period=${period}`}>{gates.every(g=>g.status==='PASS')?'Open month-end checks':'See what is blocking the close'}</Link></p><DashboardCharts data={data}/></>}{selected&&<ReportLibrary reports={reports.map(r=>({slug:r.slug,title:r.title}))} period={period} selected={selected.slug}/>}<p className="note">ABSENT means required evidence is missing. It never means zero. Financial parity against the reference is tracked separately.</p></>;
}
