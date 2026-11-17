import { store } from '@/server/runtime';
import { allowLocalRequest, errorResponse } from '@/server/http';
import { projectSelling } from '@/domain/selling-projection';
export const runtime='nodejs';
export const dynamic='force-dynamic';
export async function GET(request:Request){try{allowLocalRequest(request);return Response.json({ok:true,...projectSelling(await store.read())});}catch(error){return errorResponse(error);}}
