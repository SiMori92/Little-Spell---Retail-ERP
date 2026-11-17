import Link from 'next/link';
import { randomUUID } from 'node:crypto';
import { notFound } from 'next/navigation';
import { store } from '@/server/runtime';
import { projectMasters } from '@/domain/master-projection';
import { projectProcurement } from '@/domain/procurement-projection';
import { projectInventory } from '@/domain/inventory-projection';
import { procurementDefaults } from '@/server/procurement-defaults';
import { ProcurementFlow } from '@/components/procurement-flow';
import { StockTables } from '@/components/stock-tables';
export const runtime='nodejs';
export const dynamic='force-dynamic';
export default async function StockPage({searchParams}:{searchParams:Promise<{action?:string}>}){
  const params=await searchParams;if(params.action&&!['count','import'].includes(params.action))notFound();const status=await store.status(),runs=status.readOnly?[]:await store.read(),projection=projectProcurement(runs,status.dataset),inventory=projectInventory(runs,status.dataset),masters=projectMasters(runs,status.dataset),hasEvidence=inventory.positions.some(item=>item.evidenced);
  return <><div className="page-heading"><div><p className="eyebrow">Pieces you can explain</p><h1>Stock</h1><p className="muted">Recorded operational value: {hasEvidence?`NT$${inventory.totalValueTwd}`:'not established'} · Pending COGS: NT${inventory.pendingCogsTwd}</p></div><span className="badge">M3 · STOCK</span></div><div className="setup-actions"><Link className="button secondary" href="/money?action=reorder">Set reorder point</Link><Link className="button" href="/stock?action=count">Record physical count</Link><Link className="button secondary" href="/stock?action=import">Import count CSV</Link><Link className="button secondary" href="/buy">Receive supplier stock</Link></div>{!inventory.openingRecorded&&<p className="note">No opening count is recorded. M1 preparation is not inventory. Record a complete evidenced opening before stock activity; unknown quantities are not zero.</p>}
  {params.action?<ProcurementFlow key={randomUUID()} initial={procurementDefaults(params.action as 'count'|'import',projection,masters,inventory,randomUUID(),undefined,undefined,'counts')} masters={masters} projection={projection} readOnly={status.readOnly}/>:<StockTables inventory={inventory} procurement={projection}/>}
  <section className="card" style={{marginTop:24}}><h2>Three-step stock guide</h2><p className="muted">1. Count every active product explicitly, including zeros, and keep stable evidence. Damaged pieces are zero-value memos.<br/>2. Check the preview. Opening stock books inventory/owner capital; later decreases use existing exact WAC, not a new price typed into the count.<br/>3. Confirm a new immutable run. Increases need a goods receipt, not an unexplained count adjustment.</p><p className="note">Packaging receipts are valued separately and do not enter sellable WAC. This reference count scope accepts only explicit zero packaging rows. Operational WAC includes dispatch deductions. The status table shows which costs have been posted in Money.</p><Link prefetch={false} download href="/api/buy/sample?kind=counts">Download complete SAMPLE opening-count schedule</Link></section></>;
}
