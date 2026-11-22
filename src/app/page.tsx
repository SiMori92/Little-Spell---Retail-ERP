import Link from 'next/link';
import { ArrowRight, FolderArchive, Plus } from 'lucide-react';
import { store } from '@/server/runtime';
import { lastBackup } from '@/server/archive';
import { dashboard } from '@/domain/dashboard';
import { closeGates } from '@/domain/closing';
import { projectInventory } from '@/domain/inventory-projection';
import { periodSchema } from '@/domain/schemas/accounting';
import { KpiStrip } from '@/components/dashboard';
import { PageHeading } from '@/components/page-heading';
import { StatusBadge } from '@/components/ui/workspace';
export const runtime='nodejs';
export const dynamic='force-dynamic';

export default async function Today({searchParams}:{searchParams:Promise<{period?:string}>}) {
  const params=await searchParams,status=await store.status(),backup=await lastBackup(store.directory),runs=status.readOnly?[]:await store.read(),today=new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Taipei'}),period=periodSchema.parse(params.period??today.slice(0,7)),data=dashboard(runs,period,today),gates=closeGates(runs,period),inventory=projectInventory(runs);
  return <>
    <PageHeading eyebrow="A little clarity, every day" title="Your day, at a glance"
      description="Your next steps, from recorded facts. Review what needs attention, then get back to running your business."
      action={<><Link className="button" href="/money?action=expense"><Plus size={16}/> Record expense</Link><Link href={`/reports?period=${period}`}>View reports <ArrowRight size={14}/></Link></>}/>
    <div className="grid-main">
      <section className="card"><div className="section-heading"><h2>Next steps</h2><span className="muted">From your recorded activity</span></div>
        <div className="task"><div className="task-text"><strong>{inventory.openingRecorded?'Opening stock recorded':'Complete your setup checklist'}</strong><p className="muted">Review business details, masters and your starting point.</p></div><Link className="button secondary" href="/setup">Open setup</Link></div>
        {!status.readOnly&&data.tasks.map(task=><div className="task" key={task.title}><div className="task-text"><strong>{task.title}</strong><p className="muted">{task.detail}</p></div><Link className="button secondary" href={task.href}>Open flow <ArrowRight size={14}/></Link></div>)}
        {backup.stale&&<div className="task"><FolderArchive size={20}/><div className="task-text"><strong>{backup.days===null?'Create your first backup':'Your backup needs a refresh'}</strong><p className="muted">Keep a verified copy.</p></div><Link className="button secondary" href="/setup#backup">How to back up</Link></div>}
      </section>
      <section className="card"><div className="section-heading"><h2>Month-end checks</h2><span className="muted">{period}</span></div>
        <p className="muted">{gates.filter(g=>g.status==='PASS').length} of 5 checks passed. Missing evidence never passes.</p>
        <div className="gate-results">{gates.map(g=><div className="gate-result" key={g.gate}><span>{g.gate}</span><StatusBadge tone={g.status==='PASS'?'success':g.status==='FAIL'?'danger':'warning'}>{g.status.replaceAll('_',' ')}</StatusBadge></div>)}</div>
        <Link className="button secondary" href={`/close?period=${period}`}>View checks <ArrowRight size={14}/></Link>
      </section>
    </div>
    <section className="business-snapshot" aria-labelledby="snapshot-title"><div className="section-heading"><h2 id="snapshot-title">Business snapshot</h2><span className="muted">{period} · recorded evidence</span></div><KpiStrip data={data}/></section>
    <div className="footer">Last backup: {backup.days===null?'not recorded':`${backup.days} days ago`} · {status.runCount??'Unverified'} immutable runs · {status.readOnly?'Writes blocked':'History verified'}</div>
  </>;
}
