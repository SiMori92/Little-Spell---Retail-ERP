import { createHash } from 'node:crypto';
import chart from '../../seed/coa_snapshot.json';
import { approvedChartRows } from './chart';
import manifest from '../../seed/manifest.json';
import Decimal from './decimal';
import { canonical, digest } from './canonical';
import { DomainError } from './errors';
import { readMasterCsv } from './master-csv';
import { projectMasters } from './master-projection';
import { chartAccountSchema, masterPayloadSchema, productSchema, supplierSchema, type ChartAccount, type MasterEffect, type Product, type Supplier } from './schemas/masters';
import { decimalSchema } from './schemas/primitives';
import type { Candidate, Run } from './schemas';

function parseChartRow(row:typeof chart.rows[number]):ChartAccount {return chartAccountSchema.parse({ code:row.account_code, nameEn:row.account_name_en, nameZh:row.account_name_zh, type:row.type, statement:row.statement, normalBalance:row.normal_balance, statutoryCode:row.statutory_code, taxTreatment:row.tax_treatment || null, taxRegime:row.tax_regime, subledger:row.subledger, isReserved:row.is_reserved === 'true', isContra:row.is_contra === 'true', isClosingOnly:row.is_closing_only === 'true', activeFrom:row.active_from || null, activeTo:row.active_to || null });}
export const officialAccounts:ChartAccount[]=chart.rows.map(parseChartRow);
export const approvedAccounts:ChartAccount[]=approvedChartRows.map(parseChartRow);
const hashText = (value: string) => createHash('sha256').update(value,'utf8').digest('hex');
const placeholder = '00000000-0000-4000-8000-000000000000';
function refuse(field: string, message: string): never { throw new DomainError(field,message); }
function candidateFromRun(run: Run): Candidate { return {kind:run.kind,dataset:run.dataset,occurredOn:run.occurredOn,input:run.input,idempotencyKey:run.idempotencyKey,effects:run.effects}; }

export function planMasters(raw: unknown, runs: readonly Run[]): Candidate {
  const input = masterPayloadSchema.parse(raw);
  const projection = projectMasters(runs);
  const dataset = projection.dataset;
  let key = `masters-record:${input.idempotencyKey}`;
  let kind: Candidate['kind'] = 'masters.record';
  if (input.action === 'import') {
    readMasterCsv(input.area,input.filename,input.csvText,dataset);
    key = `masters-import:${dataset}:${input.area}:${hashText(input.csvText)}`;
    kind = 'masters.import';
  }
  if (input.action === 'bootstrap') { key = `masters-bootstrap:${dataset}:${digest({suppliersCsv:input.suppliersCsv,productsCsv:input.productsCsv})}`; kind = 'masters.bootstrap'; }
  const existing = runs.find((run) => run.idempotencyKey === key);
  if (existing) {
    if (input.action !== 'import' && canonical(existing.input) !== canonical(input)) refuse('idempotencyKey','This request was already used for a different action. Reload the form.');
    return candidateFromRun(existing);
  }
  if (input.expectedHeadHash && input.expectedHeadHash !== (runs.at(-1)?.hash ?? '0'.repeat(64))) refuse('expectedHeadHash','Records changed since your preview. Preview again before confirming.');
  const effects: MasterEffect[] = [];
  const suppliers = new Map(projection.suppliers.map((item) => [item.record.supplierRef,item]));
  const products = new Map(projection.products.map((item) => [item.record.sku,item]));
  const channels = new Set(projection.channels.map((item) => item.record.code));
  const accounts = new Map(projection.accounts.map((item) => [item.record.code,item.record]));
  function supplier(record: Supplier, previousRunId: string | null) {
    const prior = suppliers.get(record.supplierRef);
    if ((prior?.runId ?? null) !== previousRunId) refuse('previousRunId','This supplier has changed, or already exists. Reopen its latest record before continuing.');
    const mutable = ['declarationRef','canInvoiceToTaxId','paymentTerms'] as const;
    if (prior && (['legalName','country','currency','defaultIncoterm'] as const).some((field) => prior.record[field] !== record[field])) refuse('record','Supplier identity, country, currency, and Incoterm cannot change. Create a new supplier reference instead.');
    const changes = prior ? mutable.filter((field) => prior.record[field] !== record[field]).map((field) => ({field,old:prior.record[field],new:record[field],evidenceRef:record.evidenceRef})) : [];
    if (prior && !changes.length) return;
    effects.push({type:'supplier.recorded',record,previousRunId,changes});
    suppliers.set(record.supplierRef,{record,runId:prior?.runId ?? placeholder,createdAt:prior?.createdAt ?? '2026-11-16T00:00:00.000Z',sourceFilename:'planned'});
  }
  function product(record: Product, previousRunId: string | null) {
    const prior = products.get(record.sku);
    if ((prior?.runId ?? null) !== previousRunId) refuse('previousRunId','This product has changed, or already exists. Reopen its latest record before continuing.');
    const linked = record.supplierRef ? suppliers.get(record.supplierRef) : null;
    if (record.supplierRef && !linked) refuse('record.supplierRef','Add this supplier in the current dataset before assigning it to a product.');
    if (record.ingredientRef.startsWith('compliance/suppliers/') && !linked?.record.declarationRef) refuse('record.ingredientRef','Record the supplier declaration before clearing this product.');
    if (prior && (['name','uom','piecesPerSaleUnit','supplierRef','productType'] as const).some((field) => prior.record[field] !== record[field])) refuse('record','Product identity, supplier, sale-unit conversion, and type cannot change. Create a new SKU instead.');
    const changes = prior && prior.record.ingredientRef !== record.ingredientRef ? [{field:'ingredientRef',old:prior.record.ingredientRef,new:record.ingredientRef,evidenceRef:record.evidenceRef}] : [];
    if (prior && !changes.length) return;
    effects.push({type:'product.recorded',record,previousRunId,changes});
    products.set(record.sku,{record,runId:prior?.runId ?? placeholder,createdAt:prior?.createdAt ?? '2026-11-16T00:00:00.000Z',sourceFilename:'planned'});
  }
  function account(record: ChartAccount) {
    const official = approvedAccounts.find((item) => item.code === record.code);
    if (!official || canonical(record) !== canonical(official)) refuse('csvText','The chart is frozen. Import the unchanged bilingual chart; custom or plug accounts are not allowed.');
    const prior = accounts.get(record.code);
    if (prior && canonical(prior) !== canonical(record)) refuse('csvText','An account differs from the approved chart. Nothing was changed.');
    if (!prior) { effects.push({type:'account.recorded',record}); accounts.set(record.code,record); }
  }
  function references() {
    for (const record of [{code:'etsy',name:'Etsy'},{code:'instagram',name:'Instagram'}] as const) if (!channels.has(record.code)) { effects.push({type:'channel.recorded',record}); channels.add(record.code); }
    for (const record of officialAccounts) account(record);
  }
  function importRows(area: 'suppliers' | 'products' | 'channels' | 'accounts', filename: string, csvText: string) {
    const rows = readMasterCsv(area,filename,csvText,dataset);
    const seen = new Set<string>();
    const before = effects.length;
    let revisions = 0;
    if (area === 'suppliers') {
      const records = rows.map((row) => supplierSchema.parse(row));
      const refs = new Set(records.map((record) => record.supplierRef));
      if ([...suppliers.keys()].some((ref) => !refs.has(ref))) refuse('csvText','A supplier snapshot must include every existing supplier. Missing rows are never deletions.');
      for (const record of records) {
        if (seen.has(record.supplierRef)) refuse('csvText','A supplier reference repeats in this CSV. Nothing was imported.');
        seen.add(record.supplierRef);
        const prior = suppliers.get(record.supplierRef); const count = effects.length;
        supplier(record,prior?.runId ?? null); if (prior && effects.length > count) revisions++;
      }
    } else if (area === 'products') {
      for (const row of rows) {
        const record = productSchema.parse(row);
        if (seen.has(record.sku)) refuse('csvText','A SKU repeats in this CSV. Nothing was imported.');
        seen.add(record.sku); const prior = products.get(record.sku); const count = effects.length;
        product(record,prior?.runId ?? null); if (prior && effects.length > count) revisions++;
      }
    } else if (area === 'channels') {
      for (const row of rows) {
        const record = row as Extract<MasterEffect,{type:'channel.recorded'}>['record'];
        if (seen.has(record.code)) refuse('csvText','A sales channel repeats in this CSV. Nothing was imported.'); seen.add(record.code);
        if (!channels.has(record.code)) { effects.push({type:'channel.recorded',record}); channels.add(record.code); }
      }
    } else {
      for (const row of rows) {
        const record = chartAccountSchema.parse(row);
        if (seen.has(record.code)) refuse('csvText','An account repeats in this CSV. Nothing was imported.'); seen.add(record.code); account(record);
      }
    }
    const added = effects.length - before;
    effects.push({type:'masters.imported',area,filename,sourceHash:hashText(csvText),parsedRows:rows.length,recordsCreated:added-revisions,revisionsCreated:revisions});
  }
  if (input.action === 'supplier') supplier(input.record,input.previousRunId);
  if (input.action === 'product') product(input.record,input.previousRunId);
  if (input.action === 'channel' && !channels.has(input.record.code)) effects.push({type:'channel.recorded',record:input.record});
  if (input.action === 'reference') references();
  if (input.action === 'import') importRows(input.area,input.filename,input.csvText);
  if (input.action === 'business') {
    if ((projection.business?.runId ?? null) !== input.previousRunId) refuse('previousRunId','Business details changed. Reopen the latest version before continuing.');
    if (canonical(projection.business?.record ?? null) !== canonical(input.record)) effects.push({type:'business.recorded',record:input.record,previousRunId:input.previousRunId});
  }
  if (input.action === 'opening') {
    if (!projection.business || !projection.products.length || !projection.suppliers.length) refuse('record','Complete business details, products, and suppliers before preparing opening stock.');
    if ((projection.opening?.runId ?? null) !== input.previousRunId) refuse('previousRunId','The opening preparation changed. Reopen its latest version.');
    if (input.record.countedOn !== input.occurredOn) refuse('record.countedOn','Use the count date as the action date.');
    for (const line of input.record.lines) if (!products.has(line.sku)) refuse('record.lines','Choose products already recorded in this dataset.');
    const total = input.record.lines.reduce((value,line) => value.plus(new Decimal(line.qtyPieces).times(line.agreedUnitCostTwd)),new Decimal(0));
    effects.push({type:'opening.prepared',record:input.record,previousRunId:input.previousRunId,totalPreparedValueTwd:decimalSchema.parse(total.toFixed(4))});
  }
  if (input.action === 'bootstrap') {
    if (dataset !== 'SAMPLE' || runs.some((run) => run.kind.startsWith('masters.'))) refuse('action','Synthetic master seeding needs an untouched SAMPLE master workspace.');
    for (const [path,csv] of [['samples/SAMPLE_suppliers_2026-09-27.csv',input.suppliersCsv],['samples/SAMPLE_products_2026-09-27.csv',input.productsCsv]]) {
      if (hashText(csv!) !== manifest.find((fixture) => fixture.path === path)?.sha256) refuse('action','Bundled master fixtures failed verification.');
    }
    references();
    importRows('suppliers','SAMPLE_suppliers_2026-09-27.csv',input.suppliersCsv);
    importRows('products','SAMPLE_products_2026-09-27.csv',input.productsCsv);
    effects.push({type:'masters.initialized',version:1});
  }
  if (!effects.length) refuse('record','Nothing changed. The original record remains on file.');
  return {kind,dataset,occurredOn:input.occurredOn,input:structuredClone(input),effects:structuredClone(effects),idempotencyKey:key};
}

export function validateMasterCandidate(candidate: Candidate, runs: readonly Run[]): void {
  const planned = planMasters(candidate.input,runs);
  if (canonical(planned) !== canonical(candidate)) refuse('record','The saved master effects do not match the validated request.');
}

export function masterSummary(effects: readonly MasterEffect[]): string[] {
  const summaries: string[] = [];
  const suppliers = effects.filter((effect) => effect.type === 'supplier.recorded');
  const products = effects.filter((effect) => effect.type === 'product.recorded');
  if (suppliers.length) summaries.push(`${suppliers.length} supplier record(s), with earlier versions kept unchanged.`);
  if (products.length) summaries.push(`${products.length} product record(s). Inventory is measured in pieces; sales use the recorded conversion.`);
  for (const effect of effects) {
    if (effect.type === 'business.recorded') summaries.push('Business details recorded as a new version.');
    if (effect.type === 'opening.prepared') summaries.push(effect.record.mode === 'no_stock' ? 'Your no-opening-stock declaration will be saved. No stock or journal entry is booked.' : `Opening stock preparation: NT$${effect.totalPreparedValueTwd}. This is NOT posted stock or an opening journal.`);
    if (effect.type === 'masters.imported') summaries.push(`${effect.parsedRows} row(s) checked: ${effect.recordsCreated} new record(s), ${effect.revisionsCreated} audited revision(s).`);
  }
  if (!summaries.length) summaries.push('Approved reference data will be recorded.');
  summaries.push('No money, payable, sales, or stock movement is booked by this setup action.');
  return summaries;
}
