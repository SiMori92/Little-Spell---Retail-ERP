import { allowLocalRequest, errorResponse } from '@/server/http';
import { store } from '@/server/runtime';
import { masterAreaSchema } from '@/domain/schemas/masters';
import { exportMasters } from '@/domain/master-export';
import { projectMasters } from '@/domain/master-projection';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET(request: Request) {
  try {
    allowLocalRequest(request);
    const area = masterAreaSchema.parse(new URL(request.url).searchParams.get('area'));
    const projection = projectMasters(await store.read());
    const filename = `${projection.dataset === 'SAMPLE' ? 'SAMPLE_' : ''}${area}_${new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Taipei'})}.csv`;
    return new Response(exportMasters(area,projection),{headers:{'content-type':'text/csv; charset=utf-8','content-disposition':`attachment; filename="${filename}"`,'cache-control':'no-store'}});
  } catch (error) { return errorResponse(error); }
}
