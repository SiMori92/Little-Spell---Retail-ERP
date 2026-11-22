import Link from 'next/link';
import { StatusBadge } from '@/components/ui/workspace';

type Gate = { gate: string; status: string; reason: string; details: unknown };

// Plain-English purpose, recovery step and where to investigate, per gate. Wording to be confirmed by Finance.
const guide: Record<string, { title: string; recovery: string; links: (period: string) => { href: string; label: string }[] }> = {
  'G-1': { title: 'Every fact is posted', recovery: 'Review and post the remaining facts in Money, then check again.',
    links: () => [{ href: '/money', label: 'Review unposted facts' }] },
  'G-2': { title: 'Settlement and deposits are explained', recovery: 'Supply missing settlement evidence, explain aged clearing items, clear platform tax and reconcile open supplier deposits.',
    links: p => [{ href: `/reports?period=${p}&report=settlement-aging`, label: 'Settlement aging' }, { href: `/reports?period=${p}&report=supplier-deposits`, label: 'Supplier deposits' }] },
  'G-3': { title: 'Stock ties to the ledger', recovery: 'Record the missing opening, count or SKU attribution, or resolve the quantity and value differences.',
    links: p => [{ href: `/reports?period=${p}&report=inventory`, label: 'Inventory roll-forward' }, { href: '/stock', label: 'Stock and counts' }] },
  'G-4': { title: 'Contribution ties to the ledger', recovery: 'Supply the missing contribution inputs or correct the allocation, then check again.',
    links: p => [{ href: `/reports?period=${p}&report=contribution-orders`, label: 'Contribution per order' }, { href: `/reports?period=${p}&report=profit-loss`, label: 'Profit and loss' }] },
  'G-5': { title: 'No plugs or unsupported estimates', recovery: 'Review the flagged accounts, correction references and estimate evidence. Record any correction as a new reviewed entry.',
    links: p => [{ href: '/money', label: 'Review accounting evidence' }, { href: `/reports?period=${p}&report=trial-balance`, label: 'Trial balance' }] },
};
const tone = (status: string) => status === 'PASS' ? 'success' : status === 'FAIL' ? 'danger' : 'warning';

/** Month-end checks: every gate with a labelled result, the first blocker and its next step. */
export function CloseChecklist({ gates, period, closed }: { gates: readonly Gate[]; period: string; closed: boolean }) {
  const passed = gates.filter(g => g.status === 'PASS').length, blocker = gates.find(g => g.status !== 'PASS');
  return <section className="card close-checklist" aria-labelledby="close-checks-title">
    <div className="section-heading"><h2 id="close-checks-title">Month-end checks</h2><span className="muted"><strong className="close-count">{passed} of {gates.length}</strong> passed</span></div>
    {closed ? <p className="feedback success" role="status">This month is closed. Reopening requires its own audited record.</p>
      : blocker ? <div className="close-blocker" role="note">
        <p className="close-blocker-label">Month stays open — first unresolved check: {blocker.gate}</p>
        <p>{blocker.reason}</p>
        <p><strong>Next step:</strong> {guide[blocker.gate]?.recovery ?? 'Resolve this check, then review again.'}</p>
        <p className="close-links">{guide[blocker.gate]?.links(period).map((link, index) => <span key={link.href}>{index > 0 && ' · '}<Link href={link.href}>{link.label}</Link></span>)}</p>
      </div> : <p className="feedback success" role="status">All five checks pass. Record the pre-posting review, then review the close attempt.</p>}
    <ol className="gate-list" aria-label="Month-end checks in order">{gates.map(g => <li className="gate-row" key={g.gate}>
      <span className="gate-code">{g.gate}</span>
      <div className="gate-copy"><strong>{guide[g.gate]?.title ?? g.gate}</strong><span className="muted">{g.reason}</span>
        <details className="gate-evidence"><summary>Evidence details</summary><pre>{JSON.stringify(g.details, null, 2)}</pre></details></div>
      <StatusBadge tone={tone(g.status)}>{g.status.replaceAll('_', ' ')}</StatusBadge>
    </li>)}</ol>
    <p className="muted close-footnote">NOT RUNNABLE means required evidence is missing. It never passes a close.</p>
  </section>;
}
