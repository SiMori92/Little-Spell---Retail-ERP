'use client';
import Link from 'next/link';
import { useState } from 'react';
import { useForm, useFieldArray, type FieldPath, type UseFormReturn } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { toast } from 'sonner';
import { publicMasterPayloadSchema, masterResultSchema, type MasterProjection } from '@/domain/schemas/masters';
import type { MasterInput } from '@/domain/master-defaults';
import { Button } from './ui/button';
import { Glossary } from './glossary';
import { FlowProgress } from '@/components/ui/workspace';

type MasterOutput = z.output<typeof publicMasterPayloadSchema>;
type MasterForm = UseFormReturn<MasterInput,unknown,MasterOutput>;
const titles = {supplier:'Supplier details',product:'Product details',channel:'Sales channel',business:'Business details',opening:'Opening stock preparation',reference:'Approved reference data',import:'Import master CSV'};
const errorSchema = z.object({ok:z.literal(false),errors:z.array(z.object({field:z.string(),message:z.string()}))});

function OpeningFields({ form, projection }: { form:MasterForm; projection:MasterProjection }) {
  const fields = useFieldArray({control:form.control,name:'record.lines'});
  const mode = form.watch('record.mode');
  return <><label htmlFor="opening-mode">Do you have stock already?</label><select id="opening-mode" {...form.register('record.mode',{onChange:(event) => { if (event.target.value === 'no_stock') fields.replace([]); else if (!fields.fields.length) fields.append({sku:projection.products[0]?.record.sku ?? '',condition:'sellable',qtyPieces:'',agreedUnitCostTwd:'0.0000',evidenceRef:''}); }})}><option value="prepare">Yes — prepare my count</option><option value="no_stock">No — I have no opening stock</option></select><label htmlFor="counted-on">Count date</label><input id="counted-on" type="date" {...form.register('record.countedOn',{onChange:(event) => form.setValue('occurredOn',event.target.value)})} />{mode === 'prepare' && <><p className="note">Preparation only. No inventory or opening journal is booked in M1. Use evidenced per-piece costs; damaged pieces have zero sellable value.</p>{fields.fields.map((field,index) => <fieldset className="card" key={field.id} style={{marginTop:16}}><legend>Count line {index + 1}</legend><label htmlFor={`count-sku-${index}`}>Product</label><select id={`count-sku-${index}`} {...form.register(`record.lines.${index}.sku`)}>{projection.products.map(({record}) => <option key={record.sku} value={record.sku}>{record.sku} · {record.name}</option>)}</select><label htmlFor={`condition-${index}`}>Condition</label><select id={`condition-${index}`} {...form.register(`record.lines.${index}.condition`)}><option value="sellable">Sellable</option><option value="damaged">Damaged</option></select><label htmlFor={`pieces-${index}`}>Pieces counted</label><input id={`pieces-${index}`} inputMode="numeric" {...form.register(`record.lines.${index}.qtyPieces`)} /><label htmlFor={`cost-${index}`}>Agreed cost per piece (TWD)</label><input id={`cost-${index}`} inputMode="decimal" {...form.register(`record.lines.${index}.agreedUnitCostTwd`)} /><label htmlFor={`line-evidence-${index}`}>Line evidence reference</label><input id={`line-evidence-${index}`} {...form.register(`record.lines.${index}.evidenceRef`)} />{(['sku','condition','qtyPieces','agreedUnitCostTwd','evidenceRef'] as const).map((key) => {const error = form.getFieldState(`record.lines.${index}.${key}`,form.formState).error; return error ? <p role="alert" className="error" key={key}>{error.message}</p> : null;})}<Button type="button" variant="secondary" onClick={() => fields.remove(index)}>Remove draft line</Button></fieldset>)}<Button type="button" variant="secondary" onClick={() => fields.append({sku:projection.products[0]?.record.sku ?? '',condition:'sellable',qtyPieces:'',agreedUnitCostTwd:'0.0000',evidenceRef:''})}>Add draft line</Button></>}<label><input type="checkbox" {...form.register('record.founderConfirmed')} /> I confirm this is my own count or no-stock declaration.</label>{form.getFieldState('record.founderConfirmed',form.formState).error && <p className="error">Confirm the declaration before continuing.</p>}{form.getFieldState('record.lines',form.formState).error && <p className="error">{form.getFieldState('record.lines',form.formState).error?.message}</p>}</>;
}

export function MasterFlow({ initial, projection, readOnly = false }: { initial:MasterInput; projection:MasterProjection; readOnly?:boolean }) {
  const form = useForm<MasterInput,unknown,MasterOutput>({resolver:zodResolver(publicMasterPayloadSchema),defaultValues:initial});
  const [step,setStep] = useState(0), [busy,setBusy] = useState(false), [error,setError] = useState('');
  const [reading,setReading] = useState(false), [preview,setPreview] = useState<z.infer<typeof masterResultSchema> | null>(null), [saved,setSaved] = useState<z.infer<typeof masterResultSchema> | null>(null);
  const action = initial.action;
  const revision = 'previousRunId' in initial && initial.previousRunId !== null;
  const field = (path:FieldPath<MasterInput>,label:string,options?:readonly string[] | readonly (readonly [string,string])[],kind='text',help?:string,locked=false) => {
    const state = form.getFieldState(path,form.formState);
    const id = `master-${path.replaceAll('.','-')}`;
    const registration = form.register(path, path === 'record.piecesPerSaleUnit' ? {valueAsNumber:true} : {});
    return <div key={path}><label htmlFor={id}>{label}{locked && ' · fixed'}</label>{options && !locked ? <select id={id} aria-invalid={Boolean(state.error)} {...registration}>{options.map((option) => <option key={typeof option === 'string' ? option : option[0]} value={typeof option === 'string' ? option : option[0]}>{typeof option === 'string' ? option : option[1]}</option>)}</select> : <input id={id} type={kind} readOnly={locked} aria-invalid={Boolean(state.error)} aria-describedby={help ? `${id}-help` : undefined} {...registration} />}{help && <p className="muted" id={`${id}-help`} style={{fontSize:12}}>{help}</p>}{state.error && <p className="error" role="alert">{state.error.message}</p>}</div>;
  };
  async function loadFile(file?:File) {
    if (!file) return;
    setError(''); setReading(true);
    try {
      if (file.size > 524288) throw new Error('Choose a UTF-8 CSV smaller than 512 KB.');
      const text = new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());
      form.setValue('filename',file.name,{shouldValidate:true}); form.setValue('csvText',text,{shouldValidate:true});
    } catch { setError('Choose a valid UTF-8 CSV smaller than 512 KB.'); }
    finally { setReading(false); }
  }
  async function request(previewOnly:boolean) {
    if (readOnly) return;
    setBusy(true); setError('');
    try {
      const values = form.getValues();
      const payload = {...values,expectedHeadHash:previewOnly ? null : preview?.headHash ?? null};
      const response = await fetch(`/api/setup/${action === 'import' ? 'import' : 'record'}${previewOnly ? '/preview' : ''}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const raw:unknown = await response.json();
      const failure = errorSchema.safeParse(raw);
      if (failure.success) {
        const first = failure.data.errors[0]; setError(first?.message ?? 'This action was not completed.');
        for (const item of failure.data.errors) if (item.field.startsWith('record.') || ['csvText','filename','occurredOn'].includes(item.field)) form.setError(item.field as FieldPath<MasterInput>,{message:item.message});
        if (first?.field === 'expectedHeadHash') {setPreview(null);setStep(1);}
        return;
      }
      const result = masterResultSchema.parse(raw);
      if (previewOnly) {setPreview(result);setStep(2);}
      else {setSaved(result);setStep(4);toast.success(result.duplicate ? 'Already recorded. No new run was written.' : 'Recorded. Earlier versions are unchanged.');}
    } catch {setError('The action could not be confirmed. Retry the same request; duplicate writes are prevented.');}
    finally {setBusy(false);}
  }
  if (step === 4) return <section className="card"><h2>Recorded</h2><p role="status">{saved?.duplicate ? 'Already imported or recorded. No new run was written.' : 'Your setup action was recorded. The original history stays unchanged.'}</p>{saved?.summary.map((message,index) => <p className="muted" key={index}>{message}</p>)}<Link className="button" href="/setup">Back to setup</Link></section>;
  return <section className="card"><h2>{titles[action]}</h2><FlowProgress step={step} busy={busy} label="Setup flow progress"/>{readOnly && <p className="error" role="alert">History verification failed. All recording is disabled.</p>}{revision && <p className="note">This records a new evidenced version. It never edits the earlier run. Fixed identity fields cannot change.</p>}{step === 0 && <form noValidate onSubmit={form.handleSubmit(() => {setError('');setStep(1);})}><fieldset disabled={readOnly || busy} style={{border:0,padding:0,margin:0}}>{field('occurredOn','Action date',undefined,'date')}
    {action === 'business' && <>{field('record.tradingName','Business name')}{field('record.taxRegime','Business tax regime',[['unregistered','Not registered'],['assessed','Assessed'],['general','General']])}{field('record.taxId','Tax ID (optional)',undefined,'text','Use eight digits if you have a Taiwan tax ID.')}<p className="note">Based in Taiwan · Reporting currency: TWD. Choose the tax regime from your registration, not a guess.</p></>}
    {action === 'supplier' && <>{field('record.supplierRef','Supplier reference',undefined,'text','Use SUP- followed by three digits.',revision)}{field('record.legalName','Supplier legal name',undefined,'text',undefined,revision)}{field('record.country','Country code',undefined,'text','Two uppercase letters, such as TW.',revision)}{field('record.currency','Supplier currency',undefined,'text','Three uppercase letters, such as TWD.',revision)}{field('record.defaultIncoterm','Delivery terms',['EXW','FCA','CPT','CIP','DAP','DPU','DDP','FAS','FOB','CFR','CIF'],'text','Use the Incoterm on the supplier quote.',revision)}{field('record.paymentTerms','When to pay')}{field('record.canInvoiceToTaxId','Can issue an invoice to your tax ID?',['unknown','yes','no'])}{field('record.declarationRef','Supplier declaration reference',undefined,'text','Leave blank until evidenced. Otherwise use compliance/suppliers/ followed by the document reference.')}</>}
    {action === 'product' && <>{field('record.sku','SKU',undefined,'text','Sellable: TS-FL-001-S. Packaging: PKG-BOX-TW.',revision)}{field('record.name','Product name',undefined,'text',undefined,revision)}{field('record.productType','Product type',['sellable','packaging'],'text',undefined,revision)}{field('record.piecesPerSaleUnit','Pieces in one sale unit',undefined,'number','Inventory uses pieces, not packs.',revision)}{field('record.supplierRef','Supplier',[['','Unassigned — add a supplier later'],...projection.suppliers.map(({record}) => [record.supplierRef,`${record.supplierRef} · ${record.legalName}`] as const)],'text',undefined,revision)}{field('record.ingredientRef','Ingredient evidence',undefined,'text','Sellable: UNKNOWN or compliance/suppliers/ reference. Packaging: NOT_APPLICABLE.')}<p className="note">Unverified products can be recorded, but they are not purchase-cleared. Recording is not a compliance certification.</p></>}
    {action === 'channel' && <>{field('record.code','Channel',['etsy','instagram'])}{field('record.name','Channel name',['Etsy','Instagram'])}</>}
    {action === 'opening' && <OpeningFields form={form} projection={projection} />}
    {action === 'reference' && <p className="note">Load only Etsy, Instagram, and the unchanged bilingual approved chart. This creates no journal entries.</p>}
    {action === 'import' && <><label htmlFor="master-file">CSV file</label><input id="master-file" type="file" accept=".csv,text/csv" onChange={(event) => loadFile(event.target.files?.[0])} /><p className="muted" style={{fontSize:12}}>Use an exact dated {initial.action === 'import' ? initial.area : ''} CSV for the current dataset. Quoted commas, multiline cells, and UTF-8 BOM are supported.</p><p><a href={`/api/setup/template?area=${initial.action === 'import' ? initial.area : 'suppliers'}`} style={{textDecoration:'underline'}}>Download current snapshot / template</a></p>{field('filename','Source filename',undefined,'text','Keep the prescribed dated filename; do not put buyer details in filenames.')}{form.getFieldState('csvText',form.formState).error && <p role="alert" className="error">{form.getFieldState('csvText',form.formState).error?.message}</p>}<p className="note">Supplier imports are complete snapshots: missing existing suppliers are refused, never deleted. Product imports require the current v3 header. Channel and chart v1 contracts are authored for v2. No buyer data belongs in these files.</p></>}
    {action !== 'reference' && action !== 'channel' && action !== 'import' && field('record.evidenceRef','Evidence reference',undefined,'text','A stable document or decision reference. Never enter buyer contact details.')}<div style={{marginTop:24}}><Button type="submit" disabled={busy || reading || readOnly}>Check details</Button></div></fieldset></form>}
    {step === 1 && <><p>Check the details and evidence. Next, the server will validate the complete action and show exactly what will be recorded.</p><p className="note">Setup changes do not book money or stock. <Glossary term="Goods receipt" /></p><Button disabled={busy || readOnly} onClick={() => request(true)}>Preview what gets recorded</Button></>}
    {step === 2 && <><h3>What will happen</h3>{preview?.summary.map((message,index) => <p key={index}>{message}</p>)}<details style={{marginBottom:20}}><summary>Accounting view / audit effects</summary><p>No journal entries are posted by this setup action.</p><pre style={{fontSize:12,maxHeight:300,overflow:'auto'}}>{JSON.stringify(preview?.effects,null,2)}</pre></details><Button onClick={() => setStep(3)}>Continue to confirm</Button></>}
    {step === 3 && <><p>Confirm this new permanent record? Earlier runs will remain unchanged.</p><Button disabled={busy || readOnly} onClick={() => request(false)}>Confirm record</Button></>}
    {step > 0 && <Button variant="secondary" disabled={busy} onClick={() => setStep(step - 1)}>Back</Button>}{error && <p className="error" role="alert">{error}</p>}
  </section>;
}
