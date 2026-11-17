'use client';
import { useRouter, useSearchParams } from 'next/navigation';
export function PeriodPicker({ defaultPeriod }: { defaultPeriod: string }) {
  const router = useRouter();
  const params = useSearchParams();
  return <label style={{ margin:0 }}><span className="period-label muted" style={{ marginRight:10, fontSize:12 }}>Month</span><input aria-label="Reporting month" type="month" value={params.get('period') ?? defaultPeriod} onChange={(event) => { const next = new URLSearchParams(params.toString()); next.set('period', event.target.value); router.push(`?${next}`); }} /></label>;
}
