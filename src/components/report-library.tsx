'use client';
import Link from 'next/link';
import { useState } from 'react';
import { ArrowUpRight, LayoutDashboard } from 'lucide-react';

const groups: { id: string; title: string; description: string; slugs: string[] }[] = [
  { id: 'accounting', title: 'Accounting', description: 'The posted ledger and inventory position.', slugs: ['trial-balance', 'profit-loss', 'balance-sheet', 'inventory'] },
  { id: 'performance', title: 'Performance', description: 'Contribution by order, product and channel.', slugs: ['contribution-orders', 'contribution-skus', 'contribution-channels', 'cac'] },
  { id: 'reconciliation', title: 'Reconciliation', description: 'Open clearing and freight differences.', slugs: ['settlement-aging', 'carrier-reconciliation'] },
  { id: 'instagram', title: 'Instagram', description: 'The file-based, no-PII sales pipeline.', slugs: ['ig-pipeline', 'repeat-rate'] },
  { id: 'purchasing', title: 'Purchasing', description: 'Supplier commitments, documents and deposits.', slugs: ['open-pos', 'po-exceptions', 'landed-cost', 'payables', 'supplier-deposits', 'deposit-reconciliation'] },
];

/** Grouped, searchable report selector. Every link keeps the selected reporting month. */
export function ReportLibrary({ reports, period, selected }: { reports: { slug: string; title: string }[]; period: string; selected?: string }) {
  const [query, setQuery] = useState('');
  const known = new Set(groups.flatMap(group => group.slugs));
  const all = [...groups, { id: 'other', title: 'Other', description: 'Further views.', slugs: reports.map(r => r.slug).filter(slug => !known.has(slug)) }]
    .map(group => ({ ...group, items: group.slugs.map(slug => reports.find(r => r.slug === slug)).filter((r): r is { slug: string; title: string } => Boolean(r)) }))
    .filter(group => group.items.length);
  const needle = query.trim().toLocaleLowerCase();
  const visible = all.map(group => ({ ...group, items: group.items.filter(r => !needle || `${r.title} ${group.title}`.toLocaleLowerCase().includes(needle)) })).filter(group => group.items.length);
  const count = visible.reduce((sum, group) => sum + group.items.length, 0);
  return <section className="card report-library" aria-labelledby="report-library-title">
    <div className="section-heading"><h2 id="report-library-title">Report library</h2>
      <Link className={`report-dashboard-link${selected ? '' : ' active'}`} aria-current={selected ? undefined : 'page'} href={`/reports?period=${period}`}><LayoutDashboard size={15} /> Dashboard</Link></div>
    <div className="table-search report-search"><input type="search" aria-label="Find a report" placeholder="Find a report by name or area…" value={query} onChange={event => setQuery(event.target.value)} />
      <span className="table-result-count" role="status" aria-live="polite">{count} of {reports.length} reports</span></div>
    {visible.map(group => <div className="report-group" key={group.id}>
      <p className="eyebrow">{group.title}</p><p className="muted report-group-description">{group.description}</p>
      <ul className="report-links">{group.items.map(report => <li key={report.slug}>
        <Link href={`/reports?period=${period}&report=${report.slug}`} aria-current={selected === report.slug ? 'page' : undefined} className={selected === report.slug ? 'active' : ''}>{report.title}<ArrowUpRight size={14} aria-hidden="true" /></Link></li>)}</ul>
    </div>)}
    {!count && <p className="muted" role="status">No reports match “{query}”. Clear the search to see all {reports.length}.</p>}
  </section>;
}
