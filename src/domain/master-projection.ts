import { masterProjectionSchema, type MasterProjection } from './schemas/masters';
import type { Dataset, Run } from './schemas';

export function projectMasters(runs: readonly Run[], dataset: Dataset = runs.some((run) => run.effects.some((effect) => effect.type === 'dataset.activated')) ? 'ACTUAL' : 'SAMPLE'): MasterProjection {
  const result: MasterProjection = { dataset, suppliers:[], products:[], channels:[], accounts:[], business:null, opening:null, history:[] };
  for (const run of runs) {
    if (run.dataset !== dataset) continue;
    const sourceFilename = run.kind === 'masters.bootstrap' ? 'bundled SAMPLE masters' : typeof run.input === 'object' && run.input !== null && 'filename' in run.input && typeof run.input.filename === 'string' ? run.input.filename : 'manual entry';
    const fields = {runId:run.runId, createdAt:run.createdAt, sourceFilename};
    for (const effect of run.effects) {
      if (effect.type === 'supplier.recorded') { result.suppliers = result.suppliers.filter((item) => item.record.supplierRef !== effect.record.supplierRef); result.suppliers.push({...fields,record:effect.record}); result.history.push({...fields,entity:'supplier',key:effect.record.supplierRef,changes:effect.changes}); }
      if (effect.type === 'product.recorded') { result.products = result.products.filter((item) => item.record.sku !== effect.record.sku); result.products.push({...fields,record:effect.record}); result.history.push({...fields,entity:'product',key:effect.record.sku,changes:effect.changes}); }
      if (effect.type === 'channel.recorded') { result.channels.push({...fields,record:effect.record}); }
      if (effect.type === 'account.recorded' || effect.type === 'procurement.account') { result.accounts.push({...fields,record:effect.record}); }
      if (effect.type === 'business.recorded') result.business = {...fields,record:effect.record};
      if (effect.type === 'opening.prepared') result.opening = {...fields,record:effect.record,totalPreparedValueTwd:effect.totalPreparedValueTwd};
    }
  }
  return masterProjectionSchema.parse(result);
}
