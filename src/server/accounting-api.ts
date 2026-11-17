import 'server-only';
import { accountingPayloadSchema } from '../domain/schemas/accounting';
import { closePayloadSchema } from '../domain/schemas/closing';
import { planAccounting } from '../domain/accounting';
import { planClose } from '../domain/closing';
import { store } from './runtime';
import { readPayload,errorResponse } from './http';
import { financialSummary } from '../domain/financial-summary';
export async function handleAccounting(request:Request,preview:boolean,area:'money'|'close'){
 try{const raw=await readPayload(request,1100000),input=area==='money'?accountingPayloadSchema.parse(raw):closePayloadSchema.parse(raw);const result=await store.execute(runs=>area==='money'?planAccounting(input,runs):planClose(input,runs),preview);
 return Response.json({ok:true,runId:preview?null:result.run.runId,effects:result.run.effects,summary:financialSummary(result.run.effects),duplicate:result.duplicate,preview,headHash:result.run.prevHash});
 }catch(error){return errorResponse(error);}
}
