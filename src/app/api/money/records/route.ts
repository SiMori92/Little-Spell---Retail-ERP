import { store } from '@/server/runtime';
import { allowLocalRequest,errorResponse } from '@/server/http';
import { accountingState,pendingAccounting } from '@/domain/accounting';
export const runtime='nodejs';
export const dynamic='force-dynamic';
export async function GET(request:Request){try{allowLocalRequest(request);const runs=await store.read();return Response.json({ok:true,...accountingState(runs),queue:pendingAccounting(runs)});}catch(error){return errorResponse(error);}}
