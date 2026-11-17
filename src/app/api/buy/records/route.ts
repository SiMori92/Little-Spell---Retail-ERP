import { store } from '@/server/runtime';
import { allowLocalRequest,errorResponse } from '@/server/http';
import { projectProcurement } from '@/domain/procurement-projection';
import { projectInventory } from '@/domain/inventory-projection';
export const runtime='nodejs';
export const dynamic='force-dynamic';
export async function GET(request:Request){try{allowLocalRequest(request);const runs=await store.read();return Response.json({ok:true,procurement:projectProcurement(runs),inventory:projectInventory(runs)});}catch(error){return errorResponse(error);}}
