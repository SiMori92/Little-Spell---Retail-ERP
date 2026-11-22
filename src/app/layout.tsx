import type { Metadata } from 'next';
import { Suspense } from 'react';
import { ShieldCheck } from 'lucide-react';
import { Toaster } from 'sonner';
import { Navigation } from '@/components/navigation';
import { PeriodPicker } from '@/components/period-picker';
import { store } from '@/server/runtime';
import './globals.css';
import { StatusBadge } from '@/components/ui/workspace';
import { QuickActions } from '@/components/quick-actions';
export const metadata: Metadata = { title:'Little Spell · Your business, simpler', description:'Local-only, evidence-first operations for Little Spell.' };
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const status = await store.status();
  const period = new Intl.DateTimeFormat('en-CA', { timeZone:'Asia/Taipei', year:'numeric', month:'2-digit' }).format(new Date()).replace('/', '-');
  return <html lang="en"><body><a className="skip-link" href="#main-content">Skip to main content</a><div className="app-shell"><Navigation /><div className="main"><header className="topbar"><span className="workspace-label"><ShieldCheck size={16} /> Private workspace</span><div className="top-actions"><StatusBadge>{status.dataset}</StatusBadge><Suspense><PeriodPicker defaultPeriod={period} /></Suspense><QuickActions/></div></header>{status.readOnly && <div role="alert" className="integrity-banner">Read-only · History check failed at {status.badRunId}. Do not repair records. Restore a verified backup.</div>}{status.dataset === 'SAMPLE' && <div className="sample-banner">SAMPLE DATA — NOT ACTUALS · A safe place to learn. Setup is available; this workspace is not ready for real books.</div>}<main id="main-content" tabIndex={-1} className="content">{children}</main></div></div><Toaster richColors /></body></html>;
}
