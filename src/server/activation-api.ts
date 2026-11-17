import 'server-only';
import { activationPayloadSchema } from '../domain/schemas/activation';
import { planActivation } from '../domain/activation';
import { store } from './runtime';
import { readPayload,errorResponse } from './http';
import { financialSummary } from '../domain/financial-summary';
export async function handleActivation(request:Request,preview:boolean){try{const input=activationPayloadSchema.parse(await readPayload(request));const result=await store.execute(runs=>planActivation(input,runs),preview);return Response.json({ok:true,runId:preview?null:result.run.runId,effects:result.run.effects,summary:financialSummary(result.run.effects),duplicate:result.duplicate,preview,headHash:result.run.prevHash});}catch(error){return errorResponse(error);}}
