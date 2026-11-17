import { z } from 'zod';
import { dateSchema,hashSchema } from './primitives';
import { evidenceText,periodSchema } from './accounting';
import { gateSchema } from './reporting';
export const closePayloadSchema=z.strictObject({action:z.enum(['review','close']),occurredOn:dateSchema,period:periodSchema,actor:evidenceText,evidenceRef:evidenceText,founderAuthorization:evidenceText,idempotencyKey:evidenceText,expectedHeadHash:hashSchema.nullable().default(null)});
export const closeEffectSchemas=[
 z.strictObject({type:z.literal('close.reviewed'),period:periodSchema,actor:evidenceText,evidenceRef:evidenceText}),
 z.strictObject({type:z.literal('close.attempted'),period:periodSchema,actor:evidenceText,founderAuthorization:evidenceText,gates:z.array(gateSchema).length(5),status:z.enum(['CLOSED','BLOCKED']),remaining:z.array(z.string())})
] as const;
