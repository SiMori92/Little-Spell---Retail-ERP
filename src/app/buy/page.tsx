import Link from 'next/link';
import { randomUUID } from 'node:crypto';
import { notFound } from 'next/navigation';
import { z } from 'zod';
import { store } from '@/server/runtime';
import { projectMasters } from '@/domain/master-projection';
import { projectProcurement } from '@/domain/procurement-projection';
import { projectInventory } from '@/domain/inventory-projection';
import { procurementAreaSchema } from '@/domain/schemas/procurement';
import { procurementDefaults } from '@/server/procurement-defaults';
import { ProcurementFlow } from '@/components/procurement-flow';
import { ProcurementTable } from '@/components/procurement-table';
import { PageHeading } from '@/components/page-heading';
import { StatusBadge } from '@/components/ui/workspace';
export const runtime='nodejs';
export const dynamic='force-dynamic';
const tabSchema=z.enum(['orders','receipts','invoices','payments','exceptions']);
const actionSchema=z.enum(['po','receipt','invoice','payment','import']);
export default async function BuyPage({searchParams}:{searchParams:Promise<{tab?:string;action?:string;po?:string;invoice?:string;area?:string}>}){
  const params=await searchParams,status=await store.status(),runs=status.readOnly?[]:await store.read(),projection=projectProcurement(runs,status.dataset),inventory=projectInventory(runs,status.dataset),masters=projectMasters(runs,status.dataset);
  const tab=tabSchema.safeParse(params.tab??'orders'),action=params.action?actionSchema.safeParse(params.action):null,area=procurementAreaSchema.safeParse(params.area??'po');if(!tab.success||action&&!action.success||!area.success)notFound();if(action?.success&&['receipt','invoice','payment'].includes(action.data)&&!projection.orders.some(item=>item.record.poNumber===params.po))notFound();
  return <><PageHeading eyebrow="Order, receive, check, pay" title="Buy"
    compact={Boolean(action?.success)}
    description={action?.success ? 'Enter the supplier details, review their exact effects, then confirm.' : 'Keep supplier orders, deliveries and invoices together. Review the match before you pay.'}
    action={action?.success ? <Link href="/buy">Back to purchasing</Link> : <><Link className="button" href="/buy?action=po">New purchase order</Link><Link className="button secondary" href="/buy?action=import">Import document CSV</Link></>}/>
  {!action?.success&&<div className="summary-strip">
    <section className="card summary-item"><span className="muted">Matched supplier payables</span><strong>NT${projection.totalPayablesTwd}</strong><span className="muted">From matched supplier documents</span></section>
    <section className="card summary-item"><span className="muted">Document checks</span><strong>{projection.exceptions.length}</strong><Link href="/buy?tab=exceptions">{projection.exceptions.length ? 'Review documents needing attention' : 'View document checks'}</Link></section>
    <section className="card summary-item"><span className="muted">Working dataset</span><StatusBadge tone={status.dataset==='SAMPLE'?'warning':'neutral'}>{status.dataset}</StatusBadge><Link href="/stock">View stock and counts</Link></section>
  </div>}

  {action?.success?<ProcurementFlow key={randomUUID()} initial={procurementDefaults(action.data,projection,masters,inventory,randomUUID(),params.po,params.invoice,area.data)} masters={masters} projection={projection} readOnly={status.readOnly}/>:<><nav className="setup-tabs" aria-label="Purchasing records">{tabSchema.options.map(value=><Link href={`/buy?tab=${value}`} className={tab.data===value?'active':''} aria-current={tab.data===value?'page':undefined} key={value}>{value==='orders'?'Purchase orders':value==='receipts'?'Deliveries':value.charAt(0).toUpperCase()+value.slice(1)}</Link>)}</nav><ProcurementTable tab={tab.data} projection={projection} readOnly={status.readOnly}/></>}
  <details className="card guide-disclosure" id="buy-guide"><summary>Three-step buying guide</summary><p className="muted">1. Record the agreed quote, pieces, per-piece price, setup and minimum order quantity. Sending requires product/supplier compliance evidence.<br/>2. Record what arrived and the supplier bill. Their exact line sets and accepted pieces must agree before stock and payable are posted. Unmatched documents stay visible under Exceptions.<br/>3. Review the preview, confirm, then pay the matched balance using bank evidence. Deposits come before any receipt; refunds/forfeitures require a cancelled PO.</p><p className="note">One delivery and invoice per PO line. Short deliveries require an evidenced short-close. Carrier freight, duty, in-transit receipts and late-cost corrections remain outside this reference scope. No sending, editing, or deleting is performed.</p><div className="setup-actions"><Link prefetch={false} download href="/api/buy/sample?kind=po">Sample packaging PO (sent)</Link><Link prefetch={false} download href="/api/buy/sample?kind=grn">Sample delivery</Link><Link prefetch={false} download href="/api/buy/sample?kind=inv">Sample invoice</Link></div><p className="muted">These three packaging files form one isolated SAMPLE scenario. Other bundled fixture scenarios must not be mixed blindly.</p></details></>;
}
