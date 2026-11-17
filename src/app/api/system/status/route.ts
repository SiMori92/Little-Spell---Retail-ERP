import { allowLocalRequest, errorResponse } from '@/server/http';
import { store } from '@/server/runtime';
import { statusPayloadSchema } from '@/domain/schemas';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET(request: Request) {
  try { allowLocalRequest(request); statusPayloadSchema.parse({}); return Response.json({ ok: true, ...await store.status() }); }
  catch (error) { return errorResponse(error); }
}
