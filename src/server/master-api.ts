import 'server-only';
import { z } from 'zod';
import { planMasters, masterSummary } from '../domain/masters';
import { importPayloadSchema, masterEffectSchema, masterResultSchema, recordMasterPayloadSchema } from '../domain/schemas/masters';
import { errorResponse, readPayload } from './http';
import { store } from './runtime';

export async function handleMasterRequest(request: Request, preview: boolean, importOnly = false): Promise<Response> {
  try {
    const raw = await readPayload(request, importOnly ? 1052672 : 65536);
    const input = (importOnly ? importPayloadSchema : recordMasterPayloadSchema).parse(raw);
    const result = await store.execute((runs) => planMasters(input,runs),preview);
    const effects = z.array(masterEffectSchema).parse(result.run.effects);
    return Response.json(masterResultSchema.parse({ok:true,runId:preview ? null : result.run.runId,effects,summary:masterSummary(effects),duplicate:result.duplicate,preview,headHash:result.run.prevHash}));
  } catch (error) { return errorResponse(error); }
}
