import { allowLocalRequest, errorResponse } from '@/server/http';
import { store } from '@/server/runtime';
import { projectMasters } from '@/domain/master-projection';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET(request: Request) {
  try { allowLocalRequest(request); return Response.json({ok:true,...projectMasters(await store.read())}); }
  catch (error) { return errorResponse(error); }
}
