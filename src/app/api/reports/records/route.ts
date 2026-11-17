import { store } from '@/server/runtime';
import { allowLocalRequest,errorResponse } from '@/server/http';
import { operatingReports } from '@/domain/operating-reports';
import { buildReports } from '@/domain/reporting';
import { periodSchema } from '@/domain/schemas/accounting';
import { closeGates } from '@/domain/closing';
export const runtime='nodejs';
export const dynamic='force-dynamic';
export async function GET(request:Request){try{allowLocalRequest(request);const period=periodSchema.parse(new URL(request.url).searchParams.get('period')),runs=await store.read();return Response.json({ok:true,reports:[...buildReports(runs,period),...operatingReports(runs,period)],gates:closeGates(runs,period)});}catch(error){return errorResponse(error);}}
