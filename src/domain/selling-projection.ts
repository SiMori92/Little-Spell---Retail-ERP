import type { Dataset, Run } from './schemas';
import { sellingProjectionSchema, type SellingProjection } from './schemas/selling';

export function projectSelling(runs:readonly Run[],dataset:Dataset=runs.some(run=>run.effects.some(effect=>effect.type==='dataset.activated'))?'ACTUAL':'SAMPLE'):SellingProjection {
  const result:SellingProjection={dataset,orders:[],statements:[],deals:[],shipments:[],events:[],history:[],verified:false};
  for(const run of runs){if(run.dataset!==dataset)continue;for(const effect of run.effects){
    if(effect.type==='selling.order')result.orders.push({runId:run.runId,record:effect.record});
    if(effect.type==='selling.statement')result.statements.push(effect.record);
    if(effect.type==='selling.shipment')result.shipments.push(effect.record);
    if(effect.type==='selling.event')result.events.push(effect.record);
    if(effect.type==='selling.verified')result.verified=true;
    if(effect.type==='selling.deal'){result.deals=result.deals.filter(item=>item.record.dealId!==effect.record.dealId);result.deals.push({runId:run.runId,record:effect.record});result.history.push({runId:run.runId,createdAt:run.createdAt,record:effect.record,effectiveOn:effect.effectiveOn});}
  }}
  return sellingProjectionSchema.parse(result);
}
