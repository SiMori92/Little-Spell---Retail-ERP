import Link from 'next/link';
import { randomUUID } from 'node:crypto';
import { notFound } from 'next/navigation';
import { z } from 'zod';
import { accountingState } from '@/domain/accounting';
import { store } from '@/server/runtime';
import { projectSelling } from '@/domain/selling-projection';
import { projectMasters } from '@/domain/master-projection';
import { sellingDefaults } from '@/server/selling-defaults';
import { SellingFlow } from '@/components/selling-flow';
import { SellingTable } from '@/components/selling-table';
export const runtime='nodejs';
export const dynamic='force-dynamic';
const tabSchema=z.enum(['orders','deals','statements','events']);
const actionSchema=z.enum(['etsy','ig-import','deal','dispatch','verify-etsy']);
export default async function SellPage({searchParams}:{searchParams:Promise<{tab?:string;view?:string;action?:string;order?:string}>}){
  const params=await searchParams,status=await store.status(),runs=status.readOnly?[]:await store.read();
  const projection=projectSelling(runs,status.dataset),masters=projectMasters(runs,status.dataset);
  const tab=tabSchema.safeParse(params.tab??'orders'),action=params.action?actionSchema.safeParse(params.action):null;
  if(!tab.success||action&&!action.success||params.view&&!['table','board'].includes(params.view))notFound();
  if(action?.success&&action.data==='dispatch'&&!projection.orders.some(item=>item.record.orderId===params.order))notFound();
  const today=new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Taipei'}),unshipped=projection.orders.filter(item=>!projection.shipments.some(ship=>ship.orderId===item.record.orderId)).length,due=projection.deals.filter(item=>['enquiry','quoted'].includes(item.record.status)&&item.record.followUpOn&&item.record.followUpOn<=today).length;
  return <><div className="page-heading"><div><p className="eyebrow">From first hello to dispatch</p><h1>Sell</h1><p className="muted">{unshipped} Etsy orders to ship · {due} Instagram follow-ups due</p></div><span className="badge">M2 · SELLING</span></div>{!projection.verified&&<div className="note" style={{marginBottom:20}}>Etsy source headers are unverified. Previews do not bypass this gate. <Link href="/sell?action=verify-etsy" style={{textDecoration:'underline'}}>Review the exact headers</Link></div>}<div className="setup-actions"><Link className="button" href="/sell?action=etsy">Import Etsy pair</Link><Link className="button secondary" href="/sell?action=deal">New Instagram deal</Link><Link className="button secondary" href="/sell?action=ig-import">Import Instagram</Link><Link className="button secondary" href="/sell?action=verify-etsy">Header review</Link></div>
    {action?.success?<SellingFlow key={randomUUID()} initial={sellingDefaults(action.data,projection,randomUUID(),params.order)} masters={masters} readOnly={status.readOnly}/>:<><nav className="setup-tabs" aria-label="Selling records">{tabSchema.options.map(value=><Link href={`/sell?tab=${value}`} aria-current={tab.data===value?'page':undefined} key={value} className={tab.data===value?'active':''}>{value==='events'?'Accounting queue':value.charAt(0).toUpperCase()+value.slice(1)}</Link>)}</nav>{tab.data==='deals'&&<div className="setup-actions"><Link className="button secondary" href="/sell?tab=deals&view=table">Table view</Link><Link className="button secondary" href="/sell?tab=deals&view=board">Kanban view</Link></div>}<SellingTable tab={tab.data} board={params.view==='board'} projection={projection} masters={masters} readOnly={status.readOnly} postedEventIds={accountingState(runs).posted.map(p=>p.eventId)}/></>}
    <section className="card" id="sell-guide" style={{marginTop:24}}><h2>Three-step selling guide</h2><p className="muted">1. Review exact Etsy headers and record coupon-funder evidence, or add a deal with an anonymous C- reference.<br/>2. Upload, check dates and sale units, and preview. Existing counted pieces are required for Etsy dispatch; opening preparation is not stock.<br/>3. Confirm a new run. Review and post selling events in Money; ACTUAL paid Instagram deals wait for wallet evidence. No notifications are sent.</p><p className="note">Sample Instagram pipeline facts are loaded at startup. Etsy fixture booking stays gated by your header review and counted stock. Financial readiness and tie-out remain unfinished.</p><div className="setup-actions"><Link prefetch={false} href="/api/sell/sample?kind=orderitems" download>Sample Etsy order-items</Link><Link prefetch={false} href="/api/sell/sample?kind=statement" download>Sample Etsy statement</Link><Link prefetch={false} href="/api/sell/sample?kind=instagram" download>Sample Instagram v2</Link></div></section></>;
}
