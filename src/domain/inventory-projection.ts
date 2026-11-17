import type { Dataset, Run } from './schemas';
import { projectMasters } from './master-projection';
import { inventoryProjectionSchema, inventoryOperationSchema, type InventoryProjection } from './schemas/procurement';
import { z } from 'zod';
import Decimal from './decimal';
import { exactMoney } from './landed-cost';
import { DomainError } from './errors';

export function projectInventory(runs:readonly Run[],dataset:Dataset=runs.some(run=>run.effects.some(effect=>effect.type==='dataset.activated'))?'ACTUAL':'SAMPLE',through='9999-12-31'):InventoryProjection{
  const masters=projectMasters(runs,dataset),products=new Map(masters.products.map(item=>[item.record.sku,item.record]));
  const positions=new Map(masters.products.filter(item=>item.record.productType==='sellable').map(item=>[item.record.sku,{qty:new Decimal(0),value:new Decimal(0),evidenced:false}]));
  const operations=z.array(inventoryOperationSchema).parse(runs.filter(run=>run.dataset===dataset).flatMap((run,runIndex)=>run.effects.flatMap<z.infer<typeof inventoryOperationSchema>>((effect,effectIndex)=>{
    const ordinal=runIndex*100000+effectIndex;
    if(effect.type==='stock.moved'&&effect.move.condition==='sellable')return [{date:run.occurredOn,ordinal,sku:effect.move.sku,qty:effect.move.qtyPieces,value:effect.move.valueTwd,orderId:''}];
    if(effect.type==='procurement.movement')return [{date:effect.record.occurredOn,ordinal,sku:effect.record.sku,qty:effect.record.qtyPieces,value:effect.record.valueTwd,orderId:''}];
    if(effect.type==='selling.shipment')return effect.record.lines.map(line=>({date:effect.record.shipDate,ordinal,sku:line.sku,qty:new Decimal(line.qtyPieces).negated().toFixed(0),value:null,orderId:effect.record.orderId}));
    if(effect.type==='procurement.count')return effect.record.lines.filter(line=>line.condition==='sellable').map(line=>({date:effect.record.countedAt,ordinal:runIndex*100000+99999,sku:line.sku,qty:'0',value:exactMoney('0'),orderId:'',targetPieces:line.qtyPieces}));
    return [];
  }))).filter(item=>item.date<=through).sort((left,right)=>left.date.localeCompare(right.date)||left.ordinal-right.ordinal);
  const consumptions:InventoryProjection['consumptions']=[];
  for(const operation of operations){if(products.get(operation.sku)?.productType!=='sellable')continue;const position=positions.get(operation.sku)!;const qty=new Decimal(operation.qty);
    position.evidenced=true;
    if(operation.targetPieces!==undefined){if(!position.qty.eq(operation.targetPieces))throw new DomainError('stock','Backdated activity contradicts a booked physical count. Use a separately evidenced correction instead.');continue;}
    if(position.qty.plus(qty).isNegative())throw new DomainError('stock','Recorded stock would be negative on an effective date. Review the dated movements before continuing.');
    if(operation.value===null){if(position.qty.lte(0))throw new DomainError('stock','A dispatch has no evidenced weighted-average position.');const cost=qty.negated().eq(position.qty)?exactMoney(position.value):exactMoney(position.value.times(qty.negated()).div(position.qty));position.qty=position.qty.plus(qty);position.value=position.value.minus(cost);consumptions.push({orderId:operation.orderId,sku:operation.sku,shipDate:operation.date,qtyPieces:qty.negated().toFixed(0),costTwd:cost,status:'UNPOSTED'});}
    else{position.qty=position.qty.plus(qty);position.value=position.value.plus(operation.value);}
    if(position.value.isNegative()||position.qty.isZero()&&!position.value.isZero())throw new DomainError('stock','The quantity and exact stock value do not tie. No rounding plug can be added.');
  }
  for(const consumption of consumptions){const event=runs.filter(r=>r.dataset===dataset).flatMap(r=>r.effects.flatMap(e=>e.type==='selling.event'&&e.record.eventType==='order.cogs_relieved'&&e.record.entityRef===consumption.orderId?[e.record]:[]))[0];const posted=runs.filter(r=>r.dataset===dataset).flatMap(r=>r.effects.flatMap(e=>e.type==='accounting.posted'&&e.eventId===event?.eventId?[e]:[]))[0];if(posted){const lines=runs.flatMap(r=>r.effects.flatMap(e=>e.type==='journal.posted'&&e.entry.entryId===posted.entryId?e.entry.lines:[]));const booked=lines.filter(l=>l.account.code==='5111'&&l.sku===consumption.sku).reduce((sum,l)=>sum.plus(l.debit).minus(l.credit),new Decimal(0));if(!booked.eq(consumptions.filter(c=>c.orderId===consumption.orderId&&c.sku===consumption.sku).reduce((sum,c)=>sum.plus(c.costTwd),new Decimal(0))))throw new DomainError('stock','Backdated activity would change an already posted dispatch cost. Use an evidenced cost correction.');consumption.status='POSTED';}}
  const rows=[...positions].map(([sku,position])=>({sku,qtyPieces:position.qty.toFixed(0),valueTwd:exactMoney(position.value),wacPerPiece:position.qty.isZero()?null:exactMoney(position.value.div(position.qty)),evidenced:position.evidenced}));
  return inventoryProjectionSchema.parse({positions:rows,consumptions,totalValueTwd:exactMoney(rows.reduce((sum,row)=>sum.plus(row.valueTwd),new Decimal(0))),pendingCogsTwd:exactMoney(consumptions.filter(item=>item.status==='UNPOSTED').reduce((sum,item)=>sum.plus(item.costTwd),new Decimal(0))),openingRecorded:runs.some(run=>run.dataset===dataset&&run.effects.some(effect=>effect.type==='procurement.count'&&effect.kind==='opening'&&effect.record.countedAt<=through||effect.type==='journal.posted'&&effect.entry.sourceEvent==='inventory.opening_counted'&&effect.entry.occurredOn<=through))});
}
