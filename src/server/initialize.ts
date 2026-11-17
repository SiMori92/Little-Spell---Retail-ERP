import 'server-only';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { z } from 'zod';
import { digest } from '../domain/canonical';
import { IntegrityError, RunStore } from './store';
import { planMasters } from '../domain/masters';
import { planSelling } from '../domain/selling';

const manifestSchema = z.array(z.strictObject({ path: z.string().regex(/^(samples|fixtures)\/(?:[a-zA-Z0-9_-]+\/)*SAMPLE_[a-zA-Z0-9_.-]+\.csv$/), sha256: z.string().regex(/^[a-f0-9]{64}$/) })).min(1);
export async function initializeWorkspace(directory = resolve(process.env.ERP_DATA_DIR ?? 'data')) {
  const store = new RunStore(directory);
  try { await store.initialize(); }
  catch (error) { if (!(error instanceof IntegrityError)) throw error; return store.status(); }
  const manifest = manifestSchema.parse(JSON.parse(await readFile(resolve('seed/manifest.json'), 'utf8')));
  for (const fixture of manifest) {
    const body = await readFile(resolve('seed', fixture.path));
    if (createHash('sha256').update(body).digest('hex') !== fixture.sha256) throw new Error('A bundled synthetic fixture failed verification.');
  }
  await store.execute((runs) => {
    const existing = runs.find((run) => run.kind === 'sample.seed');
    return {
      kind: 'sample.seed', dataset: 'SAMPLE', occurredOn: '2026-11-16',
      input: { source: 'bundled-synthetic-fixtures', featureImportsPending: true },
      effects: [{ type: 'seed.registered', manifestHash: digest(manifest), fixtureCount: manifest.length }],
      idempotencyKey: existing?.idempotencyKey ?? `sample-fixtures:${digest(manifest)}`
    };
  });
  const runs = await store.read();
  if (!runs.some((run) => run.kind.startsWith('masters.') || run.effects.some((effect) => effect.type === 'dataset.activated'))) {
    const suppliersCsv = await readFile(resolve('seed/samples/SAMPLE_suppliers_2026-09-27.csv'),'utf8');
    const productsCsv = await readFile(resolve('seed/samples/SAMPLE_products_2026-09-27.csv'),'utf8');
    await store.execute((history) => planMasters({action:'bootstrap',occurredOn:'2026-11-16',idempotencyKey:'sample-master-bootstrap-v1',suppliersCsv,productsCsv},history));
  }
  const history = await store.read();
  if (!history.some(run => run.kind === 'selling.record' || run.effects.some(effect => effect.type === 'dataset.activated'))) {
    const csvText = await readFile(resolve('seed/samples/SAMPLE_ig_deals_2026-10.csv'),'utf8');
    await store.execute(records => planSelling({action:'ig-import',occurredOn:'2026-11-16',idempotencyKey:'sample-ig-bootstrap-v1',filename:'SAMPLE_ig_deals_2026-10.csv',csvText},records));
  }
  return store.status();
}
