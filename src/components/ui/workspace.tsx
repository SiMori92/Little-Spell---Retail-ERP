import type { ReactNode } from 'react';
import { Check, LoaderCircle } from 'lucide-react';

export type StatusTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';
const statusTones: Record<string, StatusTone> = {
  POSTED: 'success', CLOSED: 'success', PASS: 'success', ACTUAL: 'info',
  UNPOSTED: 'warning', SAMPLE: 'warning', PENDING: 'warning',
  FAIL: 'danger', FAILED: 'danger', 'NOT RUNNABLE': 'warning', REVERSED: 'neutral', OPEN: 'info',
};
export function StatusBadge({ children, tone }: { children: string; tone?: StatusTone }) {
  return <span className={`badge ${tone ?? statusTones[children.toUpperCase()] ?? 'neutral'}`}>{children}</span>;
}
export function MetricCard({ label, value, detail }: { label: string; value: ReactNode; detail: ReactNode }) {
  return <div className="card metric"><div className="metric-label">{label}</div><strong>{value}</strong><span className="metric-detail">{detail}</span></div>;
}
export function FlowProgress({ step, busy = false, label = 'Flow progress' }: { step: number; busy?: boolean; label?: string }) {
  return <div aria-busy={busy}>
    <ol className="step-track" aria-label={label}>{['Enter', 'Check', 'Preview', 'Confirm'].map((name, index) =>
      <li className={index === step ? 'active' : index < step ? 'complete' : ''} aria-current={index === step ? 'step' : undefined} key={name}>
        <span className="step-number" aria-hidden="true">{index < step ? <Check size={13} /> : index + 1}</span>{name}
      </li>)}</ol>
    {busy && <p className="flow-busy" role="status"><LoaderCircle size={15} className="loading-icon" /> Checking your request. Please wait…</p>}
  </div>;
}
export function InlineFeedback({ message, tone = 'danger' }: { message: string; tone?: StatusTone }) {
  return message ? <p className={`feedback ${tone}`} role={tone === 'danger' ? 'alert' : 'status'}>{message}</p> : null;
}
