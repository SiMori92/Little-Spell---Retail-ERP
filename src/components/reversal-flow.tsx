'use client';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { reversalPayloadSchema } from '@/domain/schemas';
import { Button } from './ui/button';
import { FlowProgress } from '@/components/ui/workspace';
export function ReversalFlow({ originalRunId }: { originalRunId: string }) {
  const [step, setStep] = useState(0), [preview, setPreview] = useState<unknown>(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const router = useRouter();
  const form = useForm<z.infer<typeof reversalPayloadSchema>>({ resolver:zodResolver(reversalPayloadSchema), defaultValues:{ originalRunId, occurredOn:new Date().toLocaleDateString('en-CA', { timeZone:'Asia/Taipei' }), reason:'', idempotencyKey:crypto.randomUUID() } });
  async function request(previewOnly: boolean) {
    setBusy(true); setError('');
    try {
      const response = await fetch(`/api/history/reverse${previewOnly ? '/preview' : ''}`, { method:'POST', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify(form.getValues()) });
      const result = await response.json();
      if (!result.ok) { setError(result.errors?.[0]?.message ?? 'This action was not completed.'); return; }
      if (previewOnly) { setPreview(result.effects); setStep(2); }
      else { toast.success('Reversing entry saved. The original is unchanged.'); setStep(4); router.refresh(); }
    } catch { setError('Connection lost. Retry with the same form; duplicates are prevented.'); }
    finally { setBusy(false); }
  }
  if (step === 4) return <p className="note" role="status">Reversal recorded. The original remains in history.</p>;
  return <section><FlowProgress step={step} busy={busy} label="Correction progress"/><p className="note">This creates a reversing entry dated today, or another open date you choose. The original stays on record.</p>{step === 0 && <form onSubmit={form.handleSubmit(() => setStep(1))}><label htmlFor="reversal-date">Correction date</label><input id="reversal-date" type="date" {...form.register('occurredOn')} />{form.formState.errors.occurredOn && <p className="error">Choose a valid correction date.</p>}<label htmlFor="reversal-reason">Why are you correcting this?</label><input id="reversal-reason" {...form.register('reason')} />{form.formState.errors.reason && <p className="error">Add a short reason, without buyer details.</p>}<div style={{ margin:'24px 0' }}><Button type="submit">Check correction</Button></div></form>}{step === 1 && <><p>The correction reverses the complete original record on {form.getValues('occurredOn')}. Check the date and reason before continuing.</p><Button disabled={busy} onClick={() => request(true)}>Preview effects</Button></>}{step === 2 && <><p>This will undo the original recorded stock and money effects exactly. It will not edit or remove the original.</p><details><summary>Accounting view</summary><pre style={{ fontSize:12, overflow:'auto' }}>{JSON.stringify(preview,null,2)}</pre></details><Button onClick={() => setStep(3)}>Continue</Button></>}{step === 3 && <><p>Ready to create the reversing entry? This action is also permanent.</p><Button disabled={busy} onClick={() => request(false)}>Confirm reversal</Button></>}{step > 0 && <Button variant="secondary" disabled={busy} onClick={() => setStep(step - 1)}>Back</Button>}{error && <p role="alert" className="error">{error}</p>}</section>;
}
