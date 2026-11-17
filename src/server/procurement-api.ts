import 'server-only';
import { procurementPayloadSchema } from '../domain/schemas/procurement';
import { procurementResultSchema } from '../domain/schemas';
import { planProcurement,procurementSummary } from '../domain/procurement';
import { errorResponse,readPayload } from './http';
import { store } from './runtime';

export async function handleProcurementRequest(request:Request,preview:boolean):Promise<Response>{
  try{
    const input=procurementPayloadSchema.parse(await readPayload(request,1100000));
    const result=await store.execute(runs=>planProcurement(input,runs),preview);
    const warnings:string[]=[];
    if(!result.duplicate)for(const effect of result.run.effects){
      if(effect.type==='procurement.matched'&&effect.record.depositAppliedTwd!==effect.record.invoiceStatedDepositTwd)warnings.push('The computed deposit application differs from the supplier-stated amount. The difference is listed, not posted.');
      if((effect.type==='procurement.invoice'||effect.type==='procurement.receipt')&&!result.run.effects.some(item=>item.type==='procurement.matched'&&item.record.poNumber===effect.record.poNumber&&item.record.receiptNo===effect.record.receiptNo))warnings.push('This document stays unmatched. No inventory or payable is booked; review it in the exceptions list.');
    }
    return Response.json(procurementResultSchema.parse({ok:true,runId:preview?null:result.run.runId,effects:result.run.effects,summary:procurementSummary(result.run.effects),warnings,duplicate:result.duplicate,preview,headHash:result.run.prevHash}));
  }catch(error){return errorResponse(error);}
}
