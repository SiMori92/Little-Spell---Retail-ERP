import Link from 'next/link';
import { randomUUID } from 'node:crypto';
import { notFound } from 'next/navigation';
import { Check, Circle, FolderArchive, ArrowRight, CircleAlert } from 'lucide-react';
import { z } from 'zod';
import { store } from '@/server/runtime';
import { projectMasters } from '@/domain/master-projection';
import { projectInventory } from '@/domain/inventory-projection';
import { masterAreaSchema } from '@/domain/schemas/masters';
import { masterDefaults } from '@/domain/master-defaults';
import { MasterFlow } from '@/components/master-flow';
import { MasterTable } from '@/components/master-table';
export const runtime='nodejs';
export const dynamic='force-dynamic';
const actionSchema=z.enum(['supplier','product','channel','business','opening','reference','import']);
export default async function SetupPage({searchParams}:{searchParams:Promise<{action?:string;tab?:string}>}) {
  const params=await searchParams;
  const status=await store.status();
  const history=status.readOnly?[]:await store.read();
  const projection=projectMasters(history,status.dataset);
  const inventory=projectInventory(history,status.dataset);
  const tab=masterAreaSchema.safeParse(params.tab??'suppliers');
  if(!tab.success)notFound();
  const action=params.action?actionSchema.safeParse(params.action):null;
  if(action&&!action.success)notFound();
  const openingComplete=inventory.openingRecorded;
  const checklist=[{label:'Business details',ready:Boolean(projection.business),prepared:false,href:'/setup?action=business'},{label:'Products',ready:projection.products.length>0,prepared:false,href:'/setup?tab=products'},{label:'Suppliers',ready:projection.suppliers.length>0,prepared:false,href:'/setup?tab=suppliers'},{label:'Opening stock',ready:openingComplete,prepared:Boolean(projection.opening)&&!openingComplete,href:'/stock?action=count'}];
  return <><div className="page-heading"><div><p className="eyebrow">Make the workspace yours</p><h1>Setup</h1><p className="muted">Business details, trusted masters, and a clear starting point.</p></div><span className="badge">M1 · MASTERS</span></div><section className="card" style={{marginBottom:24}}><div className="section-heading"><h2>Your setup checklist</h2><span className="muted">{checklist.filter((item)=>item.ready).length} of 4 complete</span></div><ol className="setup-checklist">{checklist.map((item,index)=><li key={item.label}><span className={`check-circle ${item.ready?'done':''}`}>{item.ready?<Check size={12}/>:item.prepared?<CircleAlert size={12}/>:<Circle size={10}/>}</span><Link href={item.href}><strong>{index+1}. {item.label}</strong><span className="muted" style={{display:'block',fontSize:11,marginTop:5}}>{item.ready?'Recorded':item.prepared?'Prepared · review and book count':'Needs your input'}</span></Link><ArrowRight size={13}/></li>)}</ol>{inventory.openingRecorded&&projection.opening?.record.mode==='prepare'&&<p className="note">Opening stock is recorded. New setup preparation remains unposted and does not change it.</p>}<p className="note">{checklist.every((item)=>item.ready)?'Setup declarations are complete. This does not certify opening balances or financial readiness.':'Setup progress stays here until complete. A prepared stock count is not posted inventory. Financial parity is a separate release gate.'}</p></section>
  {action?.success?<MasterFlow key={randomUUID()} initial={masterDefaults(action.data,projection,randomUUID(),tab.data)} projection={projection} readOnly={status.readOnly}/>:<><div className="setup-actions"><Link className="button secondary" href="/setup/dataset">Dataset transition</Link><Link className="button" href="/setup?action=business">Record business details</Link><Link className="button secondary" href="/setup?action=product">Add product</Link><Link className="button secondary" href="/setup?action=supplier">Add supplier</Link><Link className="button secondary" href={`/setup?action=import&tab=${tab.data}`}>Import {tab.data}</Link>{projection.accounts.length===0&&<Link className="button secondary" href="/setup?action=reference">Load approved reference data</Link>}</div><nav className="setup-tabs" aria-label="Master data">{masterAreaSchema.options.map((area)=><Link aria-current={tab.data===area?'page':undefined} className={tab.data===area?'active':''} href={`/setup?tab=${area}`} key={area}>{area==='accounts'?'Accounts / 科目':area.charAt(0).toUpperCase()+area.slice(1)}</Link>)}</nav><MasterTable area={tab.data} projection={projection} readOnly={status.readOnly}/></>}
  <div className="grid-main" style={{marginTop:24}}><section className="card" id="setup-guide"><h2>Three-step mini-guide</h2><p className="muted">1. Record business details and add or import products/suppliers. Products may stay unassigned until their supplier is recorded.<br/>2. Use the exact current CSV header and a dated filename. Downloads contain the current snapshot, not customer data.<br/>3. Check evidence, preview the effects, then confirm. Record opening preparation separately; no stock or money is booked here.</p><Link href="/" className="button secondary">Return to Today</Link></section><section className="card" id="backup"><FolderArchive color="var(--primary)"/><h2 style={{marginTop:16}}>Protect your records</h2><p className="muted">Run <code>pnpm backup</code> in the ERP folder. Keep the zip and checksum together in a secure location.</p><p className="note">Backups go to <code>../erp-backups/</code>. Restore with <code>pnpm restore &lt;zip&gt;</code> into an empty data folder only.</p></section></div></>;
}
