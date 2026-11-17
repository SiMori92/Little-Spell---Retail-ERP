import { z } from 'zod';
import Decimal from '../decimal';
import { dateSchema,decimalSchema,hashSchema } from './primitives';
import { evidenceText } from './accounting';
export const openingLineSchema=z.strictObject({account:z.string().regex(/^\d{4}$/),debit:decimalSchema.refine(v=>new Decimal(v).gte(0)),credit:decimalSchema.refine(v=>new Decimal(v).gte(0))}).refine(l=>new Decimal(l.debit).isZero()!==new Decimal(l.credit).isZero(),'Enter one positive side per line.');
const fields={occurredOn:dateSchema,idempotencyKey:evidenceText,expectedHeadHash:hashSchema.nullable().default(null),founderAuthorization:evidenceText,evidenceRef:evidenceText};
export const activationPayloadSchema=z.discriminatedUnion('action',[
 z.strictObject({action:z.literal('actual-opening'),...fields,lines:z.array(openingLineSchema).min(2).max(100)}),
 z.strictObject({action:z.literal('activate'),...fields})
]);
