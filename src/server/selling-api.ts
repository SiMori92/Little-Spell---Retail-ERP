import 'server-only';
import { z } from 'zod';
import { sellingPayloadSchema, sellingResultSchema, sellingEffectSchema } from '../domain/schemas/selling';
import { normalizeSelling } from '../domain/selling-csv';
import { planSelling, sellingBlockers, sellingSummary } from '../domain/selling';
import { candidateSchema } from '../domain/schemas';
import { readPayload, errorResponse } from './http';
import { store } from './runtime';

export async function handleSellingRequest(request:Request,preview:boolean):Promise<Response> {
  try {
    const input=normalizeSelling(sellingPayloadSchema.parse(await readPayload(request,2200000)));
    if(preview){
      const runs=await store.read(),candidate=candidateSchema.parse(planSelling(input,runs,true));
      const effects=z.array(sellingEffectSchema).parse(candidate.effects);
      return Response.json(sellingResultSchema.parse({ok:true,runId:null,effects,summary:sellingSummary(effects),warnings:effects.flatMap(effect=>effect.type==='selling.import'?effect.warnings:[]),blockers:sellingBlockers(input,runs),duplicate:runs.some(run=>run.idempotencyKey===candidate.idempotencyKey),preview:true,headHash:runs.at(-1)?.hash??'0'.repeat(64)}));
    }
    const result=await store.execute(runs=>planSelling(input,runs));const effects=z.array(sellingEffectSchema).parse(result.run.effects);
    return Response.json(sellingResultSchema.parse({ok:true,runId:result.run.runId,effects,summary:sellingSummary(effects),warnings:effects.flatMap(effect=>effect.type==='selling.import'?effect.warnings:[]),blockers:[],duplicate:result.duplicate,preview:false,headHash:result.run.prevHash}));
  } catch(error){return errorResponse(error);}
}
