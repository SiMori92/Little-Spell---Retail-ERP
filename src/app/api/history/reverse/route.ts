import { reversalPayloadSchema } from '@/domain/schemas';
import { planReversal } from '@/domain/reversal';
import { errorResponse, readPayload } from '@/server/http';
import { store } from '@/server/runtime';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function POST(request: Request) {
  try {
    const input = reversalPayloadSchema.parse(await readPayload(request));
    const result = await store.execute((runs) => planReversal(input, runs));
    return Response.json({ ok: true, runId: result.run.runId, effects: result.run.effects, duplicate: result.duplicate });
  } catch (error) { return errorResponse(error); }
}
